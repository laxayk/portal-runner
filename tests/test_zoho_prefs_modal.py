"""First-run 'Set your transaction preferences' modal must be cleared without changing options."""
from portal_runner.portals.zoho import ZohoInvoice
from conftest import run

BASE = ("<html><body><input id='cust'><div id='m' role='dialog' style='position:fixed;inset:0;background:#fff'>"
        "<h3>Set your transaction preferences</h3><label><input type='checkbox' id='c1'> I don't give discounts</label>"
        "%s<button type='button' onclick=\"document.getElementById('m').remove()\">Save &amp; Continue</button></div></body></html>")


def check(html):
    async def go(browser_ctx):
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(html)
            r = await ZohoInvoice("1")._clear_preferences_modal(page, wait=2)
            return r, await page.locator("#m").count()
    return go


def test_close_control(browser_ctx):
    h = BASE % "<button type='button' class='close' aria-label='Close' onclick=\"document.getElementById('m').remove()\">x</button>"
    assert run(check(h)(browser_ctx)) == (True, 0)


def test_fallback_save_and_continue_without_touching_boxes(browser_ctx):
    assert run(check(BASE % "")(browser_ctx)) == (True, 0)


def test_no_modal_is_noop(browser_ctx):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content("<html><body>form</body></html>")
            return await ZohoInvoice("1")._clear_preferences_modal(page, wait=1)
    assert run(go()) is False
