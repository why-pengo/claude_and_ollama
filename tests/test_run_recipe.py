"""Unit tests for the pure functions in runner/run_recipe.py.

These cover the functions that don't need to shell out to gh or hit Ollama:
result-size capping, success tracking, recipe completion, template substitution,
recipe loading with defaults, and session-message extractors.
"""

import textwrap

import pytest

from run_recipe import (
    TOOL_RESULT_SIZE_CAP,
    _cap,
    _extract_branch,
    _extract_issue_title,
    load_recipe,
    recipe_done,
    template_recipe,
    tools_succeeded,
)

# ---------------------------------------------------------------------------
# _cap — UTF-8-byte truncation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# tools_succeeded — pair tool_calls with results, count only non-ERROR
# ---------------------------------------------------------------------------


def _assistant_call(tc_id: str, name: str) -> dict:
    return {
        "role": "assistant",
        "tool_calls": [{"id": tc_id, "function": {"name": name, "arguments": "{}"}}],
    }


def _tool_result(tc_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


class TestToolsSucceeded:
    def test_counts_non_error_results(self):
        messages = [
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", '{"number": 71}'),
            _assistant_call("c1", "github__add_issue_comment"),
            _tool_result("c1", "https://github.com/.../comments/1"),
        ]
        assert tools_succeeded(messages) == {
            "github__create_pull_request",
            "github__add_issue_comment",
        }

    def test_excludes_errored_results(self):
        # This is the #55 bug — a failed PR call must not count as succeeded
        messages = [
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", "ERROR opening PR: 422 head already has open PR"),
            _assistant_call("c1", "github__add_issue_comment"),
            _tool_result("c1", "https://github.com/.../comments/1"),
        ]
        assert tools_succeeded(messages) == {"github__add_issue_comment"}

    def test_credits_retry_after_initial_error(self):
        # Errored first, retried successfully — the retry success counts
        messages = [
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", "ERROR opening PR: 422"),
            _assistant_call("pr2", "github__create_pull_request"),
            _tool_result("pr2", '{"number": 72}'),
        ]
        assert "github__create_pull_request" in tools_succeeded(messages)


# ---------------------------------------------------------------------------
# recipe_done — both PR and comment must have succeeded
# ---------------------------------------------------------------------------


class TestRecipeDone:
    def test_true_when_both_succeeded(self):
        messages = [
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", '{"number": 71}'),
            _assistant_call("c1", "github__add_issue_comment"),
            _tool_result("c1", "https://github.com/.../comments/1"),
        ]
        assert recipe_done(messages) is True

    def test_false_when_pr_errored(self):
        # The #55 bug: this used to return True, orphaning the branch
        messages = [
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", "ERROR opening PR: 422"),
            _assistant_call("c1", "github__add_issue_comment"),
            _tool_result("c1", "https://github.com/.../comments/1"),
        ]
        assert recipe_done(messages) is False


# ---------------------------------------------------------------------------
# template_recipe — {{ key }} substitution
# ---------------------------------------------------------------------------


class TestTemplateRecipe:
    def test_substitutes_known_keys(self):
        prompt = "Issue #{{ issue_number }} in {{ repo }}."
        result = template_recipe(prompt, {"issue_number": "51", "repo": "owner/repo"})
        assert result == "Issue #51 in owner/repo."

    def test_handles_whitespace_around_key(self):
        prompt = "{{issue_number}} and {{  issue_number  }}"
        result = template_recipe(prompt, {"issue_number": "51"})
        assert result == "51 and 51"

    def test_raises_key_error_on_missing_key(self):
        with pytest.raises(KeyError, match="repo"):
            template_recipe("PR for {{ repo }}", {"issue_number": "51"})


# ---------------------------------------------------------------------------
# load_recipe — honors YAML-declared parameter defaults
# ---------------------------------------------------------------------------


class TestLoadRecipe:
    def test_fills_in_declared_defaults(self, tmp_path):
        # This is the ae87496 fix — load_recipe used to ignore the YAML's
        # parameters: block, raising KeyError on optional-with-default params.
        recipe = tmp_path / "execute-issue.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: Execute GitHub Issue
                parameters:
                  - key: issue_number
                    requirement: required
                  - key: repo
                    requirement: optional
                    default: why-pengo/claude_and_goose
                  - key: base_branch
                    requirement: optional
                    default: main
                prompt: |
                  Issue #{{ issue_number }} in {{ repo }} on {{ base_branch }}.
                """))
        params = {"issue_number": "51"}
        prompt, title = load_recipe(recipe, params)
        assert title == "Execute GitHub Issue"
        assert "Issue #51 in why-pengo/claude_and_goose on main." in prompt
        # Mutated in place so the caller can use the resolved values too
        assert params["repo"] == "why-pengo/claude_and_goose"
        assert params["base_branch"] == "main"

    def test_explicit_params_win_over_defaults(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                parameters:
                  - key: repo
                    requirement: optional
                    default: default/repo
                prompt: |
                  {{ repo }}
                """))
        params = {"repo": "override/repo"}
        prompt, _ = load_recipe(recipe, params)
        assert "override/repo" in prompt


# ---------------------------------------------------------------------------
# _extract_branch / _extract_issue_title — session-message extractors
# ---------------------------------------------------------------------------


class TestExtractBranch:
    def test_pulls_branch_from_create_branch_tool_call(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "b1",
                        "function": {
                            "name": "github__create_branch",
                            "arguments": '{"branch": "goose/issue-51-foo", "from_branch": "develop"}',
                        },
                    }
                ],
            },
        ]
        assert _extract_branch(messages) == "goose/issue-51-foo"

    def test_returns_none_when_no_create_branch(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "i1",
                        "function": {
                            "name": "github__issue_read",
                            "arguments": '{"issue_number": 51}',
                        },
                    }
                ],
            },
        ]
        assert _extract_branch(messages) is None


class TestExtractIssueTitle:
    def test_pulls_title_from_issue_read_result(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "i1",
                        "function": {"name": "github__issue_read", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "i1",
                "content": '{"number": 51, "title": "feat: GET /api/hydration/daily", "body": "..."}',
            },
        ]
        assert _extract_issue_title(messages) == "feat: GET /api/hydration/daily"

    def test_returns_none_when_no_issue_read(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "b1",
                        "function": {"name": "github__create_branch", "arguments": "{}"},
                    }
                ],
            },
        ]
        assert _extract_issue_title(messages) is None
