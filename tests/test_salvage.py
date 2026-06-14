"""Unit tests for runner/salvage.py pure helpers.

The salvage_pr / salvage_comment functions shell out to gh and need a real
GitHub round-trip to test meaningfully — those are covered by smoke tests
against why-pengo/health_track during development. The URL-encoding helper
is pure and worth a focused test.
"""

from salvage import _q


class TestQuoteHelper:
    def test_encodes_slash_in_branch_name(self):
        assert _q("runner/issue-51-foo") == "runner%2Fissue-51-foo"

    def test_encodes_special_chars(self):
        # The safe="" arg means *everything* non-alphanumeric gets encoded
        assert _q("feature/with space") == "feature%2Fwith%20space"

    def test_leaves_simple_branch_unchanged(self):
        assert _q("main") == "main"
        assert _q("develop") == "develop"
