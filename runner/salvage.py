"""
Salvage mechanism for the direct-Ollama runner.

When the model commits all the work but exits before calling
`create_pull_request`, this module opens the PR from the branch
mechanically. eval-20 + eval-21 showed this is 5-of-6 of the runner's
failure mode — commits land, the PR call doesn't. Salvage converts
those into review-able artifacts instead of dead branches.

The salvaged PR body marks itself as mechanical so a reviewer knows
the verification work was not done by the model.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from gh import _gh


def _q(value: str) -> str:
    """URL-encode a value that may contain `/` (e.g. branch names like goose/issue-N-slug)."""
    return quote(value, safe="")


def _branch_exists(repo: str, branch: str) -> bool:
    rc, _, _ = _gh(["api", f"repos/{repo}/branches/{_q(branch)}"])
    return rc == 0


def _branch_commits(repo: str, branch: str, base_branch: str) -> list[str]:
    """Commit subjects on `branch` not on `base_branch`, oldest-first."""
    rc, out, _ = _gh(
        [
            "api",
            f"repos/{repo}/compare/{_q(base_branch)}...{_q(branch)}",
            "--jq",
            '[.commits[].commit.message] | map(split("\\n")[0])',
        ]
    )
    if rc != 0 or not out.strip():
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []


def _open_pr_for_branch(repo: str, branch: str) -> int | None:
    owner = repo.split("/")[0]
    rc, out, _ = _gh(
        [
            "api",
            f"repos/{repo}/pulls?state=open&head={_q(owner)}:{_q(branch)}",
            "--jq",
            ".[0].number // empty",
        ]
    )
    if rc != 0 or not out.strip():
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def salvage_pr(
    repo: str,
    branch: str,
    base_branch: str,
    issue_number: int,
    issue_title: str,
) -> dict:
    """
    Open a mechanical PR from a branch with commits but no PR.

    Always returns a dict with `status`. Caller can branch on it.

    Statuses:
      - "opened"      → PR was opened. Includes pr_number, pr_url, commit_count.
      - "no_branch"   → branch doesn't exist on the remote.
      - "no_commits"  → branch exists but has no commits ahead of base.
      - "pr_exists"   → an open PR already exists for this branch.
      - "error"       → the create-PR API call failed. Includes `error`.
    """
    if not _branch_exists(repo, branch):
        return {"status": "no_branch"}

    existing = _open_pr_for_branch(repo, branch)
    if existing is not None:
        return {"status": "pr_exists", "pr_number": existing}

    commits = _branch_commits(repo, branch, base_branch)
    if not commits:
        return {"status": "no_commits"}

    commit_lines = "\n".join(f"- {c}" for c in commits)
    body = (
        f"Closes #{issue_number}\n\n"
        f"## Summary\n"
        f"Mechanical PR opened by the runner's salvage step. The model "
        f"committed the implementation work on `{branch}` but exited "
        f"before calling `github__create_pull_request`. This PR was "
        f"opened from the branch so the work isn't lost.\n\n"
        f"## Commits on this branch\n"
        f"{commit_lines}\n\n"
        f"## Verification\n"
        f"Not executed by the model. Reviewer should run the issue's "
        f"acceptance criteria manually before merging.\n\n"
        f"## Subtasks\n"
        f"Mirror from issue #{issue_number}. None auto-ticked — verify "
        f"each before merging.\n\n"
        f"---\n"
        f"Salvaged by `runner/salvage.py`. Model never called "
        f"`github__create_pull_request` this session."
    )

    payload = json.dumps(
        {
            "title": issue_title,
            "body": body,
            "head": branch,
            "base": base_branch,
        }
    )
    rc, out, err = _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{repo}/pulls",
            "--input",
            "-",
            "--jq",
            "{number, url: .html_url}",
        ],
        stdin=payload,
    )
    if rc != 0:
        return {"status": "error", "error": err.strip()}

    try:
        pr = json.loads(out)
    except json.JSONDecodeError as e:
        return {"status": "error", "error": f"could not parse PR response: {e}"}

    return {
        "status": "opened",
        "pr_number": pr["number"],
        "pr_url": pr["url"],
        "commit_count": len(commits),
    }


def salvage_comment(repo: str, issue_number: int, pr_url: str) -> str | None:
    """Post the Step 6 equivalent — a comment linking the salvaged PR."""
    body = (
        f"⚠️ partial — salvaged PR: {pr_url}\n\n"
        f"The runner opened this PR mechanically after the model "
        f"committed all work but exited without calling "
        f"`create_pull_request`. Reviewer should verify acceptance "
        f"criteria before merging."
    )
    payload = json.dumps({"body": body})
    rc, out, _ = _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{repo}/issues/{issue_number}/comments",
            "--input",
            "-",
            "--jq",
            ".html_url",
        ],
        stdin=payload,
    )
    if rc != 0 or not out.strip():
        return None
    return out.strip()
