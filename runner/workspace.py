"""Workspace pre-flight + session-end restore for the runner.

The runner expects a user-maintained local checkout of the target repo it can
shell into. This module validates the workspace is in a sane state before any
session work begins, and restores it to `base_branch` at session end so the
next session's pre-flight passes without manual cleanup. Per epic #111 / #106,
the runner doesn't clone, install deps, or otherwise manage the workspace —
that's the user's responsibility.
"""

import re
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 60


class WorkspaceError(Exception):
    """Raised when the workspace pre-flight bails. Message is user-facing."""


def _git(args: list[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    """Invoke `git` in `cwd` and return (returncode, stdout, stderr).

    A timeout (`git fetch` against a slow remote, etc.) is surfaced as a
    non-zero rc plus a synthetic stderr so callers can raise a clean
    WorkspaceError instead of leaking a TimeoutExpired stack trace. rc=124
    matches `timeout(1)`'s convention for command-timed-out.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"`git {' '.join(args)}` timed out after {timeout}s"
    return proc.returncode, proc.stdout, proc.stderr


# Valid git branch names are far more restrictive than this regex (see
# `git check-ref-format`), but the runner only needs to defend against the
# option-injection / whitespace-in-shell-arg cases — branches like `main`,
# `develop`, `feature/foo`, `release-1.0` all pass. If git itself rejects a
# name later, that's a clean non-zero rc with git's own error message.
_SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


def parse_repo_from_origin_url(url: str) -> str | None:
    """Extract `owner/repo` from a git remote URL.

    Handles the common forms `git` writes for GitHub remotes:
    `https://github.com/owner/repo.git`, `git@github.com:owner/repo.git`,
    `ssh://git@github.com/owner/repo`. Returns None if the URL doesn't have
    a parseable trailing `owner/repo` pair.
    """
    url = url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    m = re.search(r"[:/]([^:/\s]+)/([^/\s]+?)$", url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def validate_workspace(workspace_dir: Path, target_repo: str, base_branch: str) -> None:
    """Validate the workspace is ready for a session. Raise WorkspaceError if not.

    Checks (in order, first failure wins):
    1. `base_branch` is shell-safe (no leading hyphen, no whitespace).
    2. Path exists, is a directory, contains `.git`.
    3. `origin` URL points at `target_repo`.
    4. `git status --porcelain` is empty (no modified / staged / untracked).
    5. Current branch is `base_branch`.
    6. After `git fetch origin <base_branch>`, `HEAD == origin/<base_branch>`.
    """
    if not _SAFE_BRANCH_RE.fullmatch(base_branch or ""):
        raise WorkspaceError(
            f"base_branch {base_branch!r} is unsafe to pass to git — expected only "
            "alphanumerics, underscore, dot, slash, hyphen (and no leading hyphen)."
        )
    if not workspace_dir.exists():
        raise WorkspaceError(f"workspace path does not exist: {workspace_dir}")
    if not workspace_dir.is_dir():
        raise WorkspaceError(f"workspace path is not a directory: {workspace_dir}")
    if not (workspace_dir / ".git").exists():
        raise WorkspaceError(f"workspace is not a git repository (no .git in {workspace_dir})")

    rc, out, err = _git(["remote", "get-url", "origin"], workspace_dir)
    if rc != 0:
        raise WorkspaceError(
            f"workspace {workspace_dir} has no 'origin' remote: {err.strip() or out.strip()}"
        )
    origin_url = out.strip()
    origin_repo = parse_repo_from_origin_url(origin_url)
    if origin_repo is None:
        raise WorkspaceError(f"could not parse owner/repo from origin URL: {origin_url}")
    if origin_repo.lower() != target_repo.lower():
        raise WorkspaceError(
            f"workspace origin is {origin_repo} (from {origin_url}); "
            f"runner is targeting {target_repo}"
        )

    rc, out, err = _git(["status", "--porcelain"], workspace_dir)
    if rc != 0:
        raise WorkspaceError(f"`git status` failed in {workspace_dir}: {err.strip()}")
    if out.strip():
        raise WorkspaceError(
            f"workspace {workspace_dir} is dirty — commit, stash, or remove the following "
            f"before starting a session:\n{out.rstrip()}"
        )

    rc, out, err = _git(["rev-parse", "--abbrev-ref", "HEAD"], workspace_dir)
    if rc != 0:
        raise WorkspaceError(f"could not read current branch in {workspace_dir}: {err.strip()}")
    current_branch = out.strip()
    if current_branch != base_branch:
        raise WorkspaceError(
            f"workspace {workspace_dir} is on branch '{current_branch}', "
            f"expected '{base_branch}' — `git checkout {base_branch}` and try again"
        )

    rc, _, err = _git(["fetch", "origin", base_branch], workspace_dir)
    if rc != 0:
        raise WorkspaceError(
            f"`git fetch origin {base_branch}` failed in {workspace_dir}: {err.strip()}"
        )

    rc, out, err = _git(["rev-parse", "HEAD"], workspace_dir)
    if rc != 0:
        raise WorkspaceError(f"could not read HEAD in {workspace_dir}: {err.strip()}")
    head_sha = out.strip()

    rc, out, err = _git(["rev-parse", f"origin/{base_branch}"], workspace_dir)
    if rc != 0:
        raise WorkspaceError(
            f"could not read origin/{base_branch} in {workspace_dir}: {err.strip()}"
        )
    origin_sha = out.strip()

    if head_sha == origin_sha:
        return

    # HEAD and origin/<base_branch> disagree — classify the divergence so the
    # user sees what shape of `git pull` (or reset) they need.
    rc_behind, behind_out, _ = _git(
        ["rev-list", "--count", f"HEAD..origin/{base_branch}"], workspace_dir
    )
    rc_ahead, ahead_out, _ = _git(
        ["rev-list", "--count", f"origin/{base_branch}..HEAD"], workspace_dir
    )
    behind = int(behind_out.strip()) if rc_behind == 0 and behind_out.strip().isdigit() else 0
    ahead = int(ahead_out.strip()) if rc_ahead == 0 and ahead_out.strip().isdigit() else 0
    if behind and ahead:
        summary = f"diverged: {ahead} ahead, {behind} behind"
    elif behind:
        summary = f"behind origin/{base_branch} by {behind} commit(s) — run `git pull`"
    elif ahead:
        summary = f"ahead of origin/{base_branch} by {ahead} commit(s)"
    else:
        summary = f"HEAD ({head_sha[:8]}) != origin/{base_branch} ({origin_sha[:8]})"
    raise WorkspaceError(
        f"workspace {workspace_dir} is not at origin/{base_branch}'s tip — {summary}"
    )


def restore_workspace(workspace_dir: Path, base_branch: str) -> None:
    """Best-effort restore: switch back to `base_branch` if currently elsewhere.

    Idempotent — safe to call when the session never switched branches. Does
    not delete the runner branch (kept for debugging) and does not pull. Any
    failure here is logged but not raised: the session has already run, and
    a failed restore should not mask the run's exit code.
    """
    if not workspace_dir.exists() or not (workspace_dir / ".git").exists():
        return
    rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], workspace_dir)
    if rc != 0:
        print(f"[workspace] restore skipped: could not read current branch in {workspace_dir}")
        return
    current = out.strip()
    if current == base_branch:
        return
    # We're on the session's runner branch. Any local modifications there
    # are gate artifacts (mutating verification commands — see run_gate),
    # never user work: the pre-flight required a clean workspace at session
    # start. Discard them so the checkout back to base_branch can't wedge
    # (eval-37's second symptom).
    rc, _, err = _git(["reset", "--hard"], workspace_dir)
    if rc != 0:
        print(f"[workspace] restore: `git reset --hard` failed in {workspace_dir}: {err.strip()}")
    rc, _, err = _git(["checkout", base_branch], workspace_dir)
    if rc != 0:
        print(
            f"[workspace] restore failed: `git checkout {base_branch}` in {workspace_dir}: "
            f"{err.strip()}"
        )
