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

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class GateResult:
    sha: str  # the branch tip the commands ran against
    results: list[CommandResult]
    aggregate_status: str  # "pass" if every command exited 0, else "fail"


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
            )
        )
    aggregate = "pass" if all(r.passed for r in results) else "fail"
    return GateResult(sha=sha, results=results, aggregate_status=aggregate)


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
