"""Unit tests for the pure functions in runner/run_recipe.py.

These cover the functions that don't need to shell out to gh or hit Ollama:
result-size capping, success tracking, recipe completion, template substitution,
recipe loading with defaults, and session-message extractors.
"""

import run_recipe
from run_recipe import (
    _coerce_option_value,
    _extract_branch,
    _extract_issue_title,
    parse_prose_tool_call,
    run_session,
    turn_signature,
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
            # The system prompt references {{ base_branch }} / {{ repo }} /
            # {{ branch }}; pass placeholders so template_recipe doesn't raise.
            params={
                "base_branch": "main",
                "repo": "owner/repo",
                "issue_number": "1",
                "branch": "runner/issue-1-20260627-000000",
            },
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
            params={
                "base_branch": "main",
                "repo": "owner/repo",
                "issue_number": "1",
                "branch": "runner/issue-1-20260627-000000",
            },
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
