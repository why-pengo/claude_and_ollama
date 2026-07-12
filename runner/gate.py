"""Post-commit verification gate (#108).

After every successful file-commit tool call (`github__create_or_update_file`
or `github__push_files`), the session loop syncs the runner branch's remote
tip into the local workspace and runs every verification command parsed from
the target repo's AGENTS.md (#107). Results accumulate on the session's
`gate_state` for #109's feedback loop; today the observable surface is the
per-command block in session.log.

Run-all semantics (locked decision on #108): every command runs on every
gate invocation, even after an earlier one fails — the model gets the
complete failure picture in one cycle instead of thrashing through
fix-rerun-fix-rerun. No per-command timeout: verification commands are the
target repo's own `make` targets, and per-target timeouts are explicitly
out of the epic's scope.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from agents_md import VerificationCommand

from tools import _cap
from workspace import _SAFE_BRANCH_RE, _git


class GateError(Exception):
    """Workspace sync failed — the gate could not run at all.

    Distinct from a red gate: a red gate is verification honestly failing
    on the model's commit; GateError is an environment problem (fetch or
    checkout broke). Callers skip the gate loudly rather than recording a
    failure the model's code didn't cause.
    """


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: str
    exit_code: int
    stdout: str  # _cap-truncated, safe to feed back to the model (#109)
    stderr: str  # _cap-truncated
    elapsed: float
    # Declared mechanical remediation for this command (ADR-0009), copied
    # from the AGENTS.md entry. None on synthetic detector results.
    fix: str | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class GateResult:
    sha: str  # the branch tip the commands ran against
    results: list[CommandResult]
    aggregate_status: str  # "pass" if every command exited 0, else "fail"
    # Which branch was gated. The PR-open block keys on this so a green
    # gate on an unrelated branch can't launder a red one (#109 review).
    # Default "" only for pre-#109 constructions; run_gate always sets it.
    branch: str = ""


def run_gate(
    workspace_dir: Path, branch: str, verification_commands: list[VerificationCommand]
) -> GateResult:
    """Sync `branch`'s remote tip into the workspace, run every command.

    The model commits via the GitHub API, so the workspace only learns about
    the new tip through `git fetch`. `checkout -B <branch> origin/<branch>`
    (rather than a plain checkout) forces the local branch to that tip — a
    plain checkout would silently reuse the stale local branch left behind
    by the previous gate run and verify the wrong commit.
    """
    # isinstance first: branch arrives from untrusted model tool-call args,
    # and fullmatch() on a non-string raises TypeError — which the session
    # loop doesn't catch. Everything unsafe must exit as GateError.
    if not isinstance(branch, str) or not _SAFE_BRANCH_RE.fullmatch(branch):
        raise GateError(f"branch {branch!r} is unsafe to pass to git — gate cannot run")
    # Discard local modifications before syncing. Verification commands can
    # mutate the tree (health_track's `make check` runs isort+black before
    # flake8), and a dirty tree wedges the checkout below — eval-37 lost its
    # gate from the second commit onward this way. Anything discarded here
    # is a gate artifact by construction: the pre-flight guaranteed a clean
    # workspace at session start, and the runner branch only ever receives
    # commits through the GitHub API.
    rc, _, err = _git(["reset", "--hard"], workspace_dir)
    if rc != 0:
        raise GateError(f"`git reset --hard` failed: {err.strip()}")
    rc, _, err = _git(["fetch", "origin", branch], workspace_dir)
    if rc != 0:
        raise GateError(f"`git fetch origin {branch}` failed: {err.strip()}")
    rc, _, err = _git(["checkout", "-B", branch, f"origin/{branch}"], workspace_dir)
    if rc != 0:
        raise GateError(f"`git checkout -B {branch} origin/{branch}` failed: {err.strip()}")
    rc, out, err = _git(["rev-parse", "HEAD"], workspace_dir)
    if rc != 0:
        raise GateError(f"could not read HEAD after checkout: {err.strip()}")
    sha = out.strip()

    results: list[CommandResult] = []
    for vc in verification_commands:
        start = time.monotonic()
        proc = subprocess.run(
            vc.command,
            shell=True,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
        )
        results.append(
            CommandResult(
                name=vc.name,
                command=vc.command,
                exit_code=proc.returncode,
                stdout=_cap(proc.stdout),
                stderr=_cap(proc.stderr),
                elapsed=time.monotonic() - start,
                fix=vc.fix,
            )
        )
    # Mutation detector (#154): a command that modifies tracked files makes
    # the whole run untrustworthy — a formatter can "fix" the tree before
    # later checks run, passing locally while the committed code stays
    # broken (eval-38's false green on health_track's mutating `make
    # check`). Untracked artifacts (.coverage, __pycache__, build output)
    # are tolerated here: they don't alter what the checks checked, and the
    # pre-run reset doesn't remove them either. Non-gitignored ones will
    # surface at the NEXT session's workspace pre-flight (which requires a
    # fully clean tree) — that's the right layer: the user decides whether
    # to gitignore or remove them; the gate must not delete user-visible
    # files.
    rc, out, err = _git(["status", "--porcelain", "--untracked-files=no"], workspace_dir)
    if rc != 0:
        raise GateError(f"`git status` failed after verification commands: {err.strip()}")
    mutated = [line for line in out.splitlines() if line.strip()]
    if mutated:
        results.append(
            CommandResult(
                name="workspace-mutation",
                command="git status --porcelain (runner post-commands check)",
                exit_code=1,
                stdout=_cap("\n".join(mutated)),
                stderr=_cap(
                    "Verification commands modified tracked files, so the results "
                    "above may not reflect the committed code (e.g. a formatter "
                    "fixed the tree before lint ran). Re-committing cannot fix "
                    "this: the target repo's AGENTS.md must list non-mutating "
                    "commands (isort --check-only, black --check, ...) — see the "
                    "schema's coverage-horizon guidance."
                ),
                elapsed=0.0,
            )
        )
    # A command can also mutate git state itself (`git commit` absorbs the
    # tree changes above into a clean status; `git checkout` moves away
    # from the gated commit). Either way the results no longer describe
    # the commit being gated, and GateResult.sha would lie.
    rc, out, err = _git(["rev-parse", "HEAD"], workspace_dir)
    if rc != 0:
        raise GateError(f"could not re-read HEAD after verification commands: {err.strip()}")
    head_after = out.strip()
    if head_after != sha:
        results.append(
            CommandResult(
                name="head-moved",
                command="git rev-parse HEAD (runner post-commands check)",
                exit_code=1,
                stdout=f"HEAD moved during verification: {sha} -> {head_after}",
                stderr=_cap(
                    "A verification command moved HEAD (e.g. ran git commit or "
                    "git checkout), so the results above may not describe the "
                    "gated commit. Verification commands must not change git "
                    "state — fix the target repo's AGENTS.md command list."
                ),
                elapsed=0.0,
            )
        )
    aggregate = "pass" if all(r.passed for r in results) else "fail"
    return GateResult(sha=sha, results=results, aggregate_status=aggregate, branch=branch)


@dataclass(frozen=True)
class RemediationResult:
    """Outcome of running declared fix commands after a red gate (ADR-0009)."""

    fixes_run: list[str]  # unique fix commands executed, in order
    changed_files: dict[str, str]  # path -> new content, tracked modifications only
    notes: str  # human-readable trail for session.log


def run_remediation(workspace_dir: Path, gate: GateResult) -> RemediationResult:
    """Run the declared `fix` of every failed command, collect what changed.

    Mechanical only (ADR-0009): the caller commits `changed_files` through
    the GitHub API path and re-runs the gate exactly once. Fixes never run
    when the gate carries a synthetic detector result (workspace-mutation /
    head-moved) — those mean the target's command list is misconfigured and
    remediation on top of an untrustworthy tree would launder it.

    Only modified tracked files (` M` porcelain status) are collected; a
    fix that deletes or renames files is not mechanical remediation and
    falls back to model feedback with a note.
    """
    if any(r.name in ("workspace-mutation", "head-moved") for r in gate.results):
        return RemediationResult(
            fixes_run=[],
            changed_files={},
            notes="skipped: gate carries a detector result — fix the AGENTS.md command list first",
        )
    fixes: list[str] = []
    for r in gate.results:
        if not r.passed and r.fix and r.fix not in fixes:
            fixes.append(r.fix)
    if not fixes:
        return RemediationResult(fixes_run=[], changed_files={}, notes="no fixes declared")

    for fix in fixes:
        subprocess.run(fix, shell=True, cwd=workspace_dir, capture_output=True, text=True)

    rc, out, err = _git(["status", "--porcelain", "--untracked-files=no"], workspace_dir)
    if rc != 0:
        raise GateError(f"`git status` failed after remediation: {err.strip()}")
    modified: list[str] = []
    other: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status, path = line[:2], line[3:].strip()
        if status.strip() == "M":
            modified.append(path)
        else:
            other.append(line.strip())
    if other:
        # Not mechanical — discard and let the model hear the failure.
        _git(["reset", "--hard"], workspace_dir)
        return RemediationResult(
            fixes_run=fixes,
            changed_files={},
            notes=f"skipped: fix produced non-modification changes ({', '.join(other)})",
        )
    changed = {path: (workspace_dir / path).read_text() for path in modified}
    notes = (
        f"{len(changed)} file(s) changed by {', '.join(fixes)}"
        if changed
        else "fix commands changed nothing"
    )
    return RemediationResult(fixes_run=fixes, changed_files=changed, notes=notes)


# Closing hint of the failure-feed-back message (locked decision on #109):
# gives the model permission to ignore intermediate-state failures when it
# intended further commits (e.g. test_x.py landed before x.py), without
# licensing it to ignore real failures.
GATE_FEEDBACK_HINT = (
    "If you were planning to land additional commits before this state is verified,\n"
    "continue with the next commit — the gate will re-run after each. Otherwise fix\n"
    "the failures and re-commit. Do not open the PR until all verification commands\n"
    "pass."
)


def format_gate_failure_message(gate: GateResult) -> str:
    """The user-role message fed back to the model after a red gate (#109).

    Reports every failed command with its truncated output (mirroring the
    gate's run-all semantics — the model sees the complete failure picture
    in one cycle), a one-line summary per passing command, and the
    intermediate-state hint.
    """
    failed = [r for r in gate.results if not r.passed]
    passed = [r for r in gate.results if r.passed]
    lines = [
        "Verification failed after your last commit.",
        "",
        f"{len(failed)} of {len(gate.results)} commands failed.",
        "",
    ]
    for r in failed:
        lines.append(f"[FAIL] {r.command} (exit {r.exit_code})")
        for stream in (r.stdout, r.stderr):
            if stream.strip():
                lines.append(stream.rstrip())
        lines.append("")
    for r in passed:
        lines.append(f"[PASS] {r.command} ({r.elapsed:.1f}s)")
    if passed:
        lines.append("")
    lines.append(GATE_FEEDBACK_HINT)
    return "\n".join(lines)


def format_pr_block_error(gate: GateResult) -> str:
    """Tool-result error for a create_pull_request call blocked on a red gate.

    Starts with "ERROR" so `_tool_result_succeeded` is False — a blocked PR
    call must never count toward `recipe_done`.
    """
    failed = [r.name for r in gate.results if not r.passed]
    return (
        "ERROR: Cannot open PR: verification failing on HEAD. "
        f"{len(failed)} of {len(gate.results)} commands failed: {', '.join(failed)}. "
        "Fix and re-commit before opening the PR."
    )


def format_salvage_verification(gate: GateResult | None) -> str:
    """Body of the salvaged PR's `## Verification` block (#109).

    Salvage skips the gate (running it twice defeats the emergency-path
    purpose), so this reports the last recorded gate run — per-command
    pass/fail with truncated failure output — and says so plainly. With no
    gate run recorded, the reviewer is told verification never happened.
    """
    if gate is None:
        return (
            "Not executed by the model, and no gate run was recorded this "
            "session. Reviewer should run the issue's acceptance criteria "
            "manually before merging."
        )
    lines = [
        f"Salvage skips the gate. Last recorded gate run (at `{gate.sha[:8]}`): "
        f"**{gate.aggregate_status.upper()}** — results may predate the branch tip.",
        "",
    ]
    for r in gate.results:
        if r.passed:
            lines.append(f"- `{r.command}`: PASS ({r.elapsed:.1f}s)")
        else:
            lines.append(f"- `{r.command}`: FAIL (exit {r.exit_code})")
            output = "\n".join(s.rstrip() for s in (r.stdout, r.stderr) if s.strip())
            if output:
                lines.append("  ```")
                lines.extend(f"  {out_line}" for out_line in output.splitlines())
                lines.append("  ```")
    return "\n".join(lines)


def format_gate_block(gate: GateResult) -> str:
    """Render a gate run for session.log, mirroring the turn-metric style.

    One line per command; each failing command's truncated stdout/stderr
    indented beneath it; a trailer line with the gated SHA and aggregate.
    """
    lines: list[str] = []
    for r in gate.results:
        if r.passed:
            lines.append(f"[gate: {r.command}] PASS ({r.elapsed:.1f}s)")
        else:
            lines.append(f"[gate: {r.command}] FAIL ({r.elapsed:.1f}s, exit {r.exit_code})")
            for stream in (r.stdout, r.stderr):
                if stream.strip():
                    lines.extend(f"  {out_line}" for out_line in stream.rstrip().splitlines())
    passed = sum(1 for r in gate.results if r.passed)
    lines.append(
        f"[gate @ {gate.sha[:8]}] aggregate: {gate.aggregate_status.upper()} "
        f"({passed}/{len(gate.results)} passed)"
    )
    return "\n".join(lines)
