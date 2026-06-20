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
    load_recipe,
    ollama_chat,
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
