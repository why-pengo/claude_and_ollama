"""Unit tests for runner/salvage.py pure helpers.

The salvage_pr / salvage_comment functions shell out to gh and need a real
GitHub round-trip to test meaningfully — those are covered by smoke tests
against why-pengo/health_track during development. The URL-encoding helper
and the format_salvage_status presenter are pure and worth focused tests.
"""

from salvage import _q, format_salvage_status


class TestQuoteHelper:
    def test_encodes_slash_in_branch_name(self):
        assert _q("runner/issue-51-foo") == "runner%2Fissue-51-foo"

    def test_encodes_special_chars(self):
        # The safe="" arg means *everything* non-alphanumeric gets encoded
        assert _q("feature/with space") == "feature%2Fwith%20space"

    def test_leaves_simple_branch_unchanged(self):
        assert _q("main") == "main"
        assert _q("develop") == "develop"


class TestFormatSalvageStatus:
    def test_opened_includes_pr_url_and_commit_count(self):
        result = {
            "status": "opened",
            "pr_number": 71,
            "pr_url": "https://github.com/o/r/pull/71",
            "commit_count": 3,
        }
        s = format_salvage_status(result, "runner/issue-51-foo", "main")
        assert s.startswith("✓ Salvage PR opened: ")
        assert "https://github.com/o/r/pull/71" in s
        assert "(3 commits)" in s

    def test_pr_exists_includes_number(self):
        result = {"status": "pr_exists", "pr_number": 64}
        s = format_salvage_status(result, "runner/issue-51-foo", "main")
        assert s.startswith("– PR already exists")
        assert "#64" in s

    def test_no_branch_includes_branch_name(self):
        s = format_salvage_status({"status": "no_branch"}, "runner/issue-99-bar", "main")
        assert "runner/issue-99-bar" in s
        assert s.startswith("– Branch ")

    def test_no_commits_includes_branch_and_base(self):
        s = format_salvage_status({"status": "no_commits"}, "runner/issue-99-bar", "develop")
        assert "runner/issue-99-bar" in s
        assert "develop" in s
        assert "no commits ahead" in s

    def test_error_includes_message(self):
        result = {"status": "error", "error": "422 Unprocessable Entity"}
        s = format_salvage_status(result, "runner/issue-51-foo", "main")
        assert s.startswith("✗ Salvage failed: ")
        assert "422 Unprocessable Entity" in s

    def test_error_without_message_falls_back_to_unknown(self):
        s = format_salvage_status({"status": "error"}, "runner/issue-51-foo", "main")
        assert "unknown" in s

    def test_unrecognised_status_uses_question_mark_marker(self):
        # Regression guard for the failure mode #61 calls out: a new status
        # added in salvage.py without an entry here should be obvious in
        # eval logs, not silently fall through.
        s = format_salvage_status({"status": "rate_limited"}, "runner/issue-51-foo", "main")
        assert s.startswith("? Unexpected salvage status: ")
        assert "rate_limited" in s
