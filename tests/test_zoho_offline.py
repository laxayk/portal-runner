"""Zoho targets resolve on a saved copy of the real new-invoice page (captured from the live portal), including mutations."""
from portal_runner.mutate import all_mutations
from portal_runner.portals.zoho import T, due_date_for
from portal_runner.resolver import Resolver
from conftest import FIX, run

KEYS = ["customer", "invoice_date", "terms", "due_date", "item", "quantity", "rate", "save_draft"]


def test_real_page_all_mutations(browser_ctx):
    html = (FIX / "zoho_invoice_form.html").read_text(encoding="utf-8")

    async def go():
        wins = {}
        async with browser_ctx() as b:
            for name, doc in all_mutations(html).items():
                page = await b.new_page()
                await page.set_content(doc)
                r = Resolver()
                for k in KEYS:
                    await r.resolve(page, T[k])
                wins[name] = dict(r.wins)
                await page.close()
        return wins
    wins = run(go())
    assert len(wins) >= 6
    used = {s for w in wins.values() for s in w.values()}
    assert "role_name" in used and ({"structure", "nearby_text"} & used)


def test_due_date_cross_check():
    assert due_date_for("15/10/2026", "Net 30") == "14/11/2026"
    assert due_date_for("15/10/2026", "Due on Receipt") == "15/10/2026"
    assert due_date_for("15/10/2026", "Due end of the month") is None


def test_nav_and_pdf_menu_on_real_pages(browser_ctx):
    async def go():
        out = {}
        async with browser_ctx() as b:
            for f, keys in (("zoho_invoice_list", ["nav_invoices"]), ("zoho_invoice_detail", ["pdf_menu"])):
                page = await b.new_page()
                await page.set_content((FIX / (f + ".html")).read_text(encoding="utf-8"))
                r = Resolver()
                for k in keys:
                    await r.resolve(page, T[k])
                out[f] = dict(r.wins)
                await page.close()
        return out
    out = run(go())
    assert "nav_invoices" in out["zoho_invoice_list"] and "pdf_menu" in out["zoho_invoice_detail"]
