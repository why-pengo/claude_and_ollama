#!/usr/bin/env python3
"""
Direct-Ollama recipe runner — executor for the claude_and_ollama harness.

Owns the session loop: calls Ollama directly via the OpenAI-compat endpoint
and prompts the model to continue when it emits no tool call. Implements
7 GitHub tools as wrappers around the `gh` CLI.

The runner replaced an earlier Goose-based executor whose session loop
exited-0 silently on any prose-only turn — that's the reliability ceiling
the eval-17/eval-19/eval-20 series traced and that this runner removes.

Usage:
    python runner/run_recipe.py \\
        --recipe recipes/execute-issue.yaml \\
        --params issue_number=51 \\
        --params repo=why-pengo/health_track

Env required:
    GITHUB_PERSONAL_ACCESS_TOKEN (used by `gh` CLI)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx
import yaml

from gh import _gh
from salvage import salvage_comment, salvage_pr

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "system-prompt.md"

# These match what Goose's github MCP exposes today, by name.
# Argument shapes match what the model has seen across eval-14 etc.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "github__issue_read",
            "description": "Read a GitHub issue by number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "issue_number": {"type": "integer"},
                },
                "required": ["owner", "repo", "issue_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__get_file_contents",
            "description": "Fetch a file's contents from a GitHub repo. Returns 404 if missing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "path": {"type": "string"},
                    "ref": {
                        "type": "string",
                        "description": "Optional branch or commit. Defaults to the repo's default branch.",
                    },
                },
                "required": ["owner", "repo", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__create_branch",
            "description": "Create a new branch from an existing one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "branch": {"type": "string"},
                    "from_branch": {"type": "string"},
                },
                "required": ["owner", "repo", "branch", "from_branch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__create_or_update_file",
            "description": "Create or update a single file on a branch with one commit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "branch": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["owner", "repo", "branch", "path", "content", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__push_files",
            "description": "Push multiple files in a single commit on a branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "branch": {"type": "string"},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                    },
                    "message": {"type": "string"},
                },
                "required": ["owner", "repo", "branch", "files", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__create_pull_request",
            "description": "Open a pull request. Returns the new PR's number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "head": {"type": "string", "description": "Source branch."},
                    "base": {"type": "string", "description": "Target branch."},
                },
                "required": ["owner", "repo", "title", "body", "head", "base"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__add_issue_comment",
            "description": "Post a comment on a GitHub issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "issue_number": {"type": "integer"},
                    "body": {"type": "string"},
                },
                "required": ["owner", "repo", "issue_number", "body"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations — thin wrappers around `gh` CLI
# ---------------------------------------------------------------------------

# Maximum on-wire byte size of a tool result before truncation. Tool results
# get appended to `messages` and re-sent to Ollama on every subsequent turn,
# so an unbounded 100KB lockfile fetch on turn 3 keeps costing context for
# the rest of the session. 16KB covers most legitimate source files;
# pathological cases get truncated with a size hint so the model knows the
# read was partial. The cap is a soft target — the appended marker adds
# ~60 bytes on the truncation path.
TOOL_RESULT_SIZE_CAP = 16384


def _cap(content: str) -> str:
    """Truncate tool-result content to TOOL_RESULT_SIZE_CAP UTF-8 bytes.

    Operates on encoded bytes (not str codepoints), so multi-byte characters
    don't blow past the cap on the wire. errors="ignore" on the decode trims
    any partial multi-byte sequence the slice landed inside, preventing
    invalid UTF-8 in the returned string.
    """
    encoded = content.encode("utf-8")
    if len(encoded) <= TOOL_RESULT_SIZE_CAP:
        return content
    truncated = encoded[:TOOL_RESULT_SIZE_CAP].decode("utf-8", errors="ignore")
    return truncated + (f"\n\n... [truncated by runner; full content was {len(encoded)} bytes]")


def github_issue_read(args: dict) -> str:
    rc, out, err = _gh(
        [
            "api",
            f"repos/{args['owner']}/{args['repo']}/issues/{args['issue_number']}",
            "--jq",
            "{number, title, body, state, labels: [.labels[].name]}",
        ]
    )
    return out if rc == 0 else f"ERROR: {err.strip()}"


def github_get_file_contents(args: dict) -> str:
    ref = args.get("ref")
    path = f"repos/{args['owner']}/{args['repo']}/contents/{args['path']}"
    if ref:
        path += f"?ref={ref}"
    rc, out, err = _gh(["api", path, "--jq", ".content"])
    if rc != 0:
        # Distinguish 404 (file genuinely missing) from real failures so the
        # model can apply the recipe's "404 = skip" rule for AGENTS.md etc.
        if "Not Found" in err or "(HTTP 404)" in err:
            return f"NOT_FOUND: {args['path']}"
        return f"ERROR: {err.strip()}"
    # GitHub returns base64-encoded content; decode to text.
    import base64

    try:
        decoded = base64.b64decode(out.strip().replace('"', "")).decode("utf-8")
        return _cap(decoded)
    except Exception as e:
        return f"ERROR decoding content: {e}"


def github_create_branch(args: dict) -> str:
    # Get the SHA of the from_branch's HEAD
    rc, out, err = _gh(
        [
            "api",
            f"repos/{args['owner']}/{args['repo']}/git/refs/heads/{args['from_branch']}",
            "--jq",
            ".object.sha",
        ]
    )
    if rc != 0:
        return f"ERROR resolving from_branch: {err.strip()}"
    sha = out.strip()

    payload = json.dumps(
        {
            "ref": f"refs/heads/{args['branch']}",
            "sha": sha,
        }
    )
    rc, out, err = _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{args['owner']}/{args['repo']}/git/refs",
            "--input",
            "-",
        ],
        stdin=payload,
    )
    if rc != 0:
        return f"ERROR creating branch: {err.strip()}"
    return f"Created branch {args['branch']} from {args['from_branch']} at {sha[:7]}"


def github_create_or_update_file(args: dict) -> str:
    import base64

    content_b64 = base64.b64encode(args["content"].encode("utf-8")).decode("ascii")
    # Check if the file exists to get its SHA (required for updates)
    rc, out, _ = _gh(
        [
            "api",
            f"repos/{args['owner']}/{args['repo']}/contents/{args['path']}?ref={args['branch']}",
            "--jq",
            ".sha",
        ]
    )
    payload = {
        "message": args["message"],
        "content": content_b64,
        "branch": args["branch"],
    }
    if rc == 0 and out.strip():
        payload["sha"] = out.strip().replace('"', "")
    rc, out, err = _gh(
        [
            "api",
            "-X",
            "PUT",
            f"repos/{args['owner']}/{args['repo']}/contents/{args['path']}",
            "--input",
            "-",
        ],
        stdin=json.dumps(payload),
    )
    if rc != 0:
        return f"ERROR pushing file: {err.strip()}"
    return f"Pushed {args['path']} to {args['branch']}"


def github_push_files(args: dict) -> str:
    """Multi-file commit. Builds a tree + commit + ref update via git data API."""
    owner, repo, branch = args["owner"], args["repo"], args["branch"]

    rc, out, err = _gh(
        [
            "api",
            f"repos/{owner}/{repo}/git/refs/heads/{branch}",
            "--jq",
            ".object.sha",
        ]
    )
    if rc != 0:
        return f"ERROR resolving branch HEAD: {err.strip()}"
    parent_sha = out.strip()

    rc, out, err = _gh(
        [
            "api",
            f"repos/{owner}/{repo}/git/commits/{parent_sha}",
            "--jq",
            ".tree.sha",
        ]
    )
    if rc != 0:
        return f"ERROR resolving parent tree: {err.strip()}"
    base_tree = out.strip()

    tree_entries = []
    for f in args["files"]:
        blob_payload = json.dumps(
            {
                "content": f["content"],
                "encoding": "utf-8",
            }
        )
        rc, out, err = _gh(
            [
                "api",
                "-X",
                "POST",
                f"repos/{owner}/{repo}/git/blobs",
                "--input",
                "-",
                "--jq",
                ".sha",
            ],
            stdin=blob_payload,
        )
        if rc != 0:
            return f"ERROR creating blob for {f['path']}: {err.strip()}"
        blob_sha = out.strip()
        tree_entries.append(
            {
                "path": f["path"],
                "mode": "100644",
                "type": "blob",
                "sha": blob_sha,
            }
        )

    tree_payload = json.dumps(
        {
            "base_tree": base_tree,
            "tree": tree_entries,
        }
    )
    rc, out, err = _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{owner}/{repo}/git/trees",
            "--input",
            "-",
            "--jq",
            ".sha",
        ],
        stdin=tree_payload,
    )
    if rc != 0:
        return f"ERROR creating tree: {err.strip()}"
    new_tree = out.strip()

    commit_payload = json.dumps(
        {
            "message": args["message"],
            "tree": new_tree,
            "parents": [parent_sha],
        }
    )
    rc, out, err = _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{owner}/{repo}/git/commits",
            "--input",
            "-",
            "--jq",
            ".sha",
        ],
        stdin=commit_payload,
    )
    if rc != 0:
        return f"ERROR creating commit: {err.strip()}"
    new_commit = out.strip()

    ref_payload = json.dumps({"sha": new_commit})
    rc, _, err = _gh(
        [
            "api",
            "-X",
            "PATCH",
            f"repos/{owner}/{repo}/git/refs/heads/{branch}",
            "--input",
            "-",
        ],
        stdin=ref_payload,
    )
    if rc != 0:
        return f"ERROR updating ref: {err.strip()}"
    return f"Pushed {len(args['files'])} files to {branch} as commit {new_commit[:7]}"


def github_create_pull_request(args: dict) -> str:
    payload = json.dumps(
        {
            "title": args["title"],
            "body": args["body"],
            "head": args["head"],
            "base": args["base"],
        }
    )
    rc, out, err = _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{args['owner']}/{args['repo']}/pulls",
            "--input",
            "-",
            "--jq",
            "{number, url: .html_url}",
        ],
        stdin=payload,
    )
    if rc != 0:
        return f"ERROR opening PR: {err.strip()}"
    return out.strip()


def github_add_issue_comment(args: dict) -> str:
    payload = json.dumps({"body": args["body"]})
    rc, out, err = _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{args['owner']}/{args['repo']}/issues/{args['issue_number']}/comments",
            "--input",
            "-",
            "--jq",
            ".html_url",
        ],
        stdin=payload,
    )
    if rc != 0:
        return f"ERROR adding comment: {err.strip()}"
    return out.strip()


DISPATCH = {
    "github__issue_read": github_issue_read,
    "github__get_file_contents": github_get_file_contents,
    "github__create_branch": github_create_branch,
    "github__create_or_update_file": github_create_or_update_file,
    "github__push_files": github_push_files,
    "github__create_pull_request": github_create_pull_request,
    "github__add_issue_comment": github_add_issue_comment,
}


# ---------------------------------------------------------------------------
# Ollama client + session loop
# ---------------------------------------------------------------------------


def ollama_chat(host: str, model: str, messages: list, tools: list) -> dict:
    url = f"{host.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
    }
    with httpx.Client(timeout=600.0) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


def template_recipe(prompt: str, params: dict) -> str:
    """Replace {{ key }} placeholders with parameter values."""

    def sub(m):
        key = m.group(1).strip()
        if key not in params:
            raise KeyError(
                f"Recipe references {{{{ {key} }}}} but no --params {key}=... was passed"
            )
        return str(params[key])

    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", sub, prompt)


def load_recipe(path: Path, params: dict) -> tuple[str, str]:
    """Returns (templated_prompt, recipe_title).

    Mutates `params` to apply the recipe's declared parameter defaults for any
    key not explicitly passed — so a recipe author marking a parameter as
    optional-with-default works as advertised.
    """
    data = yaml.safe_load(path.read_text())
    title = data.get("title", "Recipe")
    raw_prompt = data["prompt"]

    for p in data.get("parameters") or []:
        key = p.get("key")
        default = p.get("default")
        if key and key not in params and default is not None:
            params[key] = default

    return template_recipe(raw_prompt, params), title


FILE_WRITE_TOOLS = {"github__push_files", "github__create_or_update_file"}


def tools_succeeded(messages: list) -> set:
    """Tool names where at least one call returned a non-ERROR result.

    Pairs each assistant tool_call with its matching tool result (by
    tool_call_id) and only counts the name if the result doesn't start
    with the "ERROR" prefix the wrappers use. This is the right signal
    for recipe completion and step-phase tracking — calling
    create_pull_request and getting a 422 back is not the same as
    actually opening a PR.
    """
    succeeded = set()
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            name = tc["function"]["name"]
            tc_id = tc.get("id")
            for follow in messages[i + 1 :]:
                if follow.get("role") != "tool":
                    continue
                if follow.get("tool_call_id") != tc_id:
                    continue
                content = follow.get("content") or ""
                if not content.startswith("ERROR"):
                    succeeded.add(name)
                break
    return succeeded


def recipe_done(messages: list) -> bool:
    """True if create_pull_request AND add_issue_comment both succeeded.

    "Succeeded" means a non-ERROR tool result — see tools_succeeded.
    A failed PR call (e.g. 422 from branch protection) followed by a
    comment must not count as done; the branch would orphan.
    """
    succeeded = tools_succeeded(messages)
    return "github__create_pull_request" in succeeded and "github__add_issue_comment" in succeeded


def step_aware_continue_prompt(messages: list, params: dict) -> str:
    """
    On a no-tool-call turn, return the most specific next-step instruction
    we can derive from session state. Catches the eval-20b/20c pattern
    where the model finishes Step 3 and stalls before Step 5/6 — generic
    "call a tool" prompts weren't enough; the model needs to be told
    WHICH tool comes next.
    """
    # Use tools_succeeded — a tool that was called but errored shouldn't
    # advance the step-phase detection (e.g. failed create_pull_request
    # must not push the model toward Step 6 comment).
    succeeded = tools_succeeded(messages)
    issue_number = params.get("issue_number", "<the issue>")

    if "github__create_pull_request" in succeeded and "github__add_issue_comment" not in succeeded:
        return (
            f"`github__create_pull_request` has fired. The recipe's Step 6 is now "
            f"mandatory. Your NEXT TOOL CALL must be `github__add_issue_comment` "
            f"on issue #{issue_number} with the PR link and a status line "
            f"(✅ done | ⚠️ partial | ❌ blocked). Do not narrate. Call the tool."
        )

    if FILE_WRITE_TOOLS & succeeded and "github__create_pull_request" not in succeeded:
        return (
            "You have committed files to the branch. Step 5 of the recipe is now "
            "mandatory: open the PR. Your NEXT TOOL CALL must be "
            "`github__create_pull_request`. Title: match the issue title. "
            f"Body must include `Closes #{issue_number}`, `## Summary`, "
            "`## Verification`, `## Subtasks`. Do not narrate. Do not summarize. "
            "Call the tool."
        )

    if "github__create_branch" in succeeded and not (FILE_WRITE_TOOLS & succeeded):
        return (
            "The branch is created. Continue with Step 3 — execute the issue's "
            "subtask checklist. Your NEXT TOOL CALL must be `github__push_files` "
            "(multi-file) or `github__create_or_update_file` (single-file). "
            "Before overwriting an existing file, fetch its content first with "
            "`github__get_file_contents` to avoid clobbering unrelated content."
        )

    if "github__issue_read" in succeeded and "github__create_branch" not in succeeded:
        return (
            "Issue read. Continue with Step 2 — create the branch. Your NEXT "
            "TOOL CALL must be `github__create_branch` with name "
            f"`runner/issue-{issue_number}-<slug>` from the integration branch."
        )

    return (
        "You emitted no tool call this turn. The recipe is not complete. "
        "Identify which step you're on (Step 0-6) and call the next tool "
        "directly. Do not narrate. Do not summarize. Call the tool."
    )


def _extract_branch(messages: list) -> str | None:
    """Pull the branch name from the most recent create_branch tool call."""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] != "github__create_branch":
                continue
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                continue
            if args.get("branch"):
                return args["branch"]
    return None


def _extract_issue_title(messages: list) -> str | None:
    """Find the issue_read tool result and parse its JSON for the title."""
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] != "github__issue_read":
                continue
            tc_id = tc["id"]
            for follow in messages[i + 1 :]:
                if follow.get("role") != "tool":
                    continue
                if follow.get("tool_call_id") != tc_id:
                    continue
                try:
                    data = json.loads(follow["content"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(data, dict) and data.get("title"):
                    return data["title"]
    return None


def attempt_salvage(messages: list, params: dict) -> dict | None:
    """
    Open a mechanical PR if the model committed work but never called
    `create_pull_request`. Print a clear marker for eval-log scanning.

    Returns the salvage_pr result dict, or None if salvage was skipped
    (model already opened the PR, or session lacks the state needed).
    """
    # Use tools_succeeded so a failed create_pull_request call (e.g. 422)
    # still triggers salvage rather than letting the branch orphan.
    if "github__create_pull_request" in tools_succeeded(messages):
        return None  # model already opened the PR

    branch = _extract_branch(messages)
    issue_title = _extract_issue_title(messages)
    repo = params.get("repo", "")
    base_branch = params.get("base_branch", "main")
    issue_number_raw = params.get("issue_number")

    if not (branch and issue_title and repo and issue_number_raw):
        print("\n=== Salvage skipped: missing branch / issue-title / repo / issue-number ===")
        return None

    try:
        issue_number = int(issue_number_raw)
    except (TypeError, ValueError):
        print(f"\n=== Salvage skipped: issue_number={issue_number_raw!r} not an int ===")
        return None

    print(f"\n=== Salvage attempt: branch={branch} → base={base_branch} ===")
    result = salvage_pr(repo, branch, base_branch, issue_number, issue_title)
    status = result.get("status")

    if status == "opened":
        print(f"  ✓ Salvage PR opened: {result['pr_url']} ({result['commit_count']} commits)")
        comment_url = salvage_comment(repo, issue_number, result["pr_url"])
        if comment_url:
            print(f"  ✓ Salvage comment posted: {comment_url}")
        else:
            print("  ✗ Salvage comment failed to post")
    elif status == "pr_exists":
        print(f"  – PR already exists for this branch (#{result['pr_number']}); no salvage needed")
    elif status == "no_branch":
        print(f"  – Branch {branch} does not exist on remote; nothing to salvage")
    elif status == "no_commits":
        print(f"  – Branch {branch} has no commits ahead of {base_branch}; nothing to salvage")
    elif status == "error":
        print(f"  ✗ Salvage failed: {result.get('error', 'unknown')}")
    else:
        print(f"  ? Unexpected salvage status: {status}")

    return result


def log_tool_call(name: str, args: dict) -> None:
    """Mirror Goose's ▸ marker format so eval logs are comparable."""
    print("\n  ────────────────────────────────────────")
    print(f"  ▸ {name}")
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            v = v[:200] + "... [truncated]"
        elif isinstance(v, list):
            v = f"[{len(v)} items]"
        print(f"    {k}: {v}")
    print()


def run_session(
    host: str,
    model: str,
    recipe_path: Path,
    params: dict,
    max_turns: int = 60,
    salvage_enabled: bool = True,
) -> int:
    recipe_prompt, recipe_title = load_recipe(recipe_path, params)
    # load_recipe filled in YAML-declared defaults; now safe to template the
    # system prompt, which also references {{ base_branch }}.
    system_prompt = template_recipe(SYSTEM_PROMPT_PATH.read_text(), params)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": recipe_prompt},
    ]

    print("Runner:         direct-ollama POC")
    print(f"Repo:           {REPO_ROOT}")
    print(f"Ollama:         {host}")
    print(f"Recipe:         {recipe_path}  ({recipe_title})")
    print(f"Model:          {model}")
    print(f"Params:         {params}")
    print(f"Tools:          {len(TOOL_SCHEMAS)} declared")
    print()
    print("=== Session start ===")

    empty_turn_count = 0
    for turn in range(1, max_turns + 1):
        resp = ollama_chat(host, model, messages, TOOL_SCHEMAS)
        msg = resp["choices"][0]["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        content = msg.get("content") or ""

        if tool_calls:
            empty_turn_count = 0
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    # TypeError covers Ollama providers that return arguments
                    # as None or as a dict already (rather than a JSON string).
                    fn_args = tc["function"]["arguments"]
                log_tool_call(fn_name, fn_args if isinstance(fn_args, dict) else {"raw": fn_args})
                impl = DISPATCH.get(fn_name)
                if impl is None:
                    result = f"ERROR: unknown tool {fn_name}. Available: {sorted(DISPATCH.keys())}"
                else:
                    try:
                        result = impl(fn_args if isinstance(fn_args, dict) else {})
                    except Exception as e:
                        result = f"ERROR running {fn_name}: {type(e).__name__}: {e}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )
            if recipe_done(messages):
                print(f"\n=== Recipe complete: PR + issue comment both fired (turn {turn}) ===")
                return 0
            continue

        # No tool call this turn. THIS IS THE CRUX of the POC.
        # Goose would exit here; we prompt the model to continue.
        if content:
            print(f"\n  [model emitted prose — {len(content)} chars; no tool call]")
            print(f"  {content[:300]}{'...' if len(content) > 300 else ''}\n")

        empty_turn_count += 1
        if empty_turn_count >= 3:
            print(f"\n=== 3 consecutive no-tool-call turns; giving up (turn {turn}) ===")
            if salvage_enabled:
                attempt_salvage(messages, params)
            return 2

        if recipe_done(messages):
            print(f"\n=== Recipe complete (turn {turn}) ===")
            return 0

        next_prompt = step_aware_continue_prompt(messages, params)
        print(f'  [runner: nudging — "{next_prompt[:80]}..."]\n')
        messages.append({"role": "user", "content": next_prompt})

    print(f"\n=== Hit max_turns ({max_turns}); giving up ===")
    if salvage_enabled:
        attempt_salvage(messages, params)
    return 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_base_branch(target_repo: str) -> str | None:
    """Mirror the wrapper's default_branch resolution."""
    rc, out, _ = _gh(["api", f"repos/{target_repo}", "--jq", ".default_branch"])
    return out.strip() if rc == 0 and out.strip() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--params", action="append", default=[])
    parser.add_argument("--model", default=os.environ.get("RUNNER_MODEL", "qwen3.6:latest"))
    parser.add_argument(
        "--ollama-host",
        default=os.environ.get("OLLAMA_HOST", "http://bazzite.local:11434"),
    )
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument(
        "--no-salvage",
        action="store_true",
        help="Disable the mechanical PR-from-branch fallback when the model exits without "
        "calling create_pull_request.",
    )
    args = parser.parse_args()

    if not args.recipe.exists():
        print(f"Recipe not found: {args.recipe}", file=sys.stderr)
        return 2

    if not os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"):
        print("GITHUB_PERSONAL_ACCESS_TOKEN not set", file=sys.stderr)
        return 2

    params = {}
    for p in args.params:
        if "=" not in p:
            print(f"Bad --params format: {p}", file=sys.stderr)
            return 2
        k, v = p.split("=", 1)
        params[k] = v

    if "base_branch" not in params and "repo" in params:
        resolved = resolve_base_branch(params["repo"])
        if resolved:
            params["base_branch"] = resolved
            print(f"(resolved base_branch={resolved} from {params['repo']})")
        else:
            params["base_branch"] = "main"
            print("(could not resolve default_branch; defaulting base_branch=main)")

    return run_session(
        host=args.ollama_host,
        model=args.model,
        recipe_path=args.recipe,
        params=params,
        max_turns=args.max_turns,
        salvage_enabled=not args.no_salvage,
    )


if __name__ == "__main__":
    sys.exit(main())
