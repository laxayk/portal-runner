"""Post-submit login transitions on synthetic pages.

The runner must judge a code only by positive evidence:
- accepted: the app, accounts home, or the "Trust this browser" prompt (shown only after a good code)
- rejected: the challenge still up AND an explicit invalid/expired code error
- anything else (loading, mid-navigation, error page, boxes filled or cleared): unknown - never
  typed over, never re-submitted into; the login stage retries fresh instead.
"""
import pytest

from portal_runner.errors import RetryableError
from portal_runner.portals.zoho import ZohoInvoice
from portal_runner.resolver import Resolver
from conftest import run

TRUST_INNER = "<div id='trustbox'><h2>Trust this browser?</h2>" \
              "<p>We won't ask you to verify your account with Two-Factor Authentication on this browser for the next 180 days.</p>" \
              "<button id='trustbtn'>Trust</button>" \
              "<button id='notnowbtn' onclick=\"window.__dismissed='notnow';document.getElementById('trustbox').remove()\">Not now</button></div>"

TRUST_HTML = "<html><body>%s</body></html>" % TRUST_INNER


def challenge_html(script=""):
    boxes = "".join('<input type="tel" maxlength="1" id="d%d">' % i for i in range(6))
    return ("<html><body><form id='tfa'><p>Enter time-based OTP</p>%s"
            "<button type='button' id='totpverifybtn' onclick=\"window.__clicks=(window.__clicks||0)+1\">Verify</button>"
            "</form><script>%s</script></body></html>") % (boxes, script)


def portal():
    p = ZohoInvoice("123456")
    p.verdict_timeout = 4.0  # keep tests fast; the live default is 30s
    return p


def test_slow_acceptance_is_not_misread_as_rejected(browser_ctx):
    """The actual bug: Zoho took longer than the old 9s URL wait, a good code read as rejected,
    and the retry typed over a page that had already moved on. Acceptance at 12s must win."""
    script = "setTimeout(function(){ document.body.innerHTML = '%s'; }, 12000);" % TRUST_INNER.replace("'", "\\'")

    async def go():
        p = ZohoInvoice("123456")  # live 30s verdict window, like production
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(challenge_html(script))
            return await p._await_verdict(page)
    assert run(go()) == "accepted"


def test_explicit_error_is_rejected(browser_ctx):
    script = ("setTimeout(function(){ var d=document.createElement('div');"
              " d.textContent='The code you entered is incorrect'; document.body.appendChild(d); }, 1000);")

    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(challenge_html(script))
            return await p._await_verdict(page)
    assert run(go()) == "rejected"


def test_boxes_gone_is_unknown_not_accepted(browser_ctx):
    """Loading or mid-navigation removes the boxes; that alone must never read as success."""
    script = "setTimeout(function(){ document.querySelectorAll('input').forEach(function(i){ i.remove(); }); }, 500);"

    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(challenge_html(script))
            await p._await_verdict(page)
    with pytest.raises(RetryableError):
        run(go())


def test_error_page_after_navigation_is_unknown(browser_ctx):
    """An error page (even with scary words) is not an OTP verdict without the challenge up."""
    script = "setTimeout(function(){ document.body.innerHTML='<h1>Something went wrong</h1>'; }, 500);"

    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(challenge_html(script))
            await p._await_verdict(page)
    with pytest.raises(RetryableError):
        run(go())


def test_cleared_boxes_without_error_are_unknown_not_rejected(browser_ctx):
    """Sites clear or re-render inputs for their own reasons; only an explicit error rejects."""
    script = "setTimeout(function(){ document.querySelectorAll('input').forEach(function(i){ i.value=''; }); }, 500);"

    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(challenge_html(script))
            await p._await_verdict(page)
    with pytest.raises(RetryableError):
        run(go())


def test_no_blind_verify_reclick_on_unknown(browser_ctx):
    """A submit with no verdict: verify is clicked exactly once (the submit itself), never re-clicked."""

    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(challenge_html())

            async def get_code(ch):
                return "123456"
            with pytest.raises(RetryableError):
                await p._otp(page, Resolver(), get_code)
            return await page.evaluate("window.__clicks || 0")
    assert run(go()) == 1


def test_second_code_never_typed_when_already_accepted(browser_ctx):
    """If the page already shows post-auth evidence, a retry must not type another code."""

    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(TRUST_HTML)
            codes = []

            async def get_code(ch):
                codes.append(ch.attempt)
                return "123456"
            await p._otp(page, Resolver(), get_code)
            return codes
    assert run(go()) == [0]  # one submit attempt, skipped by the guard, verdict accepted


def test_submit_refuses_a_page_without_the_challenge(browser_ctx):
    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content("<html><body><h1>Please wait</h1></body></html>")

            async def get_code(ch):
                return "123456"
            await p._otp(page, Resolver(), get_code)
    with pytest.raises(RetryableError):
        run(go())


def test_trust_prompt_declined_with_not_now(browser_ctx):
    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(TRUST_HTML)
            with pytest.raises(RetryableError):  # offline page never reaches the app
                await p._wait_for_app(page, timeout=2.0)
            return await page.evaluate("window.__dismissed || ''")
    assert run(go()) == "notnow"


def test_late_rendering_challenge_is_waited_for(browser_ctx):
    script = ("setTimeout(function(){ var f=document.getElementById('tfa');"
              " for (var i=0;i<6;i++){ var b=document.createElement('input'); b.type='tel'; f.appendChild(b); } }, 1500);")

    async def go():
        p = portal()
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content(challenge_html(script).replace('<input type="tel" maxlength="1" id="d0">', '')
                                     .replace(''.join('<input type="tel" maxlength="1" id="d%d">' % i for i in range(1, 6)), ''))
            return await p._challenge_shown(page)
    assert run(go()) is True
