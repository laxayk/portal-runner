"""Zoho Invoice (India data center) adapter.

Flow: sign in (email, password, then a 6 digit authenticator code) -> Invoices -> New invoice ->
fill customer, date, payment terms (sets the due date), item (sets the rate), quantity -> Save as Draft
-> PDF/Print -> PDF (a real download). Drafts only. Nothing is ever sent to a customer.
"""
import asyncio
import logging
import os
import re
import time
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
    # Zoho appends an empty second row once an item is picked: two Quantity/Rate boxes are on screen, ours is the first.
    "quantity": Target("quantity", role="textbox", name="Quantity", structure="input[data-integrity$='quantity']", group=True),
    "rate": Target("rate", role="textbox", name="Rate", structure="input[data-integrity$='rate']", group=True),
    "save_draft": Target("save_draft", role="button", name="Save as Draft", tag="button", structure="button:has-text('Save as Draft')"),
    "pdf_menu": Target("pdf_menu", role="button", name="PDF/Print", tag="button", structure="button:has-text('PDF/Print')"),
    "pdf_item": Target("pdf_item", role="button", name="PDF", exact=True, tag="button", structure="[role=listbox] button:text-is('PDF')"),
}

DIGITS = re.compile(r"^\d{6}$")
PREFS_MODAL = re.compile(r"set your transaction preferences", re.I)
TRUST_PROMPT = re.compile(r"trust this browser", re.I)
OTP_ERROR = re.compile(r"invalid|incorrect|wrong|expired|didn'?t match|does not match", re.I)


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
        self.verdict_timeout = 30.0  # seconds to wait for a positive verdict after a code submit

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
        if await self._challenge_shown(page):
            await self._otp(page, resolver, get_code)
        await self._wait_for_app(page)
        if not await self.is_logged_in(page, resolver):
            raise FinalError("signed in but the app did not load")

    # ---- post-submit state ---------------------------------------------------------------------
    # After the password, and again after each code, the page is in exactly one of a few states.
    # A verdict comes only from positive evidence on the page, never from how long a redirect
    # takes: a slow redirect is not a wrong code, and a transition is not an acceptance.
    async def _challenge_shown(self, page, timeout=15.0):
        """True if the second-factor challenge is up. It can render late, like the login box."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "invoice.zoho.in" in page.url:
                return False
            if await page.locator("input[type=tel]").locator("visible=true").count():
                return True
            await page.wait_for_timeout(500)
        return False

    async def _trust_prompt_shown(self, page):
        try:
            return await page.get_by_text(TRUST_PROMPT).locator("visible=true").count() > 0
        except Exception:  # noqa: BLE001
            return False

    async def _otp_error_shown(self, page):
        try:
            return await page.get_by_text(OTP_ERROR).locator("visible=true").count() > 0
        except Exception:  # noqa: BLE001
            return False

    async def _otp_state(self, page):
        """Classify the page after a code submit.

        accepted - positive post-auth evidence only: the app itself, the accounts home, or the
                   "Trust this browser" prompt (only shown after a code was accepted)
        rejected - explicit proof only: the challenge is still up AND shows an invalid/expired
                   code error. Cleared boxes alone prove nothing (sites re-render them).
        unknown  - anything else: mid-navigation, loading, an error page, boxes filled or
                   cleared with no verdict. Never typed over and never re-submitted into.
        """
        if "invoice.zoho.in" in page.url or re.search(r"accounts\.zoho\.in/home", page.url):
            return "accepted"
        if await self._trust_prompt_shown(page):
            return "accepted"
        if not await page.locator("input[type=tel]").count():
            return "unknown"  # no challenge on screen: transition, loading or an error page
        if await self._otp_error_shown(page):
            return "rejected"
        return "unknown"

    async def _click_verify(self, page):
        btn = page.locator("#totpverifybtn, #nextbtn, button:has-text('Verify')").locator("visible=true")
        if await btn.count():
            await btn.first.click()
            return True
        log.warning("no verify button found on the second factor page")
        return False

    async def _await_verdict(self, page, verdict_timeout=None):
        """Poll until the portal positively accepts or explicitly rejects the code.

        An unknown state is never resolved by typing another code or clicking verify again:
        the first submit may still be processing, and a duplicate can confuse the portal.
        If no verdict arrives in time the whole login stage is retried fresh instead.
        """
        timeout = self.verdict_timeout if verdict_timeout is None else verdict_timeout
        deadline = time.monotonic() + timeout
        while True:
            state = await self._otp_state(page)
            if state == "accepted":
                return "accepted"
            if state == "rejected":
                log.warning("portal reported the code wrong (error shown on the challenge)")
                return "rejected"
            if time.monotonic() > deadline:
                raise RetryableError("no verdict after the code submit; the page state stayed unknown")
            await page.wait_for_timeout(500)

    async def _dismiss_trust_prompt(self, page):
        """Decline the 180 day trust offer: the run relies on its own saved session only."""
        try:
            await page.get_by_role("button", name=re.compile(r"not now", re.I)).first.click(timeout=1500)
            log.info("trust-browser prompt declined (Not now)")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _wait_for_app(self, page, timeout=45.0):
        """Reach a signed-in destination after credentials, declining the trust prompt if shown."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "invoice.zoho.in" in page.url or re.search(r"accounts\.zoho\.in/home", page.url):
                return
            if await self._trust_prompt_shown(page):
                await self._dismiss_trust_prompt(page)
            await page.wait_for_timeout(500)
        raise RetryableError("signed in but never reached the app")

    async def _otp(self, page, resolver, get_code):
        async def submit(code):
            if not DIGITS.match(code):
                raise FinalError("code is not 6 digits")
            if await self._otp_state(page) == "accepted":
                log.info("second factor already accepted; not typing another code")
                return
            boxes = page.locator("input[type=tel]")
            n = await boxes.count()
            if not n:
                raise RetryableError("second factor challenge not on screen; not typing into an unknown page")
            await boxes.nth(n - 1).click()  # clear leftover digits (retry after an explicit error)
            for _ in range(n):
                await page.keyboard.press("Backspace")
            first = await resolver.resolve(page, T["otp_box"])
            await first.click()
            await page.keyboard.type(code, delay=60)  # six separate boxes advance on each key
            await self._click_verify(page)

        async def rejected():
            return (await self._await_verdict(page)) == "rejected"

        await second_factor(self.name, get_code, submit, rejected)

    async def _clear_preferences_modal(self, page, wait=4.0):
        """First visit to the new-invoice form shows "Set your transaction preferences" over the
        form. It swallows every click. Close it without touching any option. It never clicks
        Save & Continue: that would persist account settings the user has not chosen."""
        deadline = time.monotonic() + wait
        shown = False
        while time.monotonic() < deadline:
            if await page.get_by_text(PREFS_MODAL).locator("visible=true").count():
                shown = True
                break
            await page.wait_for_timeout(300)
        if not shown:
            return False
        box = page.locator("[role=dialog], .modal, .modal-dialog, .zf-modal").filter(has_text=PREFS_MODAL).locator("visible=true").last
        for how in ("close",):
            try:
                if how == "close":
                    btn = box.locator("[aria-label*=close i], [title*=close i], button.close, .close, .modal-close, .close-icon").locator("visible=true").first
                else:
                    btn = page.get_by_role("button", name=re.compile(r"save\s*&\s*continue", re.I)).locator("visible=true").first
                await btn.click(timeout=2500)
            except Exception:  # noqa: BLE001
                continue
            await page.wait_for_timeout(800)
            if not await page.get_by_text(PREFS_MODAL).locator("visible=true").count():
                log.info("transaction preferences prompt cleared via %s, no option changed", how)
                return True
        raise FinalError("transaction preferences prompt has no working close control; saving it would change account settings, which needs the user's decision")

    async def _url_has(self, page, part, timeout):
        """Poll the address. Unlike wait_for_url this never waits for a page load event, which a
        single page app route change may not fire."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if part in page.url:
                return True
            await page.wait_for_timeout(300)
        return part in page.url

    # ---- work ----------------------------------------------------------------------------------
    async def _set_date(self, page, box, value, tries=3):
        """Fill a Zoho date picker and confirm it kept the value. The picker can reset a filled
        value to today, so the field is read back; the picker popup is closed with Escape."""
        for attempt in range(tries):
            if attempt == 0:
                await box.fill(value)
            else:
                await box.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.type(value, delay=50)
            await page.keyboard.press("Tab")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(700)  # let the picker settle: a reset can land after the blur
            if await box.input_value() == value:
                await page.wait_for_timeout(300)
                if await box.input_value() == value:
                    log.info("invoice date set to %s", value)
                    return
        raise RetryableError("invoice date field did not keep %r (shows %r)" % (value, await box.input_value()))

    async def _wait_due(self, page, resolver, expected, timeout=8.0):
        """Wait for the due date to follow the terms. Returns the last value seen."""
        deadline = time.monotonic() + timeout
        while True:
            due = await (await resolver.resolve(page, T["due_date"])).input_value()
            if not expected or due == expected or time.monotonic() > deadline:
                return due
            await page.wait_for_timeout(300)

    async def _close_customer_panel(self, page):
        """Zoho can open the customer details side panel over the form. Escape closes it; it is
        never needed for the run."""
        try:
            if await page.get_by_text("Outstanding Receivables").locator("visible=true").count():
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(400)
                log.info("closed the customer details panel")
        except Exception:  # noqa: BLE001
            pass

    async def _pick(self, page, box, text):
        """Zoho dropdowns are custom widgets, not <select>. Open, type to filter, click the option.

        The option is found as role=option (live DOM: customer, terms and item lists are all
        listbox > option). A loose get_by_text(...).last can land on other text that merely
        contains the name, such as the customer's details tab or panel, and open it instead."""
        await box.click()
        await page.keyboard.type(text, delay=40)
        opts = page.get_by_role("option").filter(has_text=text).locator("visible=true")
        try:
            await opts.first.wait_for(state="visible", timeout=8000)
            await opts.first.click()
        except Exception:  # noqa: BLE001
            opt = page.locator("[role=listbox]").get_by_text(text, exact=False).locator("visible=true").first
            await opt.wait_for(state="visible", timeout=4000)
            await opt.click()

    async def _capture_pdf(self, page, click, dest, timeout=30.0):
        """Click PDF and save the file. Live check (Oct 17): the click fires
        GET /api/v3/invoices/<id>?accept=pdf and answers 200 application/pdf, with no new tab.
        Normally the browser reports that as a download. If it is served inline and no download
        event comes, the response body itself is the PDF, so save that."""
        loop = asyncio.get_running_loop()
        got_download = loop.create_future()
        got_response = loop.create_future()

        def on_download(d):
            if not got_download.done():
                got_download.set_result(d)

        def on_response(r):
            ct = (r.headers.get("content-type") or "").lower()
            if r.status == 200 and ("accept=pdf" in r.url or "application/pdf" in ct) and not got_response.done():
                got_response.set_result(r)

        page.on("download", on_download)
        page.on("response", on_response)
        try:
            await click(timeout=10000)
            done, _ = await asyncio.wait({got_download, got_response}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise RetryableError("PDF click produced neither a download nor a PDF response")
            if got_download.done():
                await (await got_download).save_as(dest)
                return
            try:  # the response arrived first: give the download event a moment to follow
                d = await asyncio.wait_for(asyncio.shield(got_download), timeout=5.0)
                await d.save_as(dest)
                return
            except asyncio.TimeoutError:
                pass
            body = await (await got_response).body()
            with open(dest, "wb") as fh:
                fh.write(body)
            log.info("PDF came back inline, saved the response body (no download event)")
        finally:
            page.remove_listener("download", on_download)
            page.remove_listener("response", on_response)

    async def perform(self, page, resolver, inputs, out_dir, visit):
        os.makedirs(out_dir, exist_ok=True)
        await page.goto(self.home, wait_until="domcontentloaded")  # page 1
        nav = await resolver.resolve(page, T["nav_invoices"])  # page 2: list
        try:
            # Zoho's sidebar wrapper (div.main-nav-lhs) can sit over the link and swallow pointer
            # events, so a real click may never land. Try briefly, then click through the DOM.
            await nav.click(timeout=4000)
        except Exception as exc:  # noqa: BLE001
            log.info("real click on Invoices blocked (%s); clicking through the DOM", exc.__class__.__name__)
            try:
                await nav.dispatch_event("click")
            except Exception:  # noqa: BLE001
                pass
        if not await self._url_has(page, "#/invoices", 12.0):
            # The click registered nothing (single page app still wiring up its menu): go to the
            # list by its address instead. The hash route is the same page the menu opens.
            log.info("menu click did not reach the invoice list (url %s); opening the list directly", page.url.split("#")[0][-40:])
            await page.goto(APP % self.org_id + "#/invoices", wait_until="domcontentloaded")
            if not await self._url_has(page, "#/invoices", 15.0):
                raise RetryableError("invoice list did not open; url is %s" % page.url.split("?")[0])
        await page.goto(APP % self.org_id + "#/invoices/new", wait_until="domcontentloaded")  # page 3: form
        visit(page.url)
        await self._clear_preferences_modal(page)

        await self._pick(page, await resolver.resolve(page, T["customer"]), inputs["customer"])
        await self._close_customer_panel(page)
        await self._set_date(page, await resolver.resolve(page, T["invoice_date"]), inputs["invoice_date"])
        before_due = await (await resolver.resolve(page, T["due_date"])).input_value()
        await self._pick(page, await resolver.resolve(page, T["terms"]), inputs["terms"])
        expected = due_date_for(inputs["invoice_date"], inputs["terms"])
        due = await self._wait_due(page, resolver, expected)
        if expected and due != expected:
            seen = await (await resolver.resolve(page, T["invoice_date"])).input_value()
            raise RetryableError("dependent field mismatch: invoice date shows %r, due date is %r, expected %r" % (seen, due, expected))
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
        await page.get_by_text("DRAFT").locator("visible=true").first.wait_for(timeout=15000)  # ribbon reads "Draft"; match is case-insensitive

        await (await resolver.resolve(page, T["pdf_menu"])).click()
        pdf_item = await resolver.resolve(page, T["pdf_item"])
        dest = os.path.join(out_dir, "invoice_%s.pdf" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        await self._capture_pdf(page, pdf_item.click, dest)
        with open(dest, "rb") as fh:
            if fh.read(5) != b"%PDF-":
                raise RetryableError("download is not a PDF")
        return [dest]
