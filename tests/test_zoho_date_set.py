"""A date picker that resets the first fill must not silently leave the wrong invoice date."""
import pytest
from portal_runner.errors import RetryableError
from portal_runner.portals.zoho import ZohoInvoice
from conftest import run

RESET_ONCE = ("<html><body><input id='d' value='17/10/2026'><input id='x'>"
              "<script>var n=0;document.getElementById('d').addEventListener('change',function(e){ if(n++===0){ setTimeout(function(){e.target.value='17/10/2026'},50);} });</script></body></html>")
ALWAYS_RESET = ("<html><body><input id='d' value='17/10/2026'><input id='x'>"
                "<script>var d=document.getElementById('d');d.addEventListener('change',function(){ setTimeout(function(){d.value='17/10/2026'},50);});</script></body></html>")


def go(html):
    async def f(browser_ctx):
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(html)
            await ZohoInvoice("1")._set_date(page, page.locator("#d"), "15/10/2026")
            return await page.locator("#d").input_value()
    return f


def test_reset_once_is_retried(browser_ctx):
    assert run(go(RESET_ONCE)(browser_ctx)) == "15/10/2026"


def test_persistent_reset_fails_with_actual_value(browser_ctx):
    with pytest.raises(RetryableError) as e:
        run(go(ALWAYS_RESET)(browser_ctx))
    assert "17/10/2026" in str(e.value)
