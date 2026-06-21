"""Unit tests for the pure functions in runner/run_recipe.py.

These cover the functions that don't need to shell out to gh or hit Ollama:
result-size capping, success tracking, recipe completion, template substitution,
recipe loading with defaults, and session-message extractors.
"""

import textwrap

import httpx
import pytest

import run_recipe
from run_recipe import (
    GENERIC_CONTINUE_PROMPT,
    TOOL_RESULT_SIZE_CAP,
    _cap,
    _coerce_option_value,
    _extract_branch,
    _extract_issue_title,
    _tool_result_succeeded,
    extract_turn_metrics,
    format_session_metrics_summary,
    format_turn_metrics,
    load_recipe,
    ollama_chat,
    parse_prose_tool_call,
    recipe_done,
    run_session,
    step_aware_continue_prompt,
    template_recipe,
    turn_signature,
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
# extract_turn_metrics / format_turn_metrics / format_session_metrics_summary
#   — Ollama /api/chat per-call timing surfacing (#88)
# ---------------------------------------------------------------------------


class TestExtractTurnMetrics:
    def test_extracts_full_metric_block(self):
        resp = {
            "message": {"content": "ok"},
            "total_duration": 9876543210,
            "load_duration": 12345678,
            "prompt_eval_count": 1234,
            "prompt_eval_duration": 234567890,
            "eval_count": 567,
            "eval_duration": 8765432109,
        }
        m = extract_turn_metrics(resp)
        assert m == {
            "prompt_eval_count": 1234,
            "prompt_eval_duration": 234567890,
            "eval_count": 567,
            "eval_duration": 8765432109,
            "total_duration": 9876543210,
            "load_duration": 12345678,
        }

    def test_partial_block_keeps_present_fields_and_nulls_missing(self):
        # Some backends / mocked responses include only a subset. Missing
        # fields must come through as None so downstream formatters can
        # render them as "?" instead of crashing.
        resp = {"message": {}, "eval_count": 100, "eval_duration": 1_000_000_000}
        m = extract_turn_metrics(resp)
        assert m == {
            "prompt_eval_count": None,
            "prompt_eval_duration": None,
            "eval_count": 100,
            "eval_duration": 1_000_000_000,
            "total_duration": None,
            "load_duration": None,
        }

    def test_returns_none_when_no_metric_fields_present(self):
        # Bare response (mocked tests, non-Ollama backends) → None signals
        # the runner to stay quiet rather than emitting an all-"?" line.
        assert extract_turn_metrics({"message": {"content": "ok"}}) is None
        assert extract_turn_metrics({}) is None


class TestFormatTurnMetrics:
    def test_renders_issue_88_format_verbatim(self):
        # 1234 prompt tokens / 0.234567890s ≈ 5260.7 t/s
        # 567 gen tokens    / 8.765432109s ≈ 64.7 t/s
        # total = 9.876543210s              → 9.9s
        m = {
            "prompt_eval_count": 1234,
            "prompt_eval_duration": 234567890,
            "eval_count": 567,
            "eval_duration": 8765432109,
            "total_duration": 9876543210,
            "load_duration": 12345678,
        }
        assert (
            format_turn_metrics(m)
            == "[metrics: prompt=1234 tok @ 5260.7 t/s | gen=567 tok @ 64.7 t/s | total=9.9s]"
        )

    def test_renders_missing_fields_as_question_marks(self):
        m = {
            "prompt_eval_count": None,
            "prompt_eval_duration": None,
            "eval_count": 567,
            "eval_duration": 8765432109,
            "total_duration": None,
            "load_duration": None,
        }
        assert (
            format_turn_metrics(m)
            == "[metrics: prompt=? tok @ ? t/s | gen=567 tok @ 64.7 t/s | total=?s]"
        )

    def test_zero_duration_renders_rate_as_question_mark(self):
        # Defensive: a zero duration would otherwise blow up with
        # ZeroDivisionError. Render as "?" instead — same as missing.
        m = {
            "prompt_eval_count": 100,
            "prompt_eval_duration": 0,
            "eval_count": 0,
            "eval_duration": 0,
            "total_duration": 0,
            "load_duration": 0,
        }
        assert (
            format_turn_metrics(m)
            == "[metrics: prompt=100 tok @ ? t/s | gen=0 tok @ ? t/s | total=0.0s]"
        )


class TestFormatSessionMetricsSummary:
    def test_aggregates_by_summing_tokens_and_durations(self):
        # Token-weighted rates (sum tok / sum dur), not arithmetic mean
        # of per-turn rates — that's the "effective throughput" a plot wants.
        turns = [
            {
                "prompt_eval_count": 100,
                "prompt_eval_duration": 100_000_000,  # 0.1s → 1000 t/s
                "eval_count": 50,
                "eval_duration": 1_000_000_000,  # 1.0s → 50 t/s
                "total_duration": 1_500_000_000,  # 1.5s
                "load_duration": None,
            },
            {
                "prompt_eval_count": 200,
                "prompt_eval_duration": 100_000_000,  # 0.1s → 2000 t/s
                "eval_count": 100,
                "eval_duration": 2_000_000_000,  # 2.0s → 50 t/s
                "total_duration": 2_500_000_000,  # 2.5s
                "load_duration": None,
            },
        ]
        # prompt: 300 / 0.2s = 1500.0 t/s; gen: 150 / 3.0s = 50.0 t/s; wall: 4.0s
        assert format_session_metrics_summary(turns) == (
            "[session metrics: turns=2 | prompt=300 tok @ 1500.0 t/s | "
            "gen=150 tok @ 50.0 t/s | wall=4.0s]"
        )

    def test_empty_list_returns_no_metrics_line(self):
        # An exit path with zero captured metrics (mocked backend, or an
        # Ollama version that doesn't populate them) still gets a summary
        # line — the marker is useful when grepping logs for run boundaries.
        assert (
            format_session_metrics_summary([])
            == "[session metrics: turns=0 (no per-call metrics captured)]"
        )

    def test_partial_per_turn_fields_dont_crash(self):
        # If some turns have missing fields (None), the aggregator should
        # skip the Nones rather than crash on sum(None, int).
        turns = [
            {
                "prompt_eval_count": 100,
                "prompt_eval_duration": 100_000_000,
                "eval_count": None,
                "eval_duration": None,
                "total_duration": 1_000_000_000,
                "load_duration": None,
            }
        ]
        # gen sums to 0 → rate renders as "?"
        assert format_session_metrics_summary(turns) == (
            "[session metrics: turns=1 | prompt=100 tok @ 1000.0 t/s | "
            "gen=0 tok @ ? t/s | wall=1.0s]"
        )


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

    def test_handles_dict_arguments_from_native_api_chat(self):
        # Regression: native /api/chat returns arguments as a dict (not a JSON
        # string). _extract_branch used to json.loads() it unconditionally and
        # crash the salvage path with TypeError. eval-24 surfaced this.
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "b1",
                        "function": {
                            "name": "github__create_branch",
                            "arguments": {
                                "branch": "runner/issue-51-foo",
                                "from_branch": "develop",
                            },
                        },
                    }
                ],
            },
        ]
        assert _extract_branch(messages) == "runner/issue-51-foo"


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


# ---------------------------------------------------------------------------
# parse_prose_tool_call — rescue tool calls emitted in the content channel (#84)
# ---------------------------------------------------------------------------


DISPATCH_FIXTURE = {
    "github__issue_read",
    "github__get_file_contents",
    "github__create_branch",
    "github__create_or_update_file",
    "github__create_pull_request",
    "github__add_issue_comment",
    "github__push_files",
}


class TestParseProseToolCall:
    def test_clean_json_only_content_with_arguments_key(self):
        # The eval-29 shape exactly: qwen2.5-coder:32b emitted this as
        # content with empty tool_calls.
        content = (
            '{"name": "github__get_file_contents", '
            '"arguments": {"owner": "why-pengo", "repo": "health_track", '
            '"path": "AGENTS.md"}}'
        )
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        fn_name, fn_args = result
        assert fn_name == "github__get_file_contents"
        assert fn_args == {
            "owner": "why-pengo",
            "repo": "health_track",
            "path": "AGENTS.md",
        }

    def test_clean_json_with_parameters_key(self):
        # llama3.3:70b emitted with `parameters` instead of `arguments`.
        content = (
            '{"type": "function", "name": "github__create_or_update_file", '
            '"parameters": {"path": "x.py", "content": "..."}}'
        )
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        fn_name, fn_args = result
        assert fn_name == "github__create_or_update_file"
        assert fn_args == {"path": "x.py", "content": "..."}

    def test_single_underscore_name_gets_normalized(self):
        # llama3.3 emitted `github_create_or_update_file` (single underscore)
        # where DISPATCH uses `github__create_or_update_file`. The eval-26
        # log shows this exactly.
        content = '{"name": "github_create_or_update_file", ' '"arguments": {"path": "x.py"}}'
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        fn_name, _ = result
        assert fn_name == "github__create_or_update_file"

    def test_normalization_is_scoped_to_github_prefix(self):
        # Regression guard against the broader "double the first underscore"
        # form the normalization used to take. A hypothetical future tool
        # like `slack__post_message` would mean an unknown name like
        # `slack_post_message` should NOT be coerced to it just because the
        # underscore-doubling happens to match.
        dispatch_with_slack = DISPATCH_FIXTURE | {"slack__post_message"}
        content = '{"name": "slack_post_message", "arguments": {"channel": "x"}}'
        assert parse_prose_tool_call(content, dispatch_with_slack) is None

    def test_json_wrapped_in_prose(self):
        content = (
            "I'll need to read the issue first. Calling: "
            '{"name": "github__issue_read", '
            '"arguments": {"owner": "x", "repo": "y", "issue_number": 1}} '
            "and then I'll proceed."
        )
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        fn_name, fn_args = result
        assert fn_name == "github__issue_read"
        assert fn_args == {"owner": "x", "repo": "y", "issue_number": 1}

    def test_json_in_markdown_code_fence(self):
        content = (
            "```json\n"
            '{"name": "github__create_branch", '
            '"arguments": {"owner": "x", "repo": "y", "branch": "feat/x"}}\n'
            "```"
        )
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        fn_name, _ = result
        assert fn_name == "github__create_branch"

    def test_missing_args_defaults_to_empty_dict(self):
        # Some calls legitimately take no args (none of ours, but the model
        # could omit arguments anyway). Default to {} rather than refusing.
        content = '{"name": "github__issue_read"}'
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        _, fn_args = result
        assert fn_args == {}

    def test_unknown_tool_name_returns_none(self):
        # The model could hallucinate a tool name. Don't dispatch a guess.
        content = '{"name": "github__delete_repository", "arguments": {"repo": "x"}}'
        assert parse_prose_tool_call(content, DISPATCH_FIXTURE) is None

    def test_malformed_json_returns_none(self):
        # Looks tool-call-shaped but isn't valid JSON.
        content = '{"name": "github__issue_read", "arguments": {oops}'
        assert parse_prose_tool_call(content, DISPATCH_FIXTURE) is None

    def test_empty_content_returns_none(self):
        assert parse_prose_tool_call("", DISPATCH_FIXTURE) is None

    def test_content_without_name_key_returns_none(self):
        # Just any prose, even if it parses as JSON.
        content = '{"thought": "I should probably read the file."}'
        assert parse_prose_tool_call(content, DISPATCH_FIXTURE) is None

    def test_first_valid_object_wins_when_multiple(self):
        # Two candidate JSON blobs; first valid one is used.
        content = (
            'Plan: {"name": "github__issue_read", '
            '"arguments": {"owner": "x", "repo": "y", "issue_number": 1}}. '
            'Then: {"name": "github__create_branch", '
            '"arguments": {"branch": "feat/x"}}.'
        )
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        fn_name, _ = result
        assert fn_name == "github__issue_read"

    def test_nested_args_dict_preserved(self):
        content = (
            '{"name": "github__push_files", '
            '"arguments": {"files": [{"path": "a.py", "content": "x"}], '
            '"message": "m"}}'
        )
        result = parse_prose_tool_call(content, DISPATCH_FIXTURE)
        assert result is not None
        _, fn_args = result
        assert fn_args["files"] == [{"path": "a.py", "content": "x"}]


# ---------------------------------------------------------------------------
# turn_signature — hashable per-turn signature for #85 loop detection
# ---------------------------------------------------------------------------


class TestTurnSignature:
    def test_identical_tool_calls_match(self):
        a = {
            "tool_calls": [
                {"function": {"name": "github__get_file_contents", "arguments": '{"path": "x"}'}}
            ]
        }
        b = {
            "tool_calls": [
                {"function": {"name": "github__get_file_contents", "arguments": '{"path": "x"}'}}
            ]
        }
        assert turn_signature(a) == turn_signature(b)

    def test_different_args_dont_match(self):
        a = {
            "tool_calls": [
                {"function": {"name": "github__get_file_contents", "arguments": '{"path": "x"}'}}
            ]
        }
        b = {
            "tool_calls": [
                {"function": {"name": "github__get_file_contents", "arguments": '{"path": "y"}'}}
            ]
        }
        assert turn_signature(a) != turn_signature(b)

    def test_arguments_as_string_and_dict_canonicalize_equal(self):
        # /api/chat returns arguments as a dict; some other providers as a
        # JSON string. Same logical call must produce the same signature.
        as_string = {"tool_calls": [{"function": {"name": "f", "arguments": '{"a": 1, "b": 2}'}}]}
        as_dict = {"tool_calls": [{"function": {"name": "f", "arguments": {"a": 1, "b": 2}}}]}
        assert turn_signature(as_string) == turn_signature(as_dict)

    def test_arg_key_ordering_does_not_affect_signature(self):
        a = {"tool_calls": [{"function": {"name": "f", "arguments": {"a": 1, "b": 2}}}]}
        b = {"tool_calls": [{"function": {"name": "f", "arguments": {"b": 2, "a": 1}}}]}
        assert turn_signature(a) == turn_signature(b)

    def test_prose_turns_match_on_equal_content(self):
        a = {"content": "I cannot do this task without more context."}
        b = {"content": "I cannot do this task without more context."}
        assert turn_signature(a) == turn_signature(b)

    def test_prose_turns_differ_on_different_content(self):
        a = {"content": "blob A"}
        b = {"content": "blob B"}
        assert turn_signature(a) != turn_signature(b)

    def test_tool_call_and_prose_never_match(self):
        # Critical for the alternating pattern (eval-26) — a tool-call turn
        # and a prose-only turn must produce different signatures even if
        # both happen to be "empty-ish".
        tc = {"tool_calls": [{"function": {"name": "f", "arguments": "{}"}}]}
        prose = {"content": ""}
        assert turn_signature(tc) != turn_signature(prose)


# ---------------------------------------------------------------------------
# run_session loop-detect — abort on repeated signature (#85)
# ---------------------------------------------------------------------------


def _scripted_chat(scripted_responses: list[dict]):
    """Factory: returns an ollama_chat replacement that pops scripted
    responses in order. Tests inject this via monkeypatch to drive
    run_session through a deterministic sequence of model outputs.
    """
    queue = list(scripted_responses)

    def fake_chat(client, host, model, messages, tool_schemas, options=None):
        if not queue:
            raise AssertionError(
                "ollama_chat called past end of scripted responses — "
                "test expected the session to have ended by now"
            )
        return {"message": queue.pop(0), "done_reason": "stop"}

    return fake_chat


def _minimal_recipe(tmp_path):
    """Write the smallest possible recipe yaml that load_recipe accepts.
    Empty steps list keeps step_aware_continue_prompt falling back to the
    generic continue prompt without us having to fixture a step graph.
    """
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text("title: Test\nprompt: 'go'\nsteps: []\n")
    return recipe


def _ok_dispatch():
    """DISPATCH stand-in: every tool returns "OK" and counts as a success."""
    return {
        "github__issue_read": lambda args: '{"number": 1, "title": "t"}',
        "github__get_file_contents": lambda args: "file contents",
        "github__create_branch": lambda args: "OK",
        "github__create_or_update_file": lambda args: "OK",
        "github__push_files": lambda args: "OK",
        "github__create_pull_request": lambda args: "OK",
        "github__add_issue_comment": lambda args: "OK",
    }


def _tool_call_msg(name: str, args: dict) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": args}}],
    }


def _prose_msg(content: str) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": []}


class TestRunSessionLoopDetect:
    """Covers the eval-26 sampling-collapse failure mode.

    Strategy: monkeypatch ollama_chat + DISPATCH + attempt_salvage so the
    session runs entirely off scripted in-memory data. The thing under
    test is the return code from run_session: 4 means loop detected;
    anything else means the guard didn't fire.
    """

    def _runs(self, monkeypatch, tmp_path, scripted, **kwargs):
        monkeypatch.setattr(run_recipe, "ollama_chat", _scripted_chat(scripted))
        monkeypatch.setattr(run_recipe, "DISPATCH", _ok_dispatch())
        monkeypatch.setattr(run_recipe, "attempt_salvage", lambda *a, **kw: None)
        recipe = _minimal_recipe(tmp_path)
        return run_session(
            host="http://example",
            model="m",
            recipe_path=recipe,
            # The system prompt references {{ base_branch }} / {{ repo }};
            # pass placeholders so template_recipe doesn't raise.
            params={"base_branch": "main", "repo": "owner/repo", "issue_number": "1"},
            max_turns=kwargs.get("max_turns", 20),
            salvage_enabled=False,
            loop_detect_threshold=kwargs.get("loop_detect_threshold", 4),
            turn_timeout=10.0,
        )

    def test_identical_repeats_abort_at_threshold(self, monkeypatch, tmp_path):
        # The first sighting of any tool name registers as progress (newly
        # added to `succeeded`), which clears the counter — so 4 identical
        # repeats from a fresh session sit at count=3 after turn 4.
        # Five identical calls = 1 priming-progress + 4 no-progress repeats,
        # which is the natural threshold trip and mirrors what eval-26 did
        # at much higher repetition counts.
        scripted = [_tool_call_msg("github__get_file_contents", {"path": "x"})] * 5
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 4

    def test_three_identical_then_progress_does_not_trip(self, monkeypatch, tmp_path):
        # Three reads of the same file (legitimate: "read, look at it, read
        # again to verify after my own edit"). Then a fresh tool name reaches
        # succeeded, then recipe_done closes the session.
        scripted = [
            _tool_call_msg("github__get_file_contents", {"path": "x"}),
            _tool_call_msg("github__get_file_contents", {"path": "x"}),
            _tool_call_msg("github__get_file_contents", {"path": "x"}),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 0  # recipe_done, not loop-aborted

    def test_alternating_tool_call_and_prose_trips_the_guard(self, monkeypatch, tmp_path):
        # This is what eval-26 actually looked like: real tool call X, then
        # a prose blob (the model "thinks" it's emitting another tool call
        # but it lands as content), then X again, then prose, etc. The
        # consecutive-empty-turn guard never fires because the tool-call
        # turn keeps resetting it. The Counter-based loop detect catches it
        # because X's count climbs every two turns.
        x = _tool_call_msg("github__get_file_contents", {"path": "x"})
        prose = _prose_msg('{"name": "create_or_update_file", "args": {...}}')
        scripted = [x, prose, x, prose, x, prose, x, prose]
        # Trace: turn 1 X is first-seen → progress, counter clears. From there:
        # turn 2 prose→count[prose]=1, turn 3 X→count[X]=1, turn 4 prose=2,
        # turn 5 X=2, turn 6 prose=3, turn 7 X=3, turn 8 prose=4 → TRIP.
        # Prose hits threshold first, on turn 8, because the X-first-sighting
        # progress on turn 1 gave X a one-turn head start that it never gets back.
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 4

    def test_progress_in_middle_resets_the_counter(self, monkeypatch, tmp_path):
        # Three identical reads, then a NEW tool name reaches succeeded
        # (resets the Counter), then three more identical reads — the
        # original signature's count never reaches 4 in a single window.
        # Session ends via recipe_done after the PR + comment.
        x = _tool_call_msg("github__get_file_contents", {"path": "x"})
        scripted = [
            x,
            x,
            x,
            _tool_call_msg("github__create_branch", {}),  # progress: clears Counter
            x,
            x,
            x,
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 0

    def test_no_loop_detect_disables_guard(self, monkeypatch, tmp_path):
        # With threshold=None, even 5 identical no-progress turns must not
        # trip — caller has explicitly asked to investigate behaviour that
        # would otherwise abort.
        x = _tool_call_msg("github__get_file_contents", {"path": "x"})
        scripted = [
            x,
            x,
            x,
            x,
            x,
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(
            monkeypatch,
            tmp_path,
            scripted,
            loop_detect_threshold=None,
        )
        assert rc == 0


# ---------------------------------------------------------------------------
# run_session — end-to-end with prose-shaped tool call rescue (#84)
# ---------------------------------------------------------------------------


class TestRunSessionProseRescue:
    """Covers the eval-29 failure mode end-to-end.

    The rescue lives between the assistant message arriving and being
    appended to the message history; it synthesises tool_calls IN PLACE
    so the rest of the dispatch path is unchanged. These tests drive
    run_session with prose-only messages and verify the recipe progresses
    as if those had been structured tool calls.
    """

    def _runs(self, monkeypatch, tmp_path, scripted, **kwargs):
        monkeypatch.setattr(run_recipe, "ollama_chat", _scripted_chat(scripted))
        monkeypatch.setattr(run_recipe, "DISPATCH", _ok_dispatch())
        monkeypatch.setattr(run_recipe, "attempt_salvage", lambda *a, **kw: None)
        recipe = _minimal_recipe(tmp_path)
        return run_session(
            host="http://example",
            model="m",
            recipe_path=recipe,
            params={"base_branch": "main", "repo": "owner/repo", "issue_number": "1"},
            max_turns=kwargs.get("max_turns", 20),
            salvage_enabled=False,
            loop_detect_threshold=kwargs.get("loop_detect_threshold", 4),
            turn_timeout=10.0,
        )

    def test_prose_only_sequence_completes_recipe(self, monkeypatch, tmp_path):
        # eval-29-shaped sequence: every "tool call" comes in as content,
        # not as tool_calls. Without rescue, the empty_turn_count guard
        # aborts at turn 3. With rescue, dispatch sees structured tool
        # calls and the recipe completes normally.
        scripted = [
            _prose_msg(
                '{"name": "github__issue_read", '
                '"arguments": {"owner": "x", "repo": "y", "issue_number": 1}}'
            ),
            _prose_msg(
                '{"name": "github__create_pull_request", '
                '"arguments": {"head": "h", "base": "b"}}'
            ),
            _prose_msg('{"name": "github__add_issue_comment", ' '"arguments": {"body": "done"}}'),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 0  # recipe_done after PR + comment

    def test_mixed_real_and_prose_calls_both_dispatch(self, monkeypatch, tmp_path):
        # Real structured tool calls and prose-shaped ones must coexist —
        # nothing about the rescue should break the normal path.
        scripted = [
            _tool_call_msg("github__issue_read", {"issue_number": 1}),
            _prose_msg(
                '{"name": "github__create_pull_request", '
                '"arguments": {"head": "h", "base": "b"}}'
            ),
            _tool_call_msg("github__add_issue_comment", {"body": "done"}),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 0

    def test_prose_without_tool_call_shape_still_nudges(self, monkeypatch, tmp_path):
        # Plain prose with no parseable tool call must NOT rescue —
        # rescue is strict. The existing empty-turn guard should still
        # abort after 3 of these.
        scripted = [
            _prose_msg("I don't know what to do here."),
            _prose_msg("Still thinking."),
            _prose_msg("Hmm."),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 2  # empty_turn_count >= 3

    def test_unknown_tool_in_prose_does_not_rescue(self, monkeypatch, tmp_path):
        # Even if the prose looks like a tool call, the rescue refuses
        # unknown tool names rather than dispatching a hallucination.
        scripted = [
            _prose_msg('{"name": "github__delete_repository", "arguments": {"repo": "x"}}'),
            _prose_msg('{"name": "github__delete_repository", "arguments": {"repo": "x"}}'),
            _prose_msg('{"name": "github__delete_repository", "arguments": {"repo": "x"}}'),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted)
        assert rc == 2  # treated as no-tool-call; empty-turn guard fires
