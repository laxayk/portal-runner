"""_pick must click the dropdown option, not other text that contains the same name (live: customer details tab)."""
from portal_runner.portals.zoho import ZohoInvoice
from conftest import run

HTML = ("<html><body><div id='box' tabindex=0 role='combobox' onclick=\"document.getElementById('lb').style.display='block'\">Select</div>"
        "<ul id='lb' role='listbox' style='display:none'><li role='option' onclick=\"window.picked='option'\">Acme Test Traders</li></ul>"
        "<button onclick=\"window.picked='details tab'\">Acme Test Traders's Details</button>"
        "<p onclick=\"window.picked='panel'\">Acme Test Traders</p></body></html>")


def test_pick_clicks_the_option_not_look_alike_text(browser_ctx):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(HTML)
            await ZohoInvoice("1")._pick(page, page.locator("#box"), "Acme Test Traders")
            return await page.evaluate("window.picked")
    assert run(go()) == "option"
