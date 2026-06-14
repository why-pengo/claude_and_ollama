"""Unit tests for the pure functions in runner/run_recipe.py.

These cover the functions that don't need to shell out to gh or hit Ollama:
result-size capping, success tracking, recipe completion, template substitution,
recipe loading with defaults, and session-message extractors.
"""

import textwrap

import pytest

from run_recipe import (
    GENERIC_CONTINUE_PROMPT,
    TOOL_RESULT_SIZE_CAP,
    _cap,
    _extract_branch,
    _extract_issue_title,
    load_recipe,
    recipe_done,
    step_aware_continue_prompt,
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
# step_aware_continue_prompt — derive next-step nudge from the recipe graph
# ---------------------------------------------------------------------------


STEPS_FIXTURE = [
    {
        "id": "read_issue",
        "advances_on": ["github__issue_read"],
        "requires_prior": [],
        "nudge": "NUDGE_READ_ISSUE",
    },
    {
        "id": "branch",
        "advances_on": ["github__create_branch"],
        "requires_prior": ["read_issue"],
        "nudge": "NUDGE_BRANCH",
    },
    {
        "id": "write",
        "advances_on": ["github__push_files", "github__create_or_update_file"],
        "requires_prior": ["branch"],
        "nudge": "NUDGE_WRITE",
    },
    {
        "id": "pr",
        "advances_on": ["github__create_pull_request"],
        "requires_prior": ["write"],
        "nudge": "NUDGE_PR",
    },
    {
        "id": "comment",
        "advances_on": ["github__add_issue_comment"],
        "requires_prior": ["pr"],
        "nudge": "NUDGE_COMMENT",
    },
]


class TestStepAwareContinuePrompt:
    def test_returns_first_step_nudge_when_nothing_done(self):
        assert step_aware_continue_prompt([], STEPS_FIXTURE) == "NUDGE_READ_ISSUE"

    def test_advances_to_branch_after_issue_read(self):
        messages = [
            _assistant_call("i1", "github__issue_read"),
            _tool_result("i1", '{"number": 51}'),
        ]
        assert step_aware_continue_prompt(messages, STEPS_FIXTURE) == "NUDGE_BRANCH"

    def test_advances_to_write_after_branch(self):
        messages = [
            _assistant_call("i1", "github__issue_read"),
            _tool_result("i1", '{"number": 51}'),
            _assistant_call("b1", "github__create_branch"),
            _tool_result("b1", "ok"),
        ]
        assert step_aware_continue_prompt(messages, STEPS_FIXTURE) == "NUDGE_WRITE"

    def test_advances_to_pr_after_push_files(self):
        messages = [
            _assistant_call("i1", "github__issue_read"),
            _tool_result("i1", '{"number": 51}'),
            _assistant_call("b1", "github__create_branch"),
            _tool_result("b1", "ok"),
            _assistant_call("w1", "github__push_files"),
            _tool_result("w1", "Pushed"),
        ]
        assert step_aware_continue_prompt(messages, STEPS_FIXTURE) == "NUDGE_PR"

    def test_advances_to_pr_after_create_or_update_file(self):
        # Either write tool counts — they share an advances_on entry
        messages = [
            _assistant_call("i1", "github__issue_read"),
            _tool_result("i1", '{"number": 51}'),
            _assistant_call("b1", "github__create_branch"),
            _tool_result("b1", "ok"),
            _assistant_call("w1", "github__create_or_update_file"),
            _tool_result("w1", "Pushed"),
        ]
        assert step_aware_continue_prompt(messages, STEPS_FIXTURE) == "NUDGE_PR"

    def test_advances_to_comment_after_pr(self):
        messages = [
            _assistant_call("i1", "github__issue_read"),
            _tool_result("i1", '{"number": 51}'),
            _assistant_call("b1", "github__create_branch"),
            _tool_result("b1", "ok"),
            _assistant_call("w1", "github__push_files"),
            _tool_result("w1", "Pushed"),
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", '{"number": 71}'),
        ]
        assert step_aware_continue_prompt(messages, STEPS_FIXTURE) == "NUDGE_COMMENT"

    def test_falls_back_when_all_done(self):
        messages = [
            _assistant_call("i1", "github__issue_read"),
            _tool_result("i1", '{"number": 51}'),
            _assistant_call("b1", "github__create_branch"),
            _tool_result("b1", "ok"),
            _assistant_call("w1", "github__push_files"),
            _tool_result("w1", "Pushed"),
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", '{"number": 71}'),
            _assistant_call("c1", "github__add_issue_comment"),
            _tool_result("c1", "ok"),
        ]
        assert step_aware_continue_prompt(messages, STEPS_FIXTURE) == GENERIC_CONTINUE_PROMPT

    def test_errored_pr_call_does_not_advance_to_comment(self):
        # A failed create_pull_request must still trigger the PR nudge,
        # not the comment nudge — the branch would orphan otherwise.
        messages = [
            _assistant_call("i1", "github__issue_read"),
            _tool_result("i1", '{"number": 51}'),
            _assistant_call("b1", "github__create_branch"),
            _tool_result("b1", "ok"),
            _assistant_call("w1", "github__push_files"),
            _tool_result("w1", "Pushed"),
            _assistant_call("pr1", "github__create_pull_request"),
            _tool_result("pr1", "ERROR opening PR: 422"),
        ]
        assert step_aware_continue_prompt(messages, STEPS_FIXTURE) == "NUDGE_PR"

    def test_empty_steps_returns_generic_fallback(self):
        assert step_aware_continue_prompt([], []) == GENERIC_CONTINUE_PROMPT

    def test_skips_step_with_null_nudge(self):
        # A step without a nudge exists for prereq tracking only — the
        # walk should continue to the next eligible step instead of
        # falling through to the generic prompt.
        steps = [
            {
                "id": "read_issue",
                "advances_on": ["github__issue_read"],
                "requires_prior": [],
                "nudge": None,
            },
            {
                "id": "branch",
                "advances_on": ["github__create_branch"],
                "requires_prior": ["read_issue"],
                "nudge": "NUDGE_BRANCH",
            },
        ]
        # Nothing done yet → first step's nudge is None, walk continues,
        # but second step's prereq isn't met → falls through to generic.
        assert step_aware_continue_prompt([], steps) == GENERIC_CONTINUE_PROMPT


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
                    default: why-pengo/claude_and_ollama
                  - key: base_branch
                    requirement: optional
                    default: main
                prompt: |
                  Issue #{{ issue_number }} in {{ repo }} on {{ base_branch }}.
                """))
        params = {"issue_number": "51"}
        prompt, title, _steps = load_recipe(recipe, params)
        assert title == "Execute GitHub Issue"
        assert "Issue #51 in why-pengo/claude_and_ollama on main." in prompt
        # Mutated in place so the caller can use the resolved values too
        assert params["repo"] == "why-pengo/claude_and_ollama"
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
        prompt, _, _ = load_recipe(recipe, params)
        assert "override/repo" in prompt

    def test_returns_empty_steps_when_block_absent(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                prompt: |
                  hi
                """))
        _, _, steps = load_recipe(recipe, {})
        assert steps == []

    def test_parses_steps_and_templates_nudges(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: write
                    advances_on: [github__push_files]
                    requires_prior: [branch]
                    nudge: |
                      Open PR for #{{ issue_number }}.
                prompt: |
                  hi
                """))
        _, _, steps = load_recipe(recipe, {"issue_number": "42"})
        assert steps == [
            {
                "id": "write",
                "advances_on": ["github__push_files"],
                "requires_prior": ["branch"],
                "nudge": "Open PR for #42.\n",
            }
        ]

    def test_coerces_scalar_advances_on_into_single_element_list(self, tmp_path):
        # A recipe author writing `advances_on: github__issue_read` (scalar
        # rather than a list) used to silently become a list of characters.
        # Now coerced to ["github__issue_read"].
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: read_issue
                    advances_on: github__issue_read
                    requires_prior: branch
                    nudge: noop
                prompt: |
                  hi
                """))
        _, _, steps = load_recipe(recipe, {})
        assert steps[0]["advances_on"] == ["github__issue_read"]
        assert steps[0]["requires_prior"] == ["branch"]

    def test_rejects_non_string_in_advances_on_list(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: read_issue
                    advances_on: [42]
                    nudge: noop
                prompt: |
                  hi
                """))
        with pytest.raises(TypeError, match="advances_on"):
            load_recipe(recipe, {})

    def test_rejects_unexpected_advances_on_type(self, tmp_path):
        # A dict (or any non-str, non-list, non-None) at the field level is
        # almost certainly an authoring typo; surface it loudly.
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: read_issue
                    advances_on: {tool: github__issue_read}
                    nudge: noop
                prompt: |
                  hi
                """))
        with pytest.raises(TypeError, match="advances_on"):
            load_recipe(recipe, {})


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
                            "arguments": '{"branch": "runner/issue-51-foo", "from_branch": "develop"}',
                        },
                    }
                ],
            },
        ]
        assert _extract_branch(messages) == "runner/issue-51-foo"

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
