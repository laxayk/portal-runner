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
