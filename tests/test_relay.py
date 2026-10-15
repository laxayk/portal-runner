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
