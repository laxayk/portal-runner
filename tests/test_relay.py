from portal_runner.codes import Challenge, RelayProvider
from portal_runner.errors import WrongCodeError
from conftest import run
import pytest


def test_relay_reads_and_deletes_file(tmp_path):
    p = tmp_path / "code.txt"
    p.write_text("123456\n")
    code = run(RelayProvider(path=str(p)).get_code(Challenge(portal="x")))
    assert code == "123456" and not p.exists()


def test_relay_times_out(tmp_path):
    async def nosleep(_):
        return None
    with pytest.raises(WrongCodeError):
        run(RelayProvider(path=str(tmp_path / "none"), timeout=2, poll=1, sleep=nosleep).get_code(Challenge(portal="x")))


def test_totp_accepts_spaced_lowercase_and_uri():
    import pyotp
    from portal_runner.codes import TotpProvider
    base = pyotp.random_base32()
    spaced = " ".join(base[i:i + 4] for i in range(0, len(base), 4)).lower()
    uri = pyotp.TOTP(base).provisioning_uri(name="a@example.com", issuer_name="X")
    fixed = 1_700_000_010.0
    want = pyotp.TOTP(base).at(fixed)
    for form in (base, spaced, uri):
        p = TotpProvider(form, clock=lambda: fixed)
        assert run(p.get_code(Challenge(portal="x"))) == want
