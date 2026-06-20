"""Unit tests for the pure functions in runner/run_recipe.py.

These cover the functions that don't need to shell out to gh or hit Ollama:
result-size capping, success tracking, recipe completion, template substitution,
recipe loading with defaults, and session-message extractors.
"""

import textwrap

import httpx
import pytest

from run_recipe import (
    GENERIC_CONTINUE_PROMPT,
    TOOL_RESULT_SIZE_CAP,
    _cap,
    _coerce_option_value,
    _extract_branch,
    _extract_issue_title,
    _tool_result_succeeded,
    load_recipe,
    ollama_chat,
    recipe_done,
    step_aware_continue_prompt,
    template_recipe,
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
# _tool_result_succeeded — predicate that gates success-set membership.
# Lives at the dispatch loop now; tested here as the source of truth for
# the "ERROR prefix = failure" rule that was the #55 regression.
# ---------------------------------------------------------------------------


class TestToolResultSucceeded:
    def test_non_error_result_counts(self):
        assert _tool_result_succeeded('{"number": 71}') is True

    def test_error_prefixed_result_does_not_count(self):
        # This is the #55 regression guard — a failed PR call returns text
        # starting with "ERROR" and must not be credited as a success.
        assert _tool_result_succeeded("ERROR opening PR: 422 head already has open PR") is False

    def test_bare_error_prefix(self):
        assert _tool_result_succeeded("ERROR") is False

    def test_empty_result_counts(self):
        # An empty tool result isn't a failure — some tools return ""
        # on success (e.g. mid-run with no payload).
        assert _tool_result_succeeded("") is True


# ---------------------------------------------------------------------------
# recipe_done — set membership check
# ---------------------------------------------------------------------------


class TestRecipeDone:
    def test_true_when_both_succeeded(self):
        assert recipe_done({"github__create_pull_request", "github__add_issue_comment"}) is True

    def test_false_when_pr_missing(self):
        # The #55 bug: a failed PR call (not in `succeeded`) followed by a
        # successful comment must NOT count as done — the branch would orphan.
        assert recipe_done({"github__add_issue_comment"}) is False

    def test_false_when_comment_missing(self):
        assert recipe_done({"github__create_pull_request"}) is False

    def test_false_on_empty(self):
        assert recipe_done(set()) is False


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
        assert step_aware_continue_prompt(set(), STEPS_FIXTURE) == "NUDGE_READ_ISSUE"

    def test_advances_to_branch_after_issue_read(self):
        assert step_aware_continue_prompt({"github__issue_read"}, STEPS_FIXTURE) == "NUDGE_BRANCH"

    def test_advances_to_write_after_branch(self):
        succeeded = {"github__issue_read", "github__create_branch"}
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_WRITE"

    def test_advances_to_pr_after_push_files(self):
        succeeded = {"github__issue_read", "github__create_branch", "github__push_files"}
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_PR"

    def test_advances_to_pr_after_create_or_update_file(self):
        # Either write tool counts — they share an advances_on entry
        succeeded = {
            "github__issue_read",
            "github__create_branch",
            "github__create_or_update_file",
        }
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_PR"

    def test_advances_to_comment_after_pr(self):
        succeeded = {
            "github__issue_read",
            "github__create_branch",
            "github__push_files",
            "github__create_pull_request",
        }
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_COMMENT"

    def test_falls_back_when_all_done(self):
        succeeded = {
            "github__issue_read",
            "github__create_branch",
            "github__push_files",
            "github__create_pull_request",
            "github__add_issue_comment",
        }
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == GENERIC_CONTINUE_PROMPT

    def test_errored_pr_call_does_not_advance_to_comment(self):
        # A failed create_pull_request never enters `succeeded` (the dispatch
        # loop's `_tool_result_succeeded` gate keeps it out), so the PR step
        # is still pending and its nudge fires. Branch doesn't orphan.
        succeeded = {"github__issue_read", "github__create_branch", "github__push_files"}
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_PR"

    def test_empty_steps_returns_generic_fallback(self):
        assert step_aware_continue_prompt(set(), []) == GENERIC_CONTINUE_PROMPT

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
        assert step_aware_continue_prompt(set(), steps) == GENERIC_CONTINUE_PROMPT


# ---------------------------------------------------------------------------
# ollama_chat — POSTs through a caller-owned httpx.Client (#59)
#                to Ollama's native /api/chat endpoint (#78)
# ---------------------------------------------------------------------------


class TestOllamaChat:
    def test_uses_caller_provided_client_and_builds_url_payload(self):
        # Regression guard for #59: ollama_chat must accept and use the
        # client the caller passes in (so run_session can reuse a single
        # client + connection pool across every turn). Also pins the #78
        # native endpoint + envelope contract.
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            seen["url"] = str(request.url)
            seen["payload"] = _json.loads(request.content)
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "ok"}, "done_reason": "stop"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            resp = ollama_chat(
                client,
                "http://bazzite.local:11434",
                "qwen3.6:latest",
                [{"role": "user", "content": "hi"}],
                [{"type": "function", "function": {"name": "noop"}}],
            )

        assert seen["url"] == "http://bazzite.local:11434/api/chat"
        assert seen["payload"]["model"] == "qwen3.6:latest"
        assert seen["payload"]["stream"] is False
        assert seen["payload"]["messages"] == [{"role": "user", "content": "hi"}]
        assert seen["payload"]["tools"][0]["function"]["name"] == "noop"
        # No options passed → key must be absent from the wire payload.
        assert "options" not in seen["payload"]
        assert resp["message"]["content"] == "ok"

    def test_strips_trailing_slash_from_host(self):
        # Defensive: host=".../" should not produce "...//api/..." with a
        # double slash.
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"message": {"content": "x"}})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            ollama_chat(client, "http://example/", "m", [], [])

        assert seen["url"] == "http://example/api/chat"

    def test_raises_for_status_on_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                ollama_chat(client, "http://example", "m", [], [])

    def test_options_sent_when_non_empty(self):
        # Per-request options (num_ctx, num_gpu, seed, ...) must reach the
        # wire payload under an "options" key — this is the whole point of
        # the /api/chat swap (#78).
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            seen["payload"] = _json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": "ok"}})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            ollama_chat(
                client,
                "http://example",
                "m",
                [],
                [],
                options={"num_ctx": 65536, "num_gpu": 30, "seed": 42},
            )

        assert seen["payload"]["options"] == {"num_ctx": 65536, "num_gpu": 30, "seed": 42}

    def test_options_omitted_when_empty(self):
        # Explicit empty dict should behave the same as None: no options key
        # on the wire (lets Ollama apply its own defaults; keeps payloads lean).
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            seen["payload"] = _json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": "ok"}})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            ollama_chat(client, "http://example", "m", [], [], options={})

        assert "options" not in seen["payload"]


# ---------------------------------------------------------------------------
# _coerce_option_value — --ollama-option KEY=VALUE coercion (#78)
# ---------------------------------------------------------------------------


class TestCoerceOptionValue:
    def test_coerces_int(self):
        assert _coerce_option_value("30") == 30
        assert isinstance(_coerce_option_value("30"), int)

    def test_coerces_float(self):
        assert _coerce_option_value("0.7") == 0.7
        assert isinstance(_coerce_option_value("0.7"), float)

    def test_coerces_bool(self):
        assert _coerce_option_value("true") is True
        assert _coerce_option_value("True") is True
        assert _coerce_option_value("false") is False

    def test_keeps_arbitrary_string(self):
        assert _coerce_option_value("stop_here") == "stop_here"

    def test_int_takes_precedence_over_float(self):
        # "42" is parseable as both int and float; we want the int.
        assert _coerce_option_value("42") == 42
        assert isinstance(_coerce_option_value("42"), int)


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
        prompt, title, _steps, _opts = load_recipe(recipe, params)
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
        prompt, _, _, _ = load_recipe(recipe, params)
        assert "override/repo" in prompt

    def test_returns_empty_steps_when_block_absent(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                prompt: |
                  hi
                """))
        _, _, steps, _ = load_recipe(recipe, {})
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
        _, _, steps, _ = load_recipe(recipe, {"issue_number": "42"})
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
        _, _, steps, _ = load_recipe(recipe, {})
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

    def test_parses_options_block(self, tmp_path):
        # Recipe-level Ollama options carry through as the 4th tuple element
        # so run_session can merge them with CLI overrides.
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                options:
                  num_ctx: 65536
                  num_gpu: 30
                prompt: |
                  hi
                """))
        _, _, _, opts = load_recipe(recipe, {})
        assert opts == {"num_ctx": 65536, "num_gpu": 30}

    def test_rejects_non_mapping_options(self, tmp_path):
        # A scalar under `options:` is almost certainly an authoring typo
        # (`options: 65536` instead of `options:\n  num_ctx: 65536`).
        # Surface it loudly, not as a downstream dict()-coercion error.
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                options: 65536
                prompt: |
                  hi
                """))
        with pytest.raises(TypeError, match="recipe options"):
            load_recipe(recipe, {})

    def test_returns_empty_options_when_block_absent(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                prompt: |
                  hi
                """))
        _, _, _, opts = load_recipe(recipe, {})
        assert opts == {}

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
