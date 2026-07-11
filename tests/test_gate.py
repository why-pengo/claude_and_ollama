"""Tests for runner/gate.py — post-commit verification gate (#108).

run_gate tests use a real bare "remote" plus two clones — a workspace and a
"publisher" standing in for the GitHub-API side of a commit — so the actual
fetch / checkout -B / subprocess path is exercised end to end. Commands are
real shell one-liners (`true`, `exit 3`, `seq`), not mocks.
"""

import subprocess
from pathlib import Path

import pytest
from agents_md import VerificationCommand
from gate import CommandResult, GateError, GateResult, format_gate_block, run_gate

from tools import TOOL_RESULT_SIZE_CAP
from workspace import _git

BRANCH = "runner/issue-1-test"


def _commit(repo: Path, file_name: str, body: str, msg: str) -> str:
    (repo / file_name).write_text(body)
    _git(["add", file_name], repo)
    rc, _, err = _git(["commit", "-m", msg], repo)
    assert rc == 0, err
    rc, out, _ = _git(["rev-parse", "HEAD"], repo)
    return out.strip()


def _clone(bare: Path, dest: Path) -> None:
    subprocess.run(
        ["git", "clone", str(bare), str(dest)],
        check=True,
        capture_output=True,
    )
    _git(["config", "user.email", "gate-test@example.com"], dest)
    _git(["config", "user.name", "gate-test"], dest)


@pytest.fixture()
def rig(tmp_path):
    """Bare remote + workspace clone (on main) + publisher clone.

    The publisher plays the GitHub API's role: it pushes the runner branch
    with a commit the workspace hasn't seen, exactly the state run_gate
    must sync before running commands.
    """
    bare = tmp_path / "why-pengo" / "health_track.git"
    bare.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )

    publisher = tmp_path / "publisher"
    _clone(bare, publisher)
    _git(["checkout", "-b", "main"], publisher)
    _commit(publisher, "README.md", "hello", "init")
    rc, _, err = _git(["push", "origin", "main"], publisher)
    assert rc == 0, err

    workspace = tmp_path / "workspace"
    _clone(bare, workspace)

    _git(["checkout", "-b", BRANCH], publisher)
    sha = _commit(publisher, "feature.txt", "v1", "add feature")
    rc, _, err = _git(["push", "origin", BRANCH], publisher)
    assert rc == 0, err

    return {"publisher": publisher, "workspace": workspace, "sha": sha}


class TestRunGate:
    def test_all_green_aggregate_pass(self, rig):
        cmds = [
            VerificationCommand(name="check", command="true"),
            VerificationCommand(name="test", command="true"),
        ]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "pass"
        assert [r.exit_code for r in gate.results] == [0, 0]
        assert [r.name for r in gate.results] == ["check", "test"]
        assert gate.sha == rig["sha"]
        # The sync materialized the published commit in the workspace.
        assert (rig["workspace"] / "feature.txt").read_text() == "v1"

    def test_all_commands_run_after_early_failure(self, rig):
        # The locked run-all decision: a failing first command must not
        # stop the second from running.
        cmds = [
            VerificationCommand(name="fail", command="exit 1"),
            VerificationCommand(name="after", command="echo still-ran"),
        ]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "fail"
        assert len(gate.results) == 2
        assert not gate.results[0].passed
        assert gate.results[1].passed
        assert gate.results[1].stdout.strip() == "still-ran"

    def test_failure_captures_exit_code_and_both_streams(self, rig):
        cmds = [
            VerificationCommand(name="boom", command="echo out-marker; echo err-marker >&2; exit 3")
        ]
        result = run_gate(rig["workspace"], BRANCH, cmds).results[0]
        assert result.exit_code == 3
        assert not result.passed
        assert "out-marker" in result.stdout
        assert "err-marker" in result.stderr
        assert result.elapsed >= 0

    def test_output_truncated_via_cap(self, rig):
        # ~110KB of stdout must come back capped with the runner's marker.
        cmds = [VerificationCommand(name="big", command="seq 1 20000")]
        result = run_gate(rig["workspace"], BRANCH, cmds).results[0]
        assert "[truncated by runner" in result.stdout
        assert len(result.stdout.encode("utf-8")) < TOOL_RESULT_SIZE_CAP + 200

    def test_second_run_picks_up_new_remote_tip(self, rig):
        # Regression guard for the reason run_gate uses `checkout -B`: a
        # plain checkout would reuse the stale local branch from the first
        # gate run and verify the wrong commit.
        cmds = [VerificationCommand(name="check", command="true")]
        first = run_gate(rig["workspace"], BRANCH, cmds)
        sha2 = _commit(rig["publisher"], "feature.txt", "v2", "amend feature")
        rc, _, err = _git(["push", "origin", BRANCH], rig["publisher"])
        assert rc == 0, err
        second = run_gate(rig["workspace"], BRANCH, cmds)
        assert first.sha == rig["sha"]
        assert second.sha == sha2
        assert (rig["workspace"] / "feature.txt").read_text() == "v2"

    def test_unsafe_branch_name_raises(self, rig):
        with pytest.raises(GateError) as excinfo:
            run_gate(rig["workspace"], "--upload-pack=evil", [])
        assert "unsafe" in str(excinfo.value)

    def test_non_string_branch_raises_gate_error(self, rig):
        # Model tool-call args are untrusted: branch can arrive as a number
        # or null, and that must be a GateError (loud skip), not a TypeError
        # crashing the session loop.
        for bad in (42, None, ["runner/x"]):
            with pytest.raises(GateError) as excinfo:
                run_gate(rig["workspace"], bad, [])
            assert "unsafe" in str(excinfo.value)

    def test_missing_remote_branch_raises(self, rig):
        with pytest.raises(GateError) as excinfo:
            run_gate(rig["workspace"], "no-such-branch", [])
        assert "fetch" in str(excinfo.value)

    def test_empty_command_list_is_a_pass(self, rig):
        gate = run_gate(rig["workspace"], BRANCH, [])
        assert gate.aggregate_status == "pass"
        assert gate.results == []


class TestFormatGateBlock:
    SHA = "abcdef1234567890abcdef1234567890abcdef12"

    def test_pass_and_fail_lines_with_failure_output(self):
        gate = GateResult(
            sha=self.SHA,
            results=[
                CommandResult(
                    name="check",
                    command="make check",
                    exit_code=0,
                    stdout="quiet pass noise",
                    stderr="",
                    elapsed=1.23,
                ),
                CommandResult(
                    name="test",
                    command="make test",
                    exit_code=1,
                    stdout="FAILED tests/test_x.py",
                    stderr="boom",
                    elapsed=12.44,
                ),
            ],
            aggregate_status="fail",
        )
        block = format_gate_block(gate)
        assert "[gate: make check] PASS (1.2s)" in block
        assert "[gate: make test] FAIL (12.4s, exit 1)" in block
        # Failing command's output is indented beneath its line...
        assert "  FAILED tests/test_x.py" in block
        assert "  boom" in block
        # ...but a passing command's output is not dumped into the log.
        assert "quiet pass noise" not in block
        assert "[gate @ abcdef12] aggregate: FAIL (1/2 passed)" in block

    def test_all_green_block(self):
        gate = GateResult(
            sha=self.SHA,
            results=[
                CommandResult(
                    name="check",
                    command="make check",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    elapsed=0.51,
                ),
            ],
            aggregate_status="pass",
        )
        block = format_gate_block(gate)
        assert "[gate: make check] PASS (0.5s)" in block
        assert "[gate @ abcdef12] aggregate: PASS (1/1 passed)" in block
