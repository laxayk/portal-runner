"""The sidebar wrapper can cover the Invoices link and swallow real clicks (seen live, Oct 17)."""
from portal_runner.portals.zoho import T
from portal_runner.resolver import Resolver
from conftest import run

HTML = ("<html><body><nav><a href='#/invoices' onclick=\"window.__hit=1\">Invoices</a></nav>"
        "<div class='main-nav-lhs' style='position:fixed;top:0;left:0;width:400px;height:400px'></div></body></html>")


def test_covered_link_is_clicked_through_dom(browser_ctx):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(HTML)
            nav = await Resolver().resolve(page, T["nav_invoices"])
            try:
                await nav.click(timeout=1500)
                real = True
            except Exception:  # noqa: BLE001
                real = False
            await nav.dispatch_event("click")
            return real, await page.evaluate("window.__hit || 0")
    real, hit = run(go())
    assert real is False  # the overlay really blocks a normal click
    assert hit == 1       # and the DOM click still reaches the link


def test_new_click_records_route(browser_ctx, tmp_path):
    from portal_runner.portals.zoho import ZohoInvoice
    f = tmp_path / "l.html"
    f.write_text("<html><body><button class='btn-primary' onclick=\"location.hash='#/invoices/new'\">New</button></body></html>")
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.goto(f.as_uri())
            p = ZohoInvoice("1")
            await p._open_new_form(page, Resolver())
            return page.url, p.nav_notes
    url, notes = run(go())
    assert url.endswith("#/invoices/new") and notes["new_form"].startswith("clicked")


def test_new_click_dead_falls_back_to_address(browser_ctx, tmp_path, monkeypatch):
    import portal_runner.portals.zoho as z
    f = tmp_path / "l.html"
    f.write_text("<html><body><button class='btn-primary'>New</button></body></html>")
    monkeypatch.setattr(z, "APP", f.as_uri() + "?o=%s")
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.goto(f.as_uri())
            p = z.ZohoInvoice("1")
            async def quick(page, part, timeout):
                return part in page.url
            p._url_has = quick
            await p._open_new_form(page, Resolver())
            return page.url, p.nav_notes
    url, notes = run(go())
    assert url.endswith("#/invoices/new") and "by address" in notes["new_form"]
