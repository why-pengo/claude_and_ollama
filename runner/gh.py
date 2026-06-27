"""Shared gh-CLI subprocess helper used by run_recipe.py and salvage.py."""

import subprocess

DEFAULT_TIMEOUT = 120
AUTH_CHECK_TIMEOUT = 30


def _gh(
    args: list[str], stdin: str | None = None, timeout: int = DEFAULT_TIMEOUT
) -> tuple[int, str, str]:
    """Invoke `gh` and return (returncode, stdout, stderr).

    Raises subprocess.TimeoutExpired if gh takes longer than `timeout` seconds.
    Default timeout exists so a hung GitHub API call doesn't hang the session.
    """
    proc = subprocess.run(
        ["gh", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def check_gh_auth(timeout: int = AUTH_CHECK_TIMEOUT) -> tuple[bool, str]:
    """Verify the gh CLI can talk to GitHub via `gh auth status`.

    Returns (True, "") on success, (False, message) on any failure. The
    message includes a hint matched to the failure mode so the caller can
    print it verbatim:
      - missing `gh` binary → install hint
      - the check itself timing out → connectivity hint
      - non-zero exit (stale/revoked token, no auth at all) → gh's own
        stderr plus `gh auth login` hint
    """
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "gh CLI not found on PATH. Install it from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return False, (
            f"gh auth status timed out after {timeout}s. "
            "Check network connectivity to github.com."
        )
    if proc.returncode == 0:
        return True, ""
    msg = (proc.stderr or proc.stdout or "").strip() or f"gh auth status exited {proc.returncode}"
    return False, f"{msg}\nRun 'gh auth login' to authenticate."
