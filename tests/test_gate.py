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
from gate import (
    CommandResult,
    GateError,
    GateResult,
    format_gate_block,
    format_gate_failure_message,
    format_pr_block_error,
    format_salvage_verification,
    run_gate,
    run_remediation,
)

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
        assert gate.branch == BRANCH
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


class TestFormatGateFailureMessage:
    SHA = "abcdef1234567890abcdef1234567890abcdef12"

    def _mixed_gate(self):
        return GateResult(
            sha=self.SHA,
            results=[
                CommandResult(
                    name="check",
                    command="make check",
                    exit_code=1,
                    stdout="lint failed on runner/gate.py",
                    stderr="",
                    elapsed=2.0,
                ),
                CommandResult(
                    name="test",
                    command="make test",
                    exit_code=2,
                    stdout="",
                    stderr="3 failed, 200 passed",
                    elapsed=30.5,
                ),
                CommandResult(
                    name="typecheck",
                    command="make typecheck",
                    exit_code=0,
                    stdout="quiet-pass-output",
                    stderr="",
                    elapsed=3.1,
                ),
            ],
            aggregate_status="fail",
        )

    def test_multi_failure_message_shape(self):
        msg = format_gate_failure_message(self._mixed_gate())
        assert msg.startswith("Verification failed after your last commit.")
        assert "2 of 3 commands failed." in msg
        # Every failing command gets its own block with output...
        assert "[FAIL] make check (exit 1)" in msg
        assert "lint failed on runner/gate.py" in msg
        assert "[FAIL] make test (exit 2)" in msg
        assert "3 failed, 200 passed" in msg
        # ...passing commands get a one-line summary, output omitted.
        assert "[PASS] make typecheck (3.1s)" in msg
        assert "quiet-pass-output" not in msg
        # The locked intermediate-state hint closes the message.
        assert "If you were planning to land additional commits" in msg
        assert "Do not open the PR until all verification commands" in msg

    def test_single_failure_no_pass_summary(self):
        gate = GateResult(
            sha=self.SHA,
            results=[
                CommandResult(
                    name="check",
                    command="make check",
                    exit_code=1,
                    stdout="boom",
                    stderr="",
                    elapsed=1.0,
                )
            ],
            aggregate_status="fail",
        )
        msg = format_gate_failure_message(gate)
        assert "1 of 1 commands failed." in msg
        assert "[PASS]" not in msg


class TestFormatPrBlockError:
    def test_names_count_and_failed_commands(self):
        gate = GateResult(
            sha="a" * 40,
            results=[
                CommandResult(
                    name="check",
                    command="make check",
                    exit_code=1,
                    stdout="",
                    stderr="",
                    elapsed=1.0,
                ),
                CommandResult(
                    name="test",
                    command="make test",
                    exit_code=1,
                    stdout="",
                    stderr="",
                    elapsed=1.0,
                ),
                CommandResult(
                    name="typecheck",
                    command="make typecheck",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    elapsed=1.0,
                ),
            ],
            aggregate_status="fail",
        )
        err = format_pr_block_error(gate)
        # Must start with ERROR so _tool_result_succeeded stays False.
        assert err.startswith("ERROR: Cannot open PR: verification failing on HEAD.")
        assert "2 of 3 commands failed: check, test." in err
        assert "Fix and re-commit before opening the PR." in err


class TestFormatSalvageVerification:
    def test_no_gate_recorded(self):
        block = format_salvage_verification(None)
        assert "no gate run was recorded" in block
        assert "manually" in block

    def test_gate_results_listed_with_failure_output(self):
        gate = GateResult(
            sha="abcdef1234567890abcdef1234567890abcdef12",
            results=[
                CommandResult(
                    name="check",
                    command="make check",
                    exit_code=0,
                    stdout="quiet",
                    stderr="",
                    elapsed=1.2,
                ),
                CommandResult(
                    name="test",
                    command="make test",
                    exit_code=1,
                    stdout="FAILED test_x",
                    stderr="",
                    elapsed=9.9,
                ),
            ],
            aggregate_status="fail",
        )
        block = format_salvage_verification(gate)
        assert "Salvage skips the gate" in block
        assert "`abcdef12`" in block
        assert "**FAIL**" in block
        assert "- `make check`: PASS (1.2s)" in block
        assert "- `make test`: FAIL (exit 1)" in block
        assert "FAILED test_x" in block
        # Passing command output stays out of the PR body.
        assert "quiet" not in block


class TestRunGateMutatingCommands:
    """eval-37 regression: verification commands that mutate the tree
    (health_track's `make check` runs isort+black before flake8) must not
    wedge the next gate run's checkout."""

    def test_second_run_survives_mutating_command(self, rig):
        # A command that rewrites a tracked file, like a formatter would.
        cmds = [
            VerificationCommand(name="mutate", command="echo reformatted > feature.txt"),
            VerificationCommand(name="check", command="true"),
        ]
        first = run_gate(rig["workspace"], BRANCH, cmds)
        # Since #154 a mutating command is itself a red gate; this test's
        # concern is only that the mutation can't WEDGE the next run.
        assert first.aggregate_status == "fail"
        assert first.results[-1].name == "workspace-mutation"
        # Tree is now dirty — before the fix, this second run raised
        # GateError ("local changes would be overwritten by checkout").
        sha2 = _commit(rig["publisher"], "feature.txt", "v2", "next commit")
        rc, _, err = _git(["push", "origin", BRANCH], rig["publisher"])
        assert rc == 0, err
        second = run_gate(rig["workspace"], BRANCH, cmds)
        assert second.sha == sha2
        assert [r.exit_code for r in second.results[:2]] == [0, 0]

    def test_mutations_discarded_not_carried_into_next_run(self, rig):
        # The reset must discard the mutation so commands run against the
        # actual branch tip, not a half-mutated tree.
        mutate = [VerificationCommand(name="mutate", command="echo dirt > feature.txt")]
        run_gate(rig["workspace"], BRANCH, mutate)
        verify = [
            VerificationCommand(name="content", command="grep -q v1 feature.txt"),
        ]
        gate = run_gate(rig["workspace"], BRANCH, verify)
        assert gate.aggregate_status == "pass"


class TestRunGateMutationDetector:
    """#154, from eval-38's false green: a command that modifies tracked
    files must force a red gate; untracked artifacts are tolerated."""

    def test_tracked_file_mutation_forces_red(self, rig):
        cmds = [
            VerificationCommand(name="format", command="echo fixed > feature.txt"),
            VerificationCommand(name="lint", command="true"),
        ]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "fail"
        synthetic = gate.results[-1]
        assert synthetic.name == "workspace-mutation"
        assert not synthetic.passed
        assert "feature.txt" in synthetic.stdout
        assert "non-mutating" in synthetic.stderr
        # The real commands' results are still all present ahead of it.
        assert [r.name for r in gate.results] == ["format", "lint", "workspace-mutation"]

    def test_untracked_artifacts_tolerated(self, rig):
        cmds = [
            VerificationCommand(name="test", command="touch coverage-artifact.txt"),
            VerificationCommand(name="check", command="true"),
        ]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "pass"
        assert [r.name for r in gate.results] == ["test", "check"]

    def test_clean_commands_add_no_synthetic_result(self, rig):
        cmds = [VerificationCommand(name="check", command="true")]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "pass"
        assert len(gate.results) == 1

    def test_mutation_failure_reads_sensibly_in_feedback(self, rig):
        # The synthetic result flows through the #109 failure formatter.
        cmds = [VerificationCommand(name="format", command="echo fixed > feature.txt")]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        msg = format_gate_failure_message(gate)
        assert "[FAIL] git status --porcelain (runner post-commands check) (exit 1)" in msg
        assert "Re-committing cannot fix" in msg


class TestRunGateHeadMoveDetector:
    """#156 review: a command that moves HEAD (git commit absorbs mutations
    into a clean status; git checkout leaves the gated commit) must force a
    red gate — status alone can't see it."""

    def test_command_committing_mutations_forces_red(self, rig):
        sneaky = (
            "echo laundered > feature.txt && git add -A && "
            "git -c user.email=t@t -c user.name=t commit -qm sneaky"
        )
        cmds = [VerificationCommand(name="sneaky", command=sneaky)]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "fail"
        synthetic = gate.results[-1]
        assert synthetic.name == "head-moved"
        assert "HEAD moved during verification" in synthetic.stdout
        assert gate.sha in synthetic.stdout  # reports the gated sha it left

    def test_command_checking_out_elsewhere_forces_red(self, rig):
        cmds = [VerificationCommand(name="wander", command="git checkout -q main")]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "fail"
        assert gate.results[-1].name == "head-moved"


class TestRunRemediation:
    """ADR-0009 / #157: declared fixes run mechanically after a red gate."""

    def _red_gate_with_fix(self, rig):
        cmds = [
            VerificationCommand(
                name="check",
                command="grep -q formatted feature.txt",
                fix="echo formatted > feature.txt",
            )
        ]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert gate.aggregate_status == "fail"  # v1 content isn't "formatted"
        return gate

    def test_fix_collects_changed_files(self, rig):
        gate = self._red_gate_with_fix(rig)
        rem = run_remediation(rig["workspace"], gate)
        assert rem.fixes_run == ["echo formatted > feature.txt"]
        assert rem.changed_files == {"feature.txt": "formatted\n"}
        assert "1 file(s) changed" in rem.notes

    def test_no_fixes_declared_is_a_noop(self, rig):
        cmds = [VerificationCommand(name="check", command="false")]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        rem = run_remediation(rig["workspace"], gate)
        assert rem.fixes_run == []
        assert rem.changed_files == {}

    def test_fix_changing_nothing_reports_it(self, rig):
        cmds = [VerificationCommand(name="check", command="false", fix="true")]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        rem = run_remediation(rig["workspace"], gate)
        assert rem.fixes_run == ["true"]
        assert rem.changed_files == {}
        assert "changed nothing" in rem.notes

    def test_detector_results_disable_remediation(self, rig):
        # A command that mutates (no fix declared elsewhere matters): the
        # gate carries workspace-mutation, so remediation must refuse.
        cmds = [VerificationCommand(name="mutating", command="echo dirt > feature.txt", fix="true")]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        assert any(r.name == "workspace-mutation" for r in gate.results)
        rem = run_remediation(rig["workspace"], gate)
        assert rem.changed_files == {}
        assert "detector" in rem.notes

    def test_failing_fix_discarded_and_reset(self, rig):
        # The fix mutates the tree but exits non-zero: whatever it half-did
        # is untrustworthy and must not become a remediation commit.
        cmds = [
            VerificationCommand(
                name="check", command="false", fix="echo partial > feature.txt; exit 3"
            )
        ]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        rem = run_remediation(rig["workspace"], gate)
        assert rem.fixes_run == ["echo partial > feature.txt; exit 3"]
        assert rem.changed_files == {}
        assert "exited 3" in rem.notes
        # The partial mutation was rolled back.
        assert (rig["workspace"] / "feature.txt").read_text() == "v1"

    def test_destructive_fix_discarded_and_reset(self, rig):
        cmds = [VerificationCommand(name="check", command="false", fix="rm feature.txt")]
        gate = run_gate(rig["workspace"], BRANCH, cmds)
        rem = run_remediation(rig["workspace"], gate)
        assert rem.changed_files == {}
        assert "non-modification" in rem.notes
        # The destructive fix was rolled back.
        assert (rig["workspace"] / "feature.txt").read_text() == "v1"
