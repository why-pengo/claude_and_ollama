"""Tool definitions + dispatch table for the runner.

Exposes the JSON Schemas the model sees (`TOOL_SCHEMAS`), the seven
`github_*` implementations that wrap the `gh` CLI, the `DISPATCH` table
mapping tool names → implementations, and the per-turn `log_tool_call`
formatter. Pulled out of `run_recipe.py` so the session loop can stay
focused on turn orchestration.
"""

import json

from gh import _gh

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
