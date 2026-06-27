"""Unit tests for runner/prose_rescue.py — prose-channel rescue + turn signature."""

from prose_rescue import parse_prose_tool_call, turn_signature

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
