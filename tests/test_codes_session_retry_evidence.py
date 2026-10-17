import json
import logging
import os

import pyotp
import pytest

from portal_runner.codes import Challenge, TotpProvider, SecretStr
from portal_runner.errors import FinalError, RetryableError, StageFailed, WrongCodeError
from portal_runner.evidence import write_bundle
from portal_runner.manifest import Manifest
from portal_runner.redact import Redactor, install
from portal_runner.resolver import Resolver
from portal_runner.retry import run_stage
from portal_runner.runner import second_factor
from portal_runner.session import StateStore
from conftest import run

SECRET = pyotp.random_base32()


class FakeClock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


def test_totp_matches_and_waits_near_window_end():
    c = FakeClock(1_700_000_000 - (1_700_000_000 % 30) + 28)  # 2s left in window
    p = TotpProvider(SECRET, clock=c, sleep=c.sleep)
    code = run(p.get_code(Challenge("t")))
    assert code == pyotp.TOTP(SECRET).at(c.t)  # code of the NEXT window after waiting
    assert c.t % 30 < 5


def test_never_returns_same_code_twice():
    c = FakeClock(1_700_000_000 - (1_700_000_000 % 30) + 2)
    p = TotpProvider(SECRET, clock=c, sleep=c.sleep)
    a = run(p.get_code(Challenge("t", attempt=0)))
    b = run(p.get_code(Challenge("t", attempt=1)))
    assert a != b


def test_wrong_code_retried_once_then_final():
    sent = []

    async def get_code(ch):
        return "000%d" % ch.attempt

    async def submit(code):
        sent.append(code)

    async def rejected():
        return True
    with pytest.raises(WrongCodeError):
        run(second_factor("t", get_code, submit, rejected))
    assert len(sent) == 2


def test_wrong_code_then_right_passes():
    state = {"n": 0}

    async def get_code(ch):
        return "1"

    async def submit(code):
        state["n"] += 1

    async def rejected():
        return state["n"] < 2
    run(second_factor("t", get_code, submit, rejected))
    assert state["n"] == 2


def test_secret_wrapper_and_log_filter(caplog):
    s = SecretStr("hunter2-secret")
    assert "hunter2" not in repr(s) and "hunter2" not in str(s)
    red = Redactor(["hunter2-secret"])
    log = install(red)
    log.propagate = True
    with caplog.at_level(logging.INFO, logger="portal_runner"):
        log.info("password hunter2-secret code 123456 for me@example.com")
    assert "hunter2" not in caplog.text and "123456" not in caplog.text and "me@example.com" not in caplog.text


def test_state_store_detects_corruption(tmp_path):
    p = tmp_path / "s.json"
    st = StateStore(str(p))
    assert st.load() is None
    p.write_text("{not json")
    assert st.load() is None
    p.write_text('{"cookies": "x"}')
    assert st.load() is None
    p.write_text('{"cookies": [], "origins": []}')
    assert st.load() is not None


def test_retry_bounds_and_final_not_retried():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        raise RetryableError("net")

    async def nosleep(s):
        pass
    with pytest.raises(StageFailed) as e:
        run(run_stage("s", flaky, max_attempts=3, sleep=nosleep))
    assert calls["n"] == 3 and len(e.value.attempts) == 3

    calls["n"] = 0

    async def final():
        calls["n"] += 1
        raise FinalError("locked")
    with pytest.raises(StageFailed):
        run(run_stage("s", final, max_attempts=3, sleep=nosleep))
    assert calls["n"] == 1


def test_evidence_bundle_has_required_files_and_no_secrets(browser_ctx, tmp_path):
    canary_pw, canary_mail, canary_code = "Pa55-CANARY-w0rd", "canary.user@example.org", "834512"
    red = Redactor([canary_pw, canary_mail])

    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.goto("data:text/html,<title>x</title>")
            await page.set_content('<html><body><p>Hello %s</p><input value="%s"><p>code %s</p></body></html>' % (canary_mail, canary_pw, canary_code))
            return await write_bundle(str(tmp_path), page, "login", RuntimeError("boom %s" % canary_pw), Resolver(),
                                      ["log: user %s" % canary_mail], red)
    path, written = run(go())
    for need in ("page.html", "url.txt", "console.log", "stage.txt", "resolver_attempts.json", "screenshot.png"):
        assert need in written, need
    blob = b""
    for f in os.listdir(path):
        if f.endswith(".png"):
            continue
        blob += open(os.path.join(path, f), "rb").read()
    for c in (canary_pw, canary_mail, canary_code):
        assert c.encode() not in blob, c


def test_manifest_shape(tmp_path):
    red = Redactor(["s3cret-value"])
    m = Manifest("demo", {"kind": "posts"}, red)
    m.visit("https://x.example/a?token=abc#f")
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    m.capture(str(f))
    m.write(str(tmp_path / "manifest.json"))
    d = json.load(open(tmp_path / "manifest.json"))
    assert d["pages_visited"] == ["https://x.example/a"]
    assert d["captured_files"][0]["bytes"] == 5 and len(d["captured_files"][0]["sha256"]) == 64


def test_screenshot_pixels_hide_text_identity(browser_ctx, tmp_path):
    """OCR the screenshot: a control without masking shows the canaries, the bundle screenshot does not."""
    import shutil
    import subprocess
    import pytest
    if not shutil.which("tesseract"):
        pytest.skip("tesseract not installed")
    from portal_runner.evidence import mask_page_text
    from portal_runner.redact import Redactor
    html = ("<body style='font:42px sans-serif'><p>Account kaylacanary@example.com</p><p>Phone 91-8586017706</p>"
            "<p>Org Zebra Canary Traders</p><p>Invoice INV-000001</p></body>")

    def ocr(png):
        return subprocess.run(["tesseract", str(png), "-", "--psm", "6"], capture_output=True, text=True).stdout

    async def go():
        async with browser_ctx() as b:
            page = await b.new_page(viewport={"width": 1100, "height": 400})
            await page.set_content(html)
            await page.screenshot(path=str(tmp_path / "raw.png"))
            await mask_page_text(page, Redactor(["Zebra Canary Traders"]))
            await page.screenshot(path=str(tmp_path / "masked.png"))
    run(go())
    raw, masked = ocr(tmp_path / "raw.png").lower(), ocr(tmp_path / "masked.png").lower()
    assert "canary" in raw and "8586" in raw  # OCR works on the control
    assert "canary" not in masked and "8586" not in masked and "example.com" not in masked
    assert "inv-000001" in masked.replace(" ", "") or "invoice" in masked


def test_redactor_masks_phone_and_listed_ids():
    from portal_runner.redact import Redactor
    r = Redactor(["kaylakshay", "60092053190"])
    out = r.text('"phone":"91-8586017706","user_name":"kaylakshay","organization_id":"60092053190"')
    for bad in ("8586017706", "kaylakshay", "60092053190"):
        assert bad not in out


def test_child_logger_messages_are_redacted(capsys):
    import logging
    from portal_runner.redact import Redactor, install
    install(Redactor(["hunter2pass"]))
    logging.getLogger("portal_runner.zoho").warning("login hunter2pass code 123456 to a@b.co")
    err = capsys.readouterr().err
    assert "hunter2pass" not in err and "123456" not in err and "a@b.co" not in err


def test_url_keeps_spa_route_but_not_ids_or_tokens():
    from portal_runner.redact import Redactor
    r = Redactor(["60092053190"])
    assert r.url("https://invoice.zoho.in/app/60092053190#/invoices/4299035000000040001?x=1") == "https://invoice.zoho.in/app/[REDACTED]#/invoices/[REDACTED]"
    assert r.url("https://x.example/cb?code=abc#access_token=secret") == "https://x.example/cb"
    assert r.url("https://invoice.zoho.in/app/60092053190#/invoices/new") != r.url("https://invoice.zoho.in/app/60092053190#/invoices")
