"""A terms option that is only highlighted by the click must still end up selected (Windows run, Oct 17)."""
import pytest
from portal_runner.errors import RetryableError
from portal_runner.portals.zoho import ZohoInvoice
from conftest import run

def page_html(enter_commits):
    return ("<html><body><div id='box' tabindex=0 role='combobox' onclick=\"document.getElementById('lb').style.display='block'\">Due on Receipt</div>"
            "<ul id='lb' role='listbox' style='display:none'><li role='option' style='background:#cde'>Net 30</li></ul>"
            "<script>document.addEventListener('keydown',function(e){if(e.key==='Enter' && %s){document.getElementById('box').textContent='Net 30'}})</script>"
            "</body></html>" % ("true" if enter_commits else "false"))

def _pick(browser_ctx, html):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(html)
            await ZohoInvoice("1")._pick(page, page.locator("#box"), "Net 30", verify=True)
            return await page.locator("#box").inner_text()
    return run(go())

def test_enter_commits_when_click_only_highlights(browser_ctx):
    assert _pick(browser_ctx, page_html(True)) == "Net 30"

def test_uncommitted_pick_fails_with_what_the_field_shows(browser_ctx):
    with pytest.raises(RetryableError) as e:
        _pick(browser_ctx, page_html(False))
    assert "Due on Receipt" in str(e.value)
