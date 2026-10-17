"""Terms pick. Model of the suspected Windows failure: the list is filtered by a debounce after typing and a click
before that filter lands does not select. This models the hypothesis; it is not the real Zoho page."""
import pytest
from portal_runner.errors import RetryableError
from portal_runner.portals.zoho import ZohoInvoice
from conftest import run


def page_html(commits_when_filtered=True, never=False):
    return ("<html><body><div id='box' tabindex=0 role='combobox' onclick=\"document.getElementById('s').style.display='block'\">Due on Receipt</div>"
            "<div id='s' style='display:none'><input id='q' aria-label='Search'><ul id='lb' role='listbox'>"
            "<li role='option'>Net 15</li><li role='option'>Net 30</li><li role='option'>Net 45</li></ul></div>"
            "<script>var filtered=false;var t;"
            "document.getElementById('q').addEventListener('input',function(){filtered=false;clearTimeout(t);t=setTimeout(function(){"
            "document.getElementById('lb').innerHTML=\"<li role='option'>Net 30</li>\";filtered=true;bind()},450)});"
            "function bind(){document.querySelectorAll('[role=option]').forEach(function(li){li.onclick=function(){"
            "if(%s && (filtered || !%s)){document.getElementById('box').textContent=li.textContent}}})}bind();"
            "document.getElementById('box').addEventListener('click',function(){setTimeout(function(){document.getElementById('q').focus()},0)});"
            "</script></body></html>" % ("false" if never else "true", "true" if commits_when_filtered else "false"))


def _pick(browser_ctx, html):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(html)
            await ZohoInvoice("1")._pick(page, page.locator("#box"), "Net 30", verify=True)
            return await page.locator("#box").inner_text()
    return run(go())


def test_pick_waits_for_the_filtered_list_before_clicking(browser_ctx):
    assert _pick(browser_ctx, page_html()) == "Net 30"


def test_uncommitted_pick_fails_with_what_the_field_shows(browser_ctx):
    with pytest.raises(RetryableError) as e:
        _pick(browser_ctx, page_html(never=True))
    assert "Due on Receipt" in str(e.value)
