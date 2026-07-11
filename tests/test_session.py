"""Unit tests for runner/session.py — extractors, salvage trigger, run_session loop."""

from agents_md import ParsedAgentsMd, VerificationCommand
from gate import CommandResult, GateError, GateResult

import session
from session import _extract_branch, _extract_issue_title, run_session

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
    # Repo pinning (#119) refuses calls whose owner/repo don't match the
    # session's params (repo="owner/repo" in _runs), so fixtures carry a
    # matching pair by default; pass explicit values to test mismatches.
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": name, "arguments": {"owner": "owner", "repo": "repo", **args}}}
        ],
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
        monkeypatch.setattr(session, "ollama_chat", _scripted_chat(scripted))
        monkeypatch.setattr(session, "DISPATCH", _ok_dispatch())
        monkeypatch.setattr(session, "attempt_salvage", lambda *a, **kw: None)
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
        monkeypatch.setattr(session, "ollama_chat", _scripted_chat(scripted))
        monkeypatch.setattr(session, "DISPATCH", _ok_dispatch())
        monkeypatch.setattr(session, "attempt_salvage", lambda *a, **kw: None)
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
                '"arguments": {"owner": "owner", "repo": "repo", "issue_number": 1}}'
            ),
            _prose_msg(
                '{"name": "github__create_pull_request", '
                '"arguments": {"owner": "owner", "repo": "repo", "head": "h", "base": "b"}}'
            ),
            _prose_msg(
                '{"name": "github__add_issue_comment", '
                '"arguments": {"owner": "owner", "repo": "repo", "body": "done"}}'
            ),
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
                '"arguments": {"owner": "owner", "repo": "repo", "head": "h", "base": "b"}}'
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

    def test_prose_rescued_call_is_still_repo_pinned(self, monkeypatch, tmp_path):
        # The rescue path synthesises tool_calls from prose; those must go
        # through the same repo-pin gate as native tool calls. A rescued
        # call targeting a foreign repo never reaches its implementation.
        dispatched = []
        dispatch = _ok_dispatch()
        dispatch["github__push_files"] = lambda args: dispatched.append(args) or "OK"
        monkeypatch.setattr(
            session,
            "ollama_chat",
            _scripted_chat(
                [
                    _prose_msg(
                        '{"name": "github__push_files", '
                        '"arguments": {"owner": "evil", "repo": "other", "branch": "b", '
                        '"files": [], "message": "m"}}'
                    ),
                    _prose_msg(
                        '{"name": "github__create_pull_request", '
                        '"arguments": {"owner": "owner", "repo": "repo", "head": "h", "base": "b"}}'
                    ),
                    _prose_msg(
                        '{"name": "github__add_issue_comment", '
                        '"arguments": {"owner": "owner", "repo": "repo", "body": "done"}}'
                    ),
                ]
            ),
        )
        monkeypatch.setattr(session, "DISPATCH", dispatch)
        monkeypatch.setattr(session, "attempt_salvage", lambda *a, **kw: None)
        rc = run_session(
            host="http://example",
            model="m",
            recipe_path=_minimal_recipe(tmp_path),
            params={
                "base_branch": "main",
                "repo": "owner/repo",
                "issue_number": "1",
                "branch": "runner/issue-1-20260627-000000",
            },
            max_turns=20,
            salvage_enabled=False,
            loop_detect_threshold=4,
            turn_timeout=10.0,
        )
        assert rc == 0
        assert dispatched == []  # pinned-out call never hit the impl

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


# ---------------------------------------------------------------------------
# run_session — repo pinning at the dispatch seam (#119)
# ---------------------------------------------------------------------------


class TestRunSessionRepoPin:
    """A tool call targeting a repo other than the session's `--params repo`
    must produce an ERROR result without the implementation ever running —
    the pin is enforced in the session loop, upstream of DISPATCH.
    """

    def _runs(self, monkeypatch, tmp_path, scripted, dispatch):
        monkeypatch.setattr(session, "ollama_chat", _scripted_chat(scripted))
        monkeypatch.setattr(session, "DISPATCH", dispatch)
        monkeypatch.setattr(session, "attempt_salvage", lambda *a, **kw: None)
        return run_session(
            host="http://example",
            model="m",
            recipe_path=_minimal_recipe(tmp_path),
            params={
                "base_branch": "main",
                "repo": "owner/repo",
                "issue_number": "1",
                "branch": "runner/issue-1-20260627-000000",
            },
            max_turns=20,
            salvage_enabled=False,
            loop_detect_threshold=4,
            turn_timeout=10.0,
        )

    def test_mismatched_repo_call_never_reaches_impl(self, monkeypatch, tmp_path):
        dispatched = []
        dispatch = _ok_dispatch()
        dispatch["github__push_files"] = lambda args: dispatched.append(args) or "OK"
        scripted = [
            _tool_call_msg(
                "github__push_files",
                {"owner": "evil", "repo": "other", "branch": "b", "files": [], "message": "m"},
            ),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted, dispatch)
        assert rc == 0  # session still completes via the matching calls
        assert dispatched == []

    def test_missing_owner_repo_fails_closed(self, monkeypatch, tmp_path):
        dispatched = []
        dispatch = _ok_dispatch()
        dispatch["github__push_files"] = lambda args: dispatched.append(args) or "OK"
        scripted = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "github__push_files",
                            # no owner/repo at all — must not slip the pin
                            "arguments": {"branch": "b", "files": [], "message": "m"},
                        }
                    }
                ],
            },
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted, dispatch)
        assert rc == 0
        assert dispatched == []


# ---------------------------------------------------------------------------
# run_session AGENTS.md session state — banner line + presence (#107)
# ---------------------------------------------------------------------------


class TestRunSessionAgentsBanner:
    """agents_md rides into run_session as session state (#108's gate will
    consume it); the observable behaviour today is the banner summary line."""

    def _runs(self, monkeypatch, tmp_path, agents_md):
        scripted = [
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        monkeypatch.setattr(session, "ollama_chat", _scripted_chat(scripted))
        monkeypatch.setattr(session, "DISPATCH", _ok_dispatch())
        monkeypatch.setattr(session, "attempt_salvage", lambda *a, **kw: None)
        return run_session(
            host="http://example",
            model="m",
            recipe_path=_minimal_recipe(tmp_path),
            params={
                "base_branch": "main",
                "repo": "owner/repo",
                "issue_number": "1",
                "branch": "runner/issue-1-20260627-000000",
            },
            max_turns=5,
            salvage_enabled=False,
            turn_timeout=10.0,
            agents_md=agents_md,
        )

    def test_banner_line_printed_when_agents_md_present(self, monkeypatch, tmp_path, capsys):
        parsed = ParsedAgentsMd(
            verification_commands=[
                VerificationCommand(name="check", command="make check"),
                VerificationCommand(name="test", command="make test"),
            ],
            conventions=["a", "b"],
        )
        rc = self._runs(monkeypatch, tmp_path, parsed)
        assert rc == 0
        out = capsys.readouterr().out
        assert "AGENTS:         verification=[check, test], 2 conventions" in out

    def test_no_banner_line_without_agents_md(self, monkeypatch, tmp_path, capsys):
        rc = self._runs(monkeypatch, tmp_path, None)
        assert rc == 0
        assert "AGENTS:" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_session post-commit gate wiring (#108)
# ---------------------------------------------------------------------------


class TestRunSessionGateWiring:
    """run_gate itself is covered by test_gate.py against real git repos;
    these tests pin WHEN the session loop invokes it (file-commit tools
    only, successful results only, agents_md + workspace present) and how
    its output/failure surfaces in the log."""

    def _agents(self):
        return ParsedAgentsMd(
            verification_commands=[VerificationCommand(name="check", command="make check")],
            conventions=[],
        )

    def _pass_result(self):
        return GateResult(
            sha="a" * 40,
            results=[
                CommandResult(
                    name="check",
                    command="make check",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    elapsed=0.1,
                )
            ],
            aggregate_status="pass",
        )

    def _runs(
        self,
        monkeypatch,
        tmp_path,
        scripted,
        fake_run_gate,
        agents_md="default",
        dispatch=None,
        params_branch="runner/issue-1-20260627-000000",
    ):
        monkeypatch.setattr(session, "ollama_chat", _scripted_chat(scripted))
        monkeypatch.setattr(session, "DISPATCH", dispatch or _ok_dispatch())
        monkeypatch.setattr(session, "attempt_salvage", lambda *a, **kw: None)
        monkeypatch.setattr(session, "run_gate", fake_run_gate)
        return run_session(
            host="http://example",
            model="m",
            recipe_path=_minimal_recipe(tmp_path),
            params={
                "base_branch": "main",
                "repo": "owner/repo",
                "issue_number": "1",
                "branch": params_branch,
            },
            max_turns=8,
            salvage_enabled=False,
            turn_timeout=10.0,
            workspace_dir=tmp_path,
            agents_md=self._agents() if agents_md == "default" else agents_md,
        )

    def test_gate_runs_after_create_or_update_file(self, monkeypatch, tmp_path, capsys):
        calls = []

        def fake(ws, branch, cmds):
            calls.append((ws, branch, [c.name for c in cmds]))
            return self._pass_result()

        scripted = [
            _tool_call_msg(
                "github__create_or_update_file",
                {"branch": "runner/issue-1-x", "path": "f.py", "content": "c"},
            ),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted, fake)
        assert rc == 0
        # Gated the branch named in the tool call's own args.
        assert calls == [(tmp_path, "runner/issue-1-x", ["check"])]
        out = capsys.readouterr().out
        assert "[gate: make check] PASS" in out
        assert "aggregate: PASS (1/1 passed)" in out

    def test_gate_runs_after_push_files(self, monkeypatch, tmp_path):
        calls = []

        def fake(ws, branch, cmds):
            calls.append(branch)
            return self._pass_result()

        scripted = [
            _tool_call_msg(
                "github__push_files",
                {"branch": "runner/issue-1-x", "files": [], "message": "m"},
            ),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        assert self._runs(monkeypatch, tmp_path, scripted, fake) == 0
        assert calls == ["runner/issue-1-x"]

    def test_gate_skips_non_file_tools(self, monkeypatch, tmp_path):
        calls = []

        def fake(ws, branch, cmds):
            calls.append(branch)
            return self._pass_result()

        scripted = [
            _tool_call_msg("github__issue_read", {"issue_number": 1}),
            _tool_call_msg("github__create_branch", {"branch": "b", "from_branch": "main"}),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        assert self._runs(monkeypatch, tmp_path, scripted, fake) == 0
        assert calls == []

    def test_gate_skipped_without_agents_md(self, monkeypatch, tmp_path):
        calls = []

        def fake(ws, branch, cmds):
            calls.append(branch)
            return self._pass_result()

        scripted = [
            _tool_call_msg("github__create_or_update_file", {"branch": "b", "path": "f"}),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        assert self._runs(monkeypatch, tmp_path, scripted, fake, agents_md=None) == 0
        assert calls == []

    def test_gate_skipped_when_commit_call_fails(self, monkeypatch, tmp_path):
        calls = []

        def fake(ws, branch, cmds):
            calls.append(branch)
            return self._pass_result()

        dispatch = _ok_dispatch()
        dispatch["github__create_or_update_file"] = lambda args: "ERROR: 422 conflict"
        scripted = [
            _tool_call_msg("github__create_or_update_file", {"branch": "b", "path": "f"}),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        assert self._runs(monkeypatch, tmp_path, scripted, fake, dispatch=dispatch) == 0
        assert calls == []

    def test_gate_error_skips_loudly_and_session_continues(self, monkeypatch, tmp_path, capsys):
        def fake(ws, branch, cmds):
            raise GateError("`git fetch origin b` failed: network down")

        scripted = [
            _tool_call_msg("github__create_or_update_file", {"branch": "b", "path": "f"}),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        assert self._runs(monkeypatch, tmp_path, scripted, fake) == 0
        out = capsys.readouterr().out
        assert "[gate] ERROR:" in out
        assert "gate skipped for this commit" in out

    def test_gate_branch_falls_back_to_session_param(self, monkeypatch, tmp_path):
        calls = []

        def fake(ws, branch, cmds):
            calls.append(branch)
            return self._pass_result()

        # Model omitted `branch` in the commit call — the API would default,
        # so the gate falls back to the session's generated branch param.
        scripted = [
            _tool_call_msg("github__create_or_update_file", {"path": "f", "content": "c"}),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        assert self._runs(monkeypatch, tmp_path, scripted, fake) == 0
        assert calls == ["runner/issue-1-20260627-000000"]


# ---------------------------------------------------------------------------
# run_session gate-failure feedback + PR-open block + salvage state (#109)
# ---------------------------------------------------------------------------


def _red_gate(sha="b" * 40):
    return GateResult(
        sha=sha,
        results=[
            CommandResult(
                name="check",
                command="make check",
                exit_code=1,
                stdout="lint exploded",
                stderr="",
                elapsed=1.0,
            )
        ],
        aggregate_status="fail",
    )


def _green_gate(sha="c" * 40):
    return GateResult(
        sha=sha,
        results=[
            CommandResult(
                name="check",
                command="make check",
                exit_code=0,
                stdout="",
                stderr="",
                elapsed=1.0,
            )
        ],
        aggregate_status="pass",
    )


def _capturing_chat(scripted, seen):
    """Like _scripted_chat, but records a snapshot of `messages` per call so
    tests can assert what the model would see on its next turn."""
    queue = list(scripted)

    def fake_chat(client, host, model, messages, tool_schemas, options=None):
        seen.append([dict(m) for m in messages])
        if not queue:
            raise AssertionError("ollama_chat called past end of scripted responses")
        return {"message": queue.pop(0), "done_reason": "stop"}

    return fake_chat


class TestRunSessionGateFeedback:
    def _agents(self):
        return ParsedAgentsMd(
            verification_commands=[VerificationCommand(name="check", command="make check")],
            conventions=[],
        )

    def _commit_msg(self):
        return _tool_call_msg(
            "github__create_or_update_file",
            {"branch": "runner/issue-1-x", "path": "f.py", "content": "c"},
        )

    def _runs(
        self,
        monkeypatch,
        tmp_path,
        scripted,
        gate_results,
        seen=None,
        dispatch=None,
        salvage=None,
        **kwargs,
    ):
        """gate_results: queue of GateResult (or callables/exceptions) that
        successive run_gate calls pop from; repeats the last one when empty."""
        queue = list(gate_results)

        def fake_run_gate(ws, branch, cmds):
            result = queue.pop(0) if len(queue) > 1 else queue[0]
            return result

        chat = _capturing_chat(scripted, seen) if seen is not None else _scripted_chat(scripted)
        monkeypatch.setattr(session, "ollama_chat", chat)
        monkeypatch.setattr(session, "DISPATCH", dispatch or _ok_dispatch())
        monkeypatch.setattr(session, "attempt_salvage", salvage or (lambda *a, **kw: None))
        monkeypatch.setattr(session, "run_gate", fake_run_gate)
        return run_session(
            host="http://example",
            model="m",
            recipe_path=_minimal_recipe(tmp_path),
            params={
                "base_branch": "main",
                "repo": "owner/repo",
                "issue_number": "1",
                "branch": "runner/issue-1-20260627-000000",
            },
            max_turns=kwargs.get("max_turns", 10),
            salvage_enabled=kwargs.get("salvage_enabled", False),
            turn_timeout=10.0,
            loop_detect_threshold=kwargs.get("loop_detect_threshold", 4),
            workspace_dir=tmp_path,
            agents_md=self._agents(),
        )

    def test_red_gate_feeds_failure_back_as_user_message(self, monkeypatch, tmp_path, capsys):
        seen = []
        scripted = [
            self._commit_msg(),
            _prose_msg("done"),
            _prose_msg("done"),
            _prose_msg("done"),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted, [_red_gate()], seen=seen)
        assert rc == 2  # gave up after prose turns; salvage disabled
        # The call after the red-gate turn opens with the failure message
        # as the newest user-role message.
        after_commit = seen[1]
        assert after_commit[-1]["role"] == "user"
        assert "Verification failed after your last commit." in after_commit[-1]["content"]
        assert "[FAIL] make check (exit 1)" in after_commit[-1]["content"]
        assert "lint exploded" in after_commit[-1]["content"]
        assert "[runner: gate red — feeding failure back to the model]" in capsys.readouterr().out

    def test_green_gate_appends_no_feedback(self, monkeypatch, tmp_path, seen=None):
        seen = []
        scripted = [
            self._commit_msg(),
            _tool_call_msg("github__create_pull_request", {}),
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted, [_green_gate()], seen=seen)
        assert rc == 0
        after_commit = seen[1]
        assert after_commit[-1]["role"] == "tool"  # no injected user message

    def test_pr_blocked_while_red_then_allowed_after_green(self, monkeypatch, tmp_path, capsys):
        pr_impl_calls = []
        dispatch = _ok_dispatch()
        dispatch["github__create_pull_request"] = lambda args: pr_impl_calls.append(args) or "OK"
        scripted = [
            self._commit_msg(),  # gate red
            _tool_call_msg("github__create_pull_request", {}),  # blocked
            self._commit_msg(),  # gate green
            _tool_call_msg("github__create_pull_request", {}),  # allowed
            _tool_call_msg("github__add_issue_comment", {}),
        ]
        rc = self._runs(
            monkeypatch, tmp_path, scripted, [_red_gate(), _green_gate()], dispatch=dispatch
        )
        assert rc == 0
        # The blocked call never reached the tool implementation.
        assert len(pr_impl_calls) == 1
        out = capsys.readouterr().out
        assert "[runner: create_pull_request blocked — last gate red]" in out

    def test_prose_nudge_is_failure_message_while_red(self, monkeypatch, tmp_path, seen=None):
        seen = []
        scripted = [
            self._commit_msg(),  # gate red
            _prose_msg("hmm"),  # nudge should be the failure message
            _prose_msg("hmm"),
            _prose_msg("hmm"),
        ]
        rc = self._runs(monkeypatch, tmp_path, scripted, [_red_gate()], seen=seen)
        assert rc == 2
        # Third call = after commit turn + one prose turn: last user message
        # is the failure feedback again (not the step-aware nudge).
        assert "Verification failed after your last commit." in seen[2][-1]["content"]

    def test_stuck_on_same_failing_commit_trips_loop_detect(self, monkeypatch, tmp_path):
        # Identical failing commits: the first grows `succeeded` (set-add),
        # so turns 2+ accumulate the same signature and trip at threshold.
        scripted = [self._commit_msg() for _ in range(6)]
        rc = self._runs(monkeypatch, tmp_path, scripted, [_red_gate()], loop_detect_threshold=4)
        assert rc == 4

    def test_signature_stable_across_reruns_of_same_failure(self):
        import copy

        from prose_rescue import turn_signature

        msg = self._commit_msg()
        assert turn_signature(msg) == turn_signature(copy.deepcopy(msg))

    def test_salvage_receives_gate_state(self, monkeypatch, tmp_path):
        salvage_calls = []

        def fake_salvage(messages, params, succeeded, gate_state=None):
            salvage_calls.append(gate_state)
            return None

        scripted = [
            self._commit_msg(),  # gate red
            _prose_msg("done"),
            _prose_msg("done"),
            _prose_msg("done"),
        ]
        rc = self._runs(
            monkeypatch,
            tmp_path,
            scripted,
            [_red_gate()],
            salvage=fake_salvage,
            salvage_enabled=True,
        )
        assert rc == 2
        assert len(salvage_calls) == 1
        assert salvage_calls[0] is not None
        assert salvage_calls[0][-1].aggregate_status == "fail"
