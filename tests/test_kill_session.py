import json
import subprocess
import sys


def _run(*args, cwd):
    return subprocess.run([sys.executable, "-m", "portal_runner", *args], cwd=cwd, capture_output=True, text=True,
                          env={**__import__("os").environ, "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1])})


def test_kill_session_keeps_backup_and_hides_values(tmp_path):
    st = tmp_path / "s.json"
    st.write_text(json.dumps({"cookies": [{"name": "a", "value": "SECRET1"}, {"name": "b", "value": "SECRET2"}], "origins": []}))
    r = _run("kill-session", "--state", str(st), cwd=tmp_path)
    assert r.returncode == 0 and "SECRET" not in r.stdout + r.stderr and "2 cookie values" in r.stdout
    data = json.loads(st.read_text())
    assert [c["value"] for c in data["cookies"]] == ["dead", "dead"]
    baks = list(tmp_path.glob("s.json.valid-*.bak"))
    assert len(baks) == 1 and "SECRET1" in baks[0].read_text()


def test_kill_session_without_state_fails(tmp_path):
    assert _run("kill-session", "--state", str(tmp_path / "none.json"), cwd=tmp_path).returncode == 1


def test_last_run_reports_login_mode(tmp_path):
    (tmp_path / "manifest-20261018_000001.json").write_text(json.dumps({"status": "success", "login_mode": "full_login", "navigation": {"new_form": "x"}}))
    r = _run("last-run", "--out", str(tmp_path), cwd=tmp_path)
    assert "login_mode=full_login" in r.stdout


def test_load_env_handles_bom_and_quotes(tmp_path, monkeypatch):
    from portal_runner.__main__ import load_env
    p = tmp_path / ".env"
    p.write_bytes('\ufeffTEST_A="x y"\nTEST_B=plain\nTEST_C=\'q\'\n'.encode("utf-8"))
    for k in ("TEST_A", "TEST_B", "TEST_C"):
        monkeypatch.delenv(k, raising=False)
    load_env(str(p))
    import os
    assert (os.environ["TEST_A"], os.environ["TEST_B"], os.environ["TEST_C"]) == ("x y", "plain", "q")
    for k in ("TEST_A", "TEST_B", "TEST_C"):
        os.environ.pop(k, None)
