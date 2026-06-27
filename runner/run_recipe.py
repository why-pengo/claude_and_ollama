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

Prereq:
    `gh` CLI authenticated (`gh auth status` clean). Either a keyring
    login via `gh auth login` or an exported GH_TOKEN/GITHUB_TOKEN works.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Container
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from gh import _gh, check_gh_auth
from salvage import format_salvage_status, salvage_comment, salvage_pr
from workspace import WorkspaceError, restore_workspace, validate_workspace

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


def ollama_chat(
    client: httpx.Client,
    host: str,
    model: str,
    messages: list,
    tools: list,
    options: dict | None = None,
) -> dict:
    """POST a chat-completion request to Ollama's native /api/chat.

    The client is created once per session in `run_session` so the
    underlying TCP connection (and keep-alive pool) is reused across
    every turn instead of being torn down and re-handshaken each time.

    `options` is the native per-request knob bag (num_ctx, num_gpu, seed,
    temperature, ...). Omitted from the payload when empty so requests
    stay minimal and Ollama applies its own defaults.
    """
    url = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
    }
    if options:
        payload["options"] = options
    r = client.post(url, json=payload)
    r.raise_for_status()
    return r.json()


# Ollama's /api/chat response includes per-call timing fields. Durations
# are in nanoseconds. Extracted shape is used by the per-turn log line and
# the end-of-session summary. See #88.
_METRIC_KEYS = (
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
    "total_duration",
    "load_duration",
)


def extract_turn_metrics(resp: dict) -> dict | None:
    """Pluck Ollama's timing fields from a /api/chat response.

    Returns a dict with all _METRIC_KEYS (missing fields set to None), or
    None if none of the fields are present — keeps the runner quiet for
    mocked responses and non-Ollama backends that don't populate them.
    """
    extracted = {k: resp.get(k) for k in _METRIC_KEYS}
    if all(v is None for v in extracted.values()):
        return None
    return extracted


def _rate(count: int | None, duration_ns: int | None) -> str:
    # None → missing field; duration==0 → can't divide. count==0 is a
    # legitimate zero-token turn — render as "0.0", not "?", so a real
    # zero stays distinguishable from a missing field in the log.
    if count is None or duration_ns is None or duration_ns == 0:
        return "?"
    return f"{count / (duration_ns / 1e9):.1f}"


def format_turn_metrics(metrics: dict) -> str:
    """Render the per-turn one-liner specified in #88."""
    pe = metrics.get("prompt_eval_count")
    pd = metrics.get("prompt_eval_duration")
    ec = metrics.get("eval_count")
    ed = metrics.get("eval_duration")
    td = metrics.get("total_duration")
    return (
        f"[metrics: prompt={'?' if pe is None else pe} tok @ {_rate(pe, pd)} t/s | "
        f"gen={'?' if ec is None else ec} tok @ {_rate(ec, ed)} t/s | "
        f"total={'?' if td is None else f'{td / 1e9:.1f}'}s]"
    )


def format_session_metrics_summary(turn_metrics: list[dict]) -> str:
    """Aggregate per-turn metrics into a single end-of-session line.

    Rates are weighted by tokens (sum tokens / sum duration), which matches
    the effective throughput a future plot would care about — not the
    arithmetic mean of per-turn rates.
    """
    if not turn_metrics:
        return "[session metrics: turns=0 (no per-call metrics captured)]"

    def paired_sum(count_key: str, dur_key: str) -> tuple[int, int]:
        # Pair count+duration *within a turn* before summing — otherwise
        # tokens from a turn missing its duration could combine with the
        # duration from a different turn, producing a nonsense rate.
        # Ollama always emits the pair together; this just makes the code
        # robust to a backend that doesn't.
        c, d = 0, 0
        for m in turn_metrics:
            ck, dk = m.get(count_key), m.get(dur_key)
            if ck is not None and dk is not None:
                c += ck
                d += dk
        return c, d

    pe, pd = paired_sum("prompt_eval_count", "prompt_eval_duration")
    ec, ed = paired_sum("eval_count", "eval_duration")
    td = sum(m["total_duration"] for m in turn_metrics if m.get("total_duration") is not None)
    return (
        f"[session metrics: turns={len(turn_metrics)} | "
        f"prompt={pe} tok @ {_rate(pe, pd)} t/s | "
        f"gen={ec} tok @ {_rate(ec, ed)} t/s | "
        f"wall={td / 1e9:.1f}s]"
    )


def generate_branch_name(issue_number: str, *, now: datetime | None = None) -> str:
    """Generate the working branch name for a runner session.

    Format: `runner/issue-<N>-<YYYYMMDD-HHMMSS>` (local time, seconds
    resolution). Runner-owned so back-to-back same-task invocations
    don't collide on the model's slug choice (see #97, #98).
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"runner/issue-{issue_number}-{stamp}"


def template_recipe(prompt: str, params: dict) -> str:
    """Replace {{ key }} placeholders with parameter values."""

    def sub(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key not in params:
            raise KeyError(
                f"Recipe references {{{{ {key} }}}} but no --params {key}=... was passed"
            )
        return str(params[key])

    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", sub, prompt)


def _as_str_list(value: object, *, field: str, step_id: str) -> list[str]:
    """Normalize a YAML scalar-or-list into list[str].

    YAML lets a single-element list be written as a bare scalar
    (`advances_on: github__issue_read`). `list("github__issue_read")` would
    silently turn that into per-character entries, breaking step detection
    with no error. Accept the scalar form, reject anything else loudly.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                raise TypeError(
                    f"step {step_id!r} {field}: expected list of strings, "
                    f"got element {item!r} of type {type(item).__name__}"
                )
        return list(value)
    raise TypeError(
        f"step {step_id!r} {field}: expected str or list of str, "
        f"got {type(value).__name__}: {value!r}"
    )


def load_recipe(path: Path, params: dict) -> tuple[str, str, list, dict]:
    """Returns (templated_prompt, recipe_title, steps, ollama_options).

    Mutates `params` to apply the recipe's declared parameter defaults for any
    key not explicitly passed — so a recipe author marking a parameter as
    optional-with-default works as advertised.

    `steps` is the recipe's step graph (see `step_aware_continue_prompt`).
    Each step's `nudge` is templated up-front so the session loop doesn't
    need to thread params through.

    `ollama_options` is the recipe's `options:` block (passed through to
    /api/chat as per-request options). CLI flags override these.
    """
    data = yaml.safe_load(path.read_text())
    title = data.get("title", "Recipe")
    raw_prompt = data["prompt"]

    for p in data.get("parameters") or []:
        key = p.get("key")
        default = p.get("default")
        if key and key not in params and default is not None:
            params[key] = default

    steps = []
    for s in data.get("steps") or []:
        step_id = s["id"]
        steps.append(
            {
                "id": step_id,
                "advances_on": _as_str_list(
                    s.get("advances_on"), field="advances_on", step_id=step_id
                ),
                "requires_prior": _as_str_list(
                    s.get("requires_prior"), field="requires_prior", step_id=step_id
                ),
                "nudge": template_recipe(s["nudge"], params) if s.get("nudge") else None,
            }
        )

    raw_options = data.get("options")
    if raw_options is not None and not isinstance(raw_options, dict):
        raise TypeError(
            f"recipe options: expected mapping (e.g. 'num_ctx: 65536'), got "
            f"{type(raw_options).__name__}: {raw_options!r}"
        )
    ollama_options = dict(raw_options or {})

    return template_recipe(raw_prompt, params), title, steps, ollama_options


def _tool_result_succeeded(result: str) -> bool:
    """True if a tool result doesn't start with the "ERROR" prefix the
    wrappers use. Centralises the "what counts as success?" predicate so
    the dispatch loop and any future caller agree on the same rule.
    """
    return not result.startswith("ERROR")


def recipe_done(succeeded: set[str]) -> bool:
    """True if create_pull_request AND add_issue_comment both succeeded.

    `succeeded` is the set of tool names that have had at least one
    non-ERROR result this session — maintained as monotonic-add-only by
    the session loop. The #55 regression guard rides on the same set:
    a failed PR call (e.g. 422 from branch protection) is never added,
    so a later successful comment call cannot flip this to True.
    """
    return "github__create_pull_request" in succeeded and "github__add_issue_comment" in succeeded


GENERIC_CONTINUE_PROMPT = (
    "You emitted no tool call this turn. The recipe is not complete. "
    "Identify which step you're on (Step 0-6) and call the next tool "
    "directly. Do not narrate. Do not summarize. Call the tool."
)


def parse_prose_tool_call(content: str, dispatch_keys: Container[str]) -> tuple[str, dict] | None:
    """Try to recover a structured tool call from prose-channel content.

    Returns (fn_name, fn_args) on hit, None on miss.

    eval-26 (llama3.3:70b q3) and eval-29 (qwen2.5-coder:32b) both showed
    models that knew the right tool call format and emitted well-formed
    tool-call JSON — but in the content channel instead of via the
    structured `tool_calls` field. The dispatch loop saw no tool calls,
    treated the turn as no-op, and the empty-turn / loop-detect guard
    eventually aborted the session. This rescue parses those into the
    same shape a structured tool call would have taken so the dispatch
    path can run unchanged.

    Accepts both `arguments` (OpenAI/qwen convention) and `parameters`
    (llama convention) for the args field. Tolerates a leading `type:
    "function"` wrapper key. Normalizes a single-underscore prefix like
    `github_create_or_update_file` to the double-underscore form the
    DISPATCH dict actually uses — llama3.3 emits the single form.

    `dispatch_keys` is the set/dict of recognised tool names; the rescue
    only fires when the parsed name resolves to a real tool. Refuses
    plausible-but-unknown names rather than dispatching garbage.
    """
    if not content or '"name"' not in content:
        return None

    obj = _try_load_json(content.strip())
    if obj is None:
        obj = _find_embedded_json_with_name(content)
        if obj is None:
            return None

    name = obj.get("name")
    if not isinstance(name, str):
        return None

    args = obj.get("arguments")
    if args is None:
        args = obj.get("parameters")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None

    # Scoped to the `github_X` → `github__X` case observed in eval-26;
    # broader "double the first underscore" would let any unknown tool
    # name accidentally coerce to a valid dispatch key.
    if name not in dispatch_keys and name.startswith("github_") and not name.startswith("github__"):
        normalized = "github__" + name[len("github_") :]
        if normalized in dispatch_keys:
            name = normalized

    if name not in dispatch_keys:
        return None

    return name, args


def _try_load_json(s: str) -> dict | None:
    # Models sometimes wrap JSON in a markdown fence; strip the common forms
    # before attempting json.loads. Leaves non-fenced content untouched.
    stripped = s.strip()
    for fence in ("```json", "```"):
        if stripped.startswith(fence):
            stripped = stripped[len(fence) :].lstrip()
            break
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()
    try:
        result = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _find_embedded_json_with_name(content: str) -> dict | None:
    """Scan for a balanced JSON object containing a `name` key.

    Brace-balanced rather than regex-based so nested objects and quoted
    braces inside strings don't trip us up. Returns the first matching
    object so prose like "I'll call: {name: ..., args: ...}" works.
    """
    i = 0
    n = len(content)
    while i < n:
        if content[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        for j in range(i, n):
            c = content[j]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = content[i : j + 1]
                    obj = _try_load_json(candidate)
                    if isinstance(obj, dict) and "name" in obj:
                        return obj
                    break
        i += 1
    return None


def turn_signature(msg: dict) -> tuple:
    """Hashable signature of one assistant turn, for loop detection.

    Tool-call turns hash on a tuple of (fn_name, canonical-JSON-args) per
    call so identical calls compare equal regardless of key ordering.
    Prose-only turns hash on a sha256 of the content — sha256 because the
    raw prose can be multi-KB and the signature ends up in a Counter.

    eval-26 produced a sampling-collapse loop that alternated identical
    tool calls with identical prose blobs (~12x repeats). The existing
    empty_turn_count guard at run_session() only fires on consecutive
    no-tool-call turns, so the alternation kept resetting it. This
    signature is what the loop-detect Counter keys on instead.
    """
    tool_calls = msg.get("tool_calls") or []
    if tool_calls:
        parts = []
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    pass
            try:
                canonical = json.dumps(args, sort_keys=True, default=str)
            except TypeError:
                canonical = repr(args)
            parts.append(("tool", name, canonical))
        return tuple(parts)
    content = msg.get("content") or ""
    return (("prose", hashlib.sha256(content.encode("utf-8")).hexdigest()),)


def step_aware_continue_prompt(succeeded: set[str], steps: list) -> str:
    """
    On a no-tool-call turn, return the most specific next-step instruction
    we can derive from session state. Catches the eval-20b/20c pattern
    where the model finishes Step 3 and stalls before Step 5/6 — generic
    "call a tool" prompts weren't enough; the model needs to be told
    WHICH tool comes next.

    `succeeded` is the set of tool names that have had at least one
    non-ERROR result this session — monotonic-add-only, maintained by
    the session loop. A step counts as "done" when at least one of its
    advances_on tools is in that set. The walk returns the pre-templated
    nudge of the first step whose requires_prior steps are all done but
    who isn't.
    """
    by_id = {s["id"]: s for s in steps}

    def step_done(step: dict) -> bool:
        return any(t in succeeded for t in step["advances_on"])

    for step in steps:
        if step_done(step):
            continue
        prereqs = step.get("requires_prior", [])
        if not all(p in by_id and step_done(by_id[p]) for p in prereqs):
            continue
        if step.get("nudge"):
            return step["nudge"]

    return GENERIC_CONTINUE_PROMPT


def _extract_branch(messages: list) -> str | None:
    """Pull the branch name from the most recent create_branch tool call."""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] != "github__create_branch":
                continue
            raw = tc["function"]["arguments"]
            # Native /api/chat returns arguments as a dict; OpenAI-compat as a
            # JSON string. Mirror the dispatch loop's fallback so salvage's
            # branch-recovery path works against either shape.
            try:
                args = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                args = raw if isinstance(raw, dict) else {}
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


def attempt_salvage(messages: list, params: dict, succeeded: set[str]) -> dict | None:
    """
    Open a mechanical PR if the model committed work but never called
    `create_pull_request`. Print a clear marker for eval-log scanning.

    Returns the salvage_pr result dict, or None if salvage was skipped
    (model already opened the PR, or session lacks the state needed).
    """
    # A failed create_pull_request call (e.g. 422) is NOT in `succeeded`,
    # so salvage still fires and the branch doesn't orphan.
    if "github__create_pull_request" in succeeded:
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
    print(f"  {format_salvage_status(result, branch, base_branch)}")

    # 'opened' has a follow-up the formatter can't express: post the Step 6
    # equivalent comment. Stays here because it does I/O, not formatting.
    if result.get("status") == "opened":
        comment_url = salvage_comment(repo, issue_number, result["pr_url"])
        if comment_url:
            print(f"  ✓ Salvage comment posted: {comment_url}")
        else:
            print("  ✗ Salvage comment failed to post")

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
    cli_options: dict | None = None,
    turn_timeout: float = 600.0,
    loop_detect_threshold: int | None = 4,
    workspace_dir: Path | None = None,
) -> int:
    recipe_prompt, recipe_title, recipe_steps, recipe_options = load_recipe(recipe_path, params)
    # load_recipe filled in YAML-declared defaults; now safe to template the
    # system prompt, which also references {{ base_branch }}.
    system_prompt = template_recipe(SYSTEM_PROMPT_PATH.read_text(), params)

    # CLI options override recipe options (per-run knob trumps recipe default).
    options = {**recipe_options, **(cli_options or {})}

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": recipe_prompt},
    ]

    print("Runner:         direct-ollama POC")
    print(f"Repo:           {REPO_ROOT}")
    print(f"Ollama:         {host}")
    if workspace_dir is not None:
        print(f"Workspace:      {workspace_dir}")
    print(f"Recipe:         {recipe_path}  ({recipe_title})")
    print(f"Model:          {model}")
    print(f"Params:         {params}")
    print(f"Options:        {options or '(defaults)'}")
    print(f"Turn timeout:   {turn_timeout:g}s")
    print(f"Tools:          {len(TOOL_SCHEMAS)} declared")
    print()
    print("=== Session start ===")

    succeeded: set[str] = set()
    empty_turn_count = 0
    # Per-turn timing metrics extracted from each /api/chat response.
    # Drives the per-turn log line and the end-of-session summary (#88).
    turn_metrics: list[dict] = []
    # Counter of turn signatures since the last successful new tool name
    # reached `succeeded`. eval-26 showed sampling-collapse loops that
    # alternate identical tool calls with identical prose blobs, so the
    # consecutive-empty-turn guard below doesn't catch them. When any
    # single signature's count crosses loop_detect_threshold, we abort.
    recent_signatures: Counter[tuple] = Counter()
    # One httpx.Client for the whole session — TCP+TLS handshake to the
    # Ollama host happens once, then the connection pool keeps the socket
    # warm across every turn (vs. a per-call handshake under the old shape).
    # turn_timeout caps a single chat call — at heavy-offload throughput
    # (1-2 t/s on a 70B with partial GPU), a 600s cap chokes responses past
    # ~1000 tokens; bump it for big models via --turn-timeout.
    with httpx.Client(timeout=turn_timeout) as client:
        for turn in range(1, max_turns + 1):
            resp = ollama_chat(client, host, model, messages, TOOL_SCHEMAS, options)
            metrics = extract_turn_metrics(resp)
            if metrics is not None:
                turn_metrics.append(metrics)
                print(f"  {format_turn_metrics(metrics)}")
            msg = resp["message"]

            # Native /api/chat omits `id` on tool calls. Synthesize one IN PLACE
            # on the assistant message before we append it, so the whole pipeline
            # (this loop's tool_call_id below, _extract_issue_title's correlation
            # walk, any future consumer) sees a coherent assistant↔tool linkage.
            for i, tc in enumerate(msg.get("tool_calls") or []):
                if "id" not in tc:
                    tc["id"] = f"call_{turn}_{i}"

            # Prose-shaped tool call rescue (#84). If the model emitted tool
            # call JSON in the content channel rather than via tool_calls,
            # synthesize the structured form IN PLACE on msg before appending.
            # The rest of the loop then runs unchanged — both dispatch and the
            # message history see this as a normal tool-call turn.
            if not (msg.get("tool_calls") or []) and msg.get("content"):
                rescued = parse_prose_tool_call(msg["content"], DISPATCH)
                if rescued is not None:
                    fn_name, fn_args = rescued
                    msg["tool_calls"] = [
                        {
                            "id": f"rescued_{turn}",
                            "function": {"name": fn_name, "arguments": fn_args},
                        }
                    ]
                    print(f"\n  [runner: rescued prose-shaped tool call → {fn_name}]")

            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            prev_succeeded_count = len(succeeded)
            sig = turn_signature(msg)

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
                    log_tool_call(
                        fn_name, fn_args if isinstance(fn_args, dict) else {"raw": fn_args}
                    )
                    impl = DISPATCH.get(fn_name)
                    if impl is None:
                        result = (
                            f"ERROR: unknown tool {fn_name}. Available: {sorted(DISPATCH.keys())}"
                        )
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
                    if _tool_result_succeeded(result):
                        succeeded.add(fn_name)
                if recipe_done(succeeded):
                    print(f"\n=== Recipe complete: PR + issue comment both fired (turn {turn}) ===")
                    print(format_session_metrics_summary(turn_metrics))
                    return 0
            else:
                # No tool call this turn. THIS IS THE CRUX of the POC.
                # Goose would exit here; we prompt the model to continue.
                if content:
                    print(f"\n  [model emitted prose — {len(content)} chars; no tool call]")
                    print(f"  {content[:300]}{'...' if len(content) > 300 else ''}\n")

                empty_turn_count += 1
                if empty_turn_count >= 3:
                    print(f"\n=== 3 consecutive no-tool-call turns; giving up (turn {turn}) ===")
                    print(format_session_metrics_summary(turn_metrics))
                    if salvage_enabled:
                        attempt_salvage(messages, params, succeeded)
                    return 2

                if recipe_done(succeeded):
                    print(f"\n=== Recipe complete (turn {turn}) ===")
                    print(format_session_metrics_summary(turn_metrics))
                    return 0

                next_prompt = step_aware_continue_prompt(succeeded, recipe_steps)
                print(f'  [runner: nudging — "{next_prompt[:80]}..."]\n')
                messages.append({"role": "user", "content": next_prompt})

            # Loop detection — runs for both branches. Any new tool name
            # reaching `succeeded` this turn is real progress, so the
            # counter resets. Otherwise track this turn's signature; if
            # the same one has now appeared loop_detect_threshold times
            # since last progress, abort instead of burning more turns.
            if loop_detect_threshold is not None:
                if len(succeeded) > prev_succeeded_count:
                    recent_signatures.clear()
                else:
                    recent_signatures[sig] += 1
                    if recent_signatures[sig] >= loop_detect_threshold:
                        print(
                            f"\n=== Loop detected: turn signature repeated "
                            f"{recent_signatures[sig]}x without progress; aborting "
                            f"(turn {turn}) ==="
                        )
                        print(format_session_metrics_summary(turn_metrics))
                        if salvage_enabled:
                            attempt_salvage(messages, params, succeeded)
                        return 4

    print(f"\n=== Hit max_turns ({max_turns}); giving up ===")
    print(format_session_metrics_summary(turn_metrics))
    if salvage_enabled:
        attempt_salvage(messages, params, succeeded)
    return 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _coerce_option_value(raw: str) -> bool | int | float | str:
    """Best-effort coercion for --ollama-option VALUE strings.

    Tries bool → int → float → str so callers can write `use_mmap=true`,
    `num_gpu=30`, `temperature=0.7` and get the right JSON type on the wire.
    """
    lower = raw.lower()
    if lower in ("true", "false"):
        return lower == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def resolve_base_branch(target_repo: str) -> str | None:
    """Mirror the wrapper's default_branch resolution."""
    rc, out, _ = _gh(["api", f"repos/{target_repo}", "--jq", ".default_branch"])
    return out.strip() if rc == 0 and out.strip() else None


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser. Extracted from `main` so tests can introspect
    argparse defaults (e.g. assert the default `--model` matches ADR-0008)
    without invoking the full `main` entry point.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--params", action="append", default=[])
    parser.add_argument("--model", default=os.environ.get("RUNNER_MODEL", "qwen2.5-coder:32b"))
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=(
            Path(os.environ["RUNNER_WORKSPACE_DIR"])
            if os.environ.get("RUNNER_WORKSPACE_DIR")
            else None
        ),
        help="Local checkout of the target repo. Validated before the session runs "
        "(must exist, match `--params repo=...`, be clean, and be at the tip of "
        "the resolved base_branch). Falls back to $RUNNER_WORKSPACE_DIR.",
    )
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
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=None,
        help="Per-request context window size (folds into Ollama options.num_ctx).",
    )
    parser.add_argument(
        "--ollama-option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Generic per-request Ollama option (e.g. num_gpu=30, seed=42, temperature=0.7). "
        "Repeatable. Numeric and boolean values are coerced; everything else stays a string.",
    )
    parser.add_argument(
        "--turn-timeout",
        type=float,
        default=600.0,
        help="Seconds to wait on a single chat call before httpx raises ReadTimeout. "
        "Default 600s is fine for ~30 t/s qwen-class models; for 70B-class with heavy "
        "CPU offload (~1-2 t/s), bump to 3600 or higher.",
    )
    parser.add_argument(
        "--loop-detect-threshold",
        type=int,
        default=4,
        help="Abort when the same turn signature (tool call + args, or prose-content "
        "hash) has appeared this many times since the last successful new tool name "
        "reached `succeeded`. Default 4 catches the eval-26 sampling-collapse pattern "
        "(alternating identical tool calls / prose blobs) without tripping on a few "
        "legitimate repeat reads. Must be a positive integer; use --no-loop-detect "
        "to disable.",
    )
    parser.add_argument(
        "--no-loop-detect",
        action="store_true",
        help="Disable the repeated-signature loop-detection guard. Use when "
        "investigating model behaviour that legitimately involves many identical "
        "repeated calls.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if not args.recipe.exists():
        print(f"Recipe not found: {args.recipe}", file=sys.stderr)
        return 2

    ok, msg = check_gh_auth()
    if not ok:
        print(msg, file=sys.stderr)
        return 2

    # 0 or negative would make the guard trip on every no-progress turn
    # (Counter[sig] >= 0 is always true). The disable path is --no-loop-detect.
    if args.loop_detect_threshold <= 0:
        print(
            f"--loop-detect-threshold must be a positive integer "
            f"(got {args.loop_detect_threshold}); use --no-loop-detect to disable.",
            file=sys.stderr,
        )
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

    if "branch" not in params and "issue_number" in params:
        params["branch"] = generate_branch_name(params["issue_number"])
        print(f"(generated branch={params['branch']})")

    cli_options: dict = {}
    if args.num_ctx is not None:
        cli_options["num_ctx"] = args.num_ctx
    for opt in args.ollama_option:
        if "=" not in opt:
            print(f"Bad --ollama-option format: {opt} (expected KEY=VALUE)", file=sys.stderr)
            return 2
        k, v = opt.split("=", 1)
        cli_options[k] = _coerce_option_value(v)

    if args.workspace_dir is None:
        print(
            "--workspace-dir / RUNNER_WORKSPACE_DIR not set; runner needs a local "
            "checkout of the target repo to validate against.",
            file=sys.stderr,
        )
        return 2
    if "repo" not in params:
        print(
            "--params repo=<owner>/<name> is required when --workspace-dir is set "
            "(pre-flight matches the workspace's origin against this value).",
            file=sys.stderr,
        )
        return 2
    try:
        validate_workspace(args.workspace_dir, params["repo"], params["base_branch"])
    except WorkspaceError as e:
        print(f"Workspace pre-flight failed: {e}", file=sys.stderr)
        return 2

    try:
        return run_session(
            host=args.ollama_host,
            model=args.model,
            recipe_path=args.recipe,
            params=params,
            max_turns=args.max_turns,
            salvage_enabled=not args.no_salvage,
            cli_options=cli_options,
            turn_timeout=args.turn_timeout,
            loop_detect_threshold=None if args.no_loop_detect else args.loop_detect_threshold,
            workspace_dir=args.workspace_dir,
        )
    finally:
        restore_workspace(args.workspace_dir, params["base_branch"])


if __name__ == "__main__":
    sys.exit(main())
