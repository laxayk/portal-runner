"""Zoho Invoice (India data center) adapter.

Flow: sign in (email, password, then a 6 digit authenticator code) -> Invoices -> New invoice ->
fill customer, date, payment terms (sets the due date), item (sets the rate), quantity -> Save as Draft
-> PDF/Print -> PDF (a real download). Drafts only. Nothing is ever sent to a customer.
"""
import logging
import os
import re
from datetime import datetime, timedelta

from ..errors import FinalError, RetryableError
from ..resolver import Target
from ..runner import Portal, second_factor

log = logging.getLogger("portal_runner.zoho")

SIGNIN = "https://accounts.zoho.in/signin?servicename=ZohoInvoice"
APP = "https://invoice.zoho.in/app/%s"

T = {
    "login_id": Target("login_id", role="textbox", name="Email address or mobile number", structure="input[name=LOGIN_ID]", id="login_id"),
    "password": Target("password", label="Enter password", structure="input[type=password]", id="password"),
    "next": Target("next", role="button", name="Next", tag="button", structure="button#nextbtn", id="nextbtn"),
    "otp_box": Target("otp_box", structure="input[type=tel]", group=True),
    "nav_invoices": Target("nav_invoices", role="link", name="Invoices", tag="a", structure="a[href*='#/invoices']"),
    "customer": Target("customer", role="combobox", name="Customer Name", nearby="Customer Name*", tag="input", structure="[data-binding-key=customer_id] [role=combobox]"),
    "invoice_date": Target("invoice_date", role="textbox", name="Invoice Date", nearby="Invoice Date*", structure="input[data-integrity=date]"),
    "terms": Target("terms", role="combobox", name="Terms", nearby="Terms", structure="[data-binding-key=payment_terms_label] [role=combobox]"),
    "due_date": Target("due_date", role="textbox", name="Due Date", nearby="Due Date", structure="input.zf-date-picker.editable"),
    "item": Target("item", role="combobox", name="Type or click to select an item", structure="input[aria-label^='Type or click']"),
    "quantity": Target("quantity", role="textbox", name="Quantity", structure="input[data-integrity$='quantity']"),
    "rate": Target("rate", role="textbox", name="Rate", structure="input[data-integrity$='rate']"),
    "save_draft": Target("save_draft", role="button", name="Save as Draft", tag="button", structure="button:has-text('Save as Draft')"),
    "pdf_menu": Target("pdf_menu", role="button", name="PDF/Print", tag="button", structure="button:has-text('PDF/Print')"),
    "pdf_item": Target("pdf_item", role="button", name="PDF", tag="button", structure="button:has-text('PDF')"),
}

DIGITS = re.compile(r"^\d{6}$")


def due_date_for(invoice_date, terms):
    """What the portal should show as due date for the terms we choose, used as a cross check."""
    d = datetime.strptime(invoice_date, "%d/%m/%Y")
    m = re.match(r"Net (\d+)$", terms)
    if m:
        return (d + timedelta(days=int(m.group(1)))).strftime("%d/%m/%Y")
    if terms == "Due on Receipt":
        return invoice_date
    return None  # month-end terms: not cross checked


class ZohoInvoice(Portal):
    name = "zoho-invoice-in"

    def __init__(self, org_id):
        self.org_id = org_id
        self.home = APP % org_id + "#/home"

    # ---- session -------------------------------------------------------------------------------
    async def is_logged_in(self, page, resolver):
        """Alive only if the app itself renders its own navigation. A URL check alone is not enough:
        an expired session can leave the app shell up with no data, or bounce to accounts.zoho.in."""
        await page.goto(self.home, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        host = page.url.split("/")[2] if "//" in page.url else ""
        if host != "invoice.zoho.in":
            log.info("session check: redirected to %s", host)
            return False
        try:
            await page.get_by_role("link", name="Invoices").first.wait_for(state="visible", timeout=15000)
        except Exception:  # noqa: BLE001
            log.info("session check: app navigation did not render")
            return False
        body = (await page.inner_text("body"))[:3000].lower()
        if "session expired" in body or "sign in again" in body:
            return False
        await resolver.resolve(page, T["nav_invoices"])
        return True

    async def login(self, page, resolver, get_code, creds):
        await page.goto(SIGNIN, wait_until="domcontentloaded")
        await (await resolver.resolve(page, T["login_id"])).fill(creds["email"])
        await (await resolver.resolve(page, T["next"])).click()
        pw = await resolver.resolve(page, T["password"])
        await pw.fill(creds["password"])
        await (await resolver.resolve(page, T["next"])).click()
        await page.wait_for_timeout(3000)
        if "accounts.zoho.in" in page.url and await page.locator("input[type=tel]").count():
            await self._otp(page, resolver, get_code)
        await page.wait_for_url(re.compile(r"invoice\.zoho\.in|accounts\.zoho\.in/(home|trustbrowser)"), timeout=30000)
        if not await self.is_logged_in(page, resolver):
            raise FinalError("signed in but the app did not load")

    async def _otp(self, page, resolver, get_code):
        async def submit(code):
            if not DIGITS.match(code):
                raise FinalError("code is not 6 digits")
            first = await resolver.resolve(page, T["otp_box"])
            await first.click()
            await page.keyboard.type(code, delay=60)  # six separate boxes advance on each key
            btn = page.locator("#totpverifybtn, #nextbtn").locator("visible=true")
            if await btn.count():
                await btn.first.click()

        async def rejected():
            try:
                await page.wait_for_url(re.compile(r"invoice\.zoho\.in|trustbrowser|accounts\.zoho\.in/home"), timeout=9000)
                return False
            except Exception:  # noqa: BLE001
                return True

        await second_factor(self.name, get_code, submit, rejected)
        # "Trust this browser" prompt, if shown: decline, so the session is the only thing we rely on.
        try:
            await page.get_by_role("button", name=re.compile("Skip|Not now|No", re.I)).first.click(timeout=2500)
        except Exception:  # noqa: BLE001
            pass

    # ---- work ----------------------------------------------------------------------------------
    async def _pick(self, page, box, text):
        """Zoho dropdowns are custom widgets, not <select>. Open, type to filter, click the option."""
        await box.click()
        await page.keyboard.type(text, delay=40)
        opt = page.get_by_text(text, exact=False).locator("visible=true").last
        await opt.wait_for(state="visible", timeout=8000)
        await opt.click()

    async def perform(self, page, resolver, inputs, out_dir, visit):
        os.makedirs(out_dir, exist_ok=True)
        await page.goto(self.home, wait_until="domcontentloaded")  # page 1
        await (await resolver.resolve(page, T["nav_invoices"])).click()  # page 2: list
        await page.wait_for_url(re.compile(r"#/invoices"), timeout=15000)
        await page.goto(APP % self.org_id + "#/invoices/new", wait_until="domcontentloaded")  # page 3: form
        visit(page.url)

        await self._pick(page, await resolver.resolve(page, T["customer"]), inputs["customer"])
        date = await resolver.resolve(page, T["invoice_date"])
        await date.fill(inputs["invoice_date"])
        await page.keyboard.press("Tab")
        before_due = await (await resolver.resolve(page, T["due_date"])).input_value()
        await self._pick(page, await resolver.resolve(page, T["terms"]), inputs["terms"])
        await page.wait_for_timeout(500)
        due = await (await resolver.resolve(page, T["due_date"])).input_value()
        expected = due_date_for(inputs["invoice_date"], inputs["terms"])
        if expected and due != expected:
            raise RetryableError("dependent field mismatch: due date is %s, expected %s" % (due, expected))
        log.info("due date moved %s -> %s after terms were set", before_due, due)

        await self._pick(page, await resolver.resolve(page, T["item"]), inputs["item"])
        rate = await (await resolver.resolve(page, T["rate"])).input_value()
        if rate in ("", "0.00"):
            raise RetryableError("item rate did not fill")
        qty = await resolver.resolve(page, T["quantity"])
        await qty.fill(str(inputs["quantity"]))
        await page.keyboard.press("Tab")

        await (await resolver.resolve(page, T["save_draft"])).click()
        await page.wait_for_url(re.compile(r"#/invoices/\d+"), timeout=20000)  # page 4: the saved draft
        visit(page.url)
        await page.get_by_text("DRAFT").first.wait_for(timeout=15000)

        await (await resolver.resolve(page, T["pdf_menu"])).click()
        async with page.expect_download(timeout=30000) as dl:
            await (await resolver.resolve(page, T["pdf_item"])).click()
        download = await dl.value
        dest = os.path.join(out_dir, "invoice_%s.pdf" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        await download.save_as(dest)
        with open(dest, "rb") as fh:
            if fh.read(5) != b"%PDF-":
                raise RetryableError("download is not a PDF")
        return [dest]
