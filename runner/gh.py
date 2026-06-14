"""Shared gh-CLI subprocess helper used by run_recipe.py and salvage.py."""

import subprocess

DEFAULT_TIMEOUT = 120


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
