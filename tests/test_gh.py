"""Unit tests for runner/gh.py — the gh CLI subprocess wrapper."""

import subprocess

from gh import check_gh_auth


class TestCheckGhAuth:
    """check_gh_auth is the session-start pre-flight that replaced the legacy
    GITHUB_PERSONAL_ACCESS_TOKEN env-var check (see issue #112). It must
    return a clean True/False signal so main() can fail fast with an
    actionable message instead of letting the first gh subcall blow up."""

    def test_returns_success_when_gh_auth_status_exits_zero(self, monkeypatch):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args[0], 0, stdout="", stderr="Logged in to github.com account why-pengo"
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        ok, msg = check_gh_auth()
        assert ok is True
        assert msg == ""

    def test_returns_failure_with_captured_stderr_on_nonzero_exit(self, monkeypatch):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args[0], 1, stdout="", stderr="You are not logged into any GitHub hosts."
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        ok, msg = check_gh_auth()
        assert ok is False
        assert "not logged" in msg

    def test_returns_failure_when_gh_binary_missing(self, monkeypatch):
        def boom(*args, **kwargs):
            raise FileNotFoundError("gh")

        monkeypatch.setattr(subprocess, "run", boom)
        ok, msg = check_gh_auth()
        assert ok is False
        assert "not found" in msg.lower()

    def test_returns_failure_on_timeout(self, monkeypatch):
        def boom(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 30))

        monkeypatch.setattr(subprocess, "run", boom)
        ok, msg = check_gh_auth(timeout=5)
        assert ok is False
        assert "timed out" in msg
        assert "5s" in msg
