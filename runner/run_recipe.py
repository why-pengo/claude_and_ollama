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
import os
import sys
from pathlib import Path

from gh import _gh, check_gh_auth
from recipe import generate_branch_name
from session import run_session
from workspace import WorkspaceError, restore_workspace, validate_workspace

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
