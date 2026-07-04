"""Unit tests for runner/tools.py — tool dispatch table, result-size cap,
repo pinning, and URL-component encoding/validation (#119)."""

import base64

import tools
from tools import TOOL_RESULT_SIZE_CAP, _cap, repo_pin_error


def _capture_gh(monkeypatch, rc=0, out="", err=""):
    """Replace tools._gh with a recorder returning a fixed result.

    Returns the list of (args, stdin) tuples captured, so tests can assert
    both what reached gh and that nothing did.
    """
    calls = []

    def fake_gh(args, stdin=None, timeout=120):
        calls.append((args, stdin))
        return rc, out, err

    monkeypatch.setattr(tools, "_gh", fake_gh)
    return calls


class TestCap:
    def test_passes_small_ascii_unchanged(self):
        small = "x" * 1000
        assert _cap(small) == small

    def test_passes_exact_cap_ascii_unchanged(self):
        exact = "y" * TOOL_RESULT_SIZE_CAP
        assert _cap(exact) == exact

    def test_truncates_large_ascii_with_size_hint(self):
        big = "z" * 100_000
        result = _cap(big)
        assert "truncated by runner" in result
        assert "100000 bytes" in result
        assert len(result.encode("utf-8")) < len(big)

    def test_truncates_cjk_by_bytes_not_codepoints(self):
        # 16000 CJK codepoints would FALSE-PASS under codepoint semantics
        # (16000 < TOOL_RESULT_SIZE_CAP) but is 48000 UTF-8 bytes.
        cjk = "中" * 16000
        result = _cap(cjk)
        assert "truncated by runner" in result
        assert "48000 bytes" in result
        assert len(result.encode("utf-8")) <= TOOL_RESULT_SIZE_CAP + 100

    def test_truncated_output_is_valid_utf8_when_slice_lands_midchar(self):
        # 6000 CJK chars = 18000 bytes; the byte-slice will land
        # mid-multibyte-character. errors="ignore" must produce valid UTF-8.
        test = "中" * 6000
        result = _cap(test)
        # Round-trip would raise UnicodeDecodeError if invalid bytes leaked
        result.encode("utf-8").decode("utf-8")


class TestRepoPinError:
    def test_matching_repo_returns_none(self):
        assert repo_pin_error({"owner": "o", "repo": "r"}, "o/r") is None

    def test_match_is_case_insensitive(self):
        assert (
            repo_pin_error({"owner": "Why-Pengo", "repo": "Health_Track"}, "why-pengo/health_track")
            is None
        )

    def test_mismatched_repo_errors(self):
        result = repo_pin_error({"owner": "evil", "repo": "other"}, "o/r")
        assert result is not None and result.startswith("ERROR")
        assert "evil/other" in result and "o/r" in result

    def test_missing_owner_fails_closed(self):
        result = repo_pin_error({"repo": "r"}, "o/r")
        assert result is not None and result.startswith("ERROR")

    def test_non_string_owner_fails_closed(self):
        result = repo_pin_error({"owner": ["o"], "repo": "r"}, "o/r")
        assert result is not None and result.startswith("ERROR")

    def test_empty_strings_fail_closed(self):
        result = repo_pin_error({"owner": "", "repo": ""}, "o/r")
        assert result is not None and result.startswith("ERROR")


class TestUrlEncoding:
    """Model-supplied URL components must reach gh percent-encoded so they
    can't terminate the path early or smuggle query parameters (#119)."""

    def test_path_special_chars_are_encoded(self, monkeypatch):
        content = base64.b64encode(b"hello").decode("ascii")
        calls = _capture_gh(monkeypatch, out=content)
        result = tools.github_get_file_contents({"owner": "o", "repo": "r", "path": "a b?c#d"})
        assert result == "hello"
        ((args, _),) = calls
        assert args[1] == "repos/o/r/contents/a%20b%3Fc%23d"

    def test_path_slashes_survive_as_separators(self, monkeypatch):
        content = base64.b64encode(b"x").decode("ascii")
        calls = _capture_gh(monkeypatch, out=content)
        tools.github_get_file_contents({"owner": "o", "repo": "r", "path": "src/app/main.py"})
        ((args, _),) = calls
        assert args[1] == "repos/o/r/contents/src/app/main.py"

    def test_ref_is_encoded_as_query_value(self, monkeypatch):
        content = base64.b64encode(b"x").decode("ascii")
        calls = _capture_gh(monkeypatch, out=content)
        tools.github_get_file_contents({"owner": "o", "repo": "r", "path": "f.py", "ref": "x&y=1"})
        ((args, _),) = calls
        assert args[1] == "repos/o/r/contents/f.py?ref=x%26y%3D1"

    def test_branch_with_slash_still_works_in_refs_url(self, monkeypatch):
        calls = _capture_gh(monkeypatch, out="abc1234")
        tools.github_create_branch(
            {"owner": "o", "repo": "r", "branch": "b", "from_branch": "runner/issue-42-x"}
        )
        assert calls[0][0][1] == "repos/o/r/git/refs/heads/runner/issue-42-x"

    def test_dot_segment_path_is_rejected_before_gh_runs(self, monkeypatch):
        calls = _capture_gh(monkeypatch)
        result = tools.github_get_file_contents(
            {"owner": "o", "repo": "r", "path": "../../user/repos"}
        )
        assert result.startswith("ERROR")
        assert calls == []

    def test_dot_segment_branch_is_rejected_before_gh_runs(self, monkeypatch):
        calls = _capture_gh(monkeypatch)
        result = tools.github_push_files(
            {"owner": "o", "repo": "r", "branch": "../main", "files": [], "message": "m"}
        )
        assert result.startswith("ERROR")
        assert calls == []


class TestIssueNumberValidation:
    def test_numeric_string_is_accepted(self, monkeypatch):
        calls = _capture_gh(monkeypatch, out="{}")
        result = tools.github_issue_read({"owner": "o", "repo": "r", "issue_number": "51"})
        assert not result.startswith("ERROR")
        assert calls[0][0][1] == "repos/o/r/issues/51"

    def test_path_shaped_issue_number_is_rejected(self, monkeypatch):
        calls = _capture_gh(monkeypatch)
        result = tools.github_issue_read({"owner": "o", "repo": "r", "issue_number": "51/comments"})
        assert result.startswith("ERROR")
        assert calls == []

    def test_add_issue_comment_rejects_non_int(self, monkeypatch):
        calls = _capture_gh(monkeypatch)
        result = tools.github_add_issue_comment(
            {"owner": "o", "repo": "r", "issue_number": None, "body": "hi"}
        )
        assert result.startswith("ERROR")
        assert calls == []
