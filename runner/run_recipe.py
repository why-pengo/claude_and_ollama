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
import json
import os
import sys
from collections import Counter
from pathlib import Path

import httpx

from gh import _gh, check_gh_auth
from ollama_client import (
    extract_turn_metrics,
    format_session_metrics_summary,
    format_turn_metrics,
    ollama_chat,
)
from prose_rescue import parse_prose_tool_call, turn_signature
from recipe import (
    _tool_result_succeeded,
    generate_branch_name,
    load_recipe,
    recipe_done,
    step_aware_continue_prompt,
    template_recipe,
)
from salvage import format_salvage_status, salvage_comment, salvage_pr
from tools import DISPATCH, TOOL_SCHEMAS, log_tool_call
from workspace import WorkspaceError, restore_workspace, validate_workspace

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "system-prompt.md"


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
