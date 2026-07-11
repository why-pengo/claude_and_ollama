"""Session loop — drives the turn-by-turn dispatch of model output → tools.

Owns the per-session orchestration:

- One `httpx.Client` reused across every turn for connection keepalive.
- Dispatch loop: model emits tool_calls (or prose-shaped ones rescued in
  place); each call executes via `tools.DISPATCH`; results append to
  `messages` and the next turn fires.
- `succeeded` set membership gates the `recipe_done` check that closes a
  session cleanly when both `github__create_pull_request` and
  `github__add_issue_comment` have landed.
- Loop-detect Counter aborts sampling-collapse loops (#85).
- Salvage path (`attempt_salvage`) opens a mechanical PR when the model
  committed work but exited before calling `create_pull_request`.

Extracted from `run_recipe.py` so the CLI shell stays focused on argument
parsing and `main`.
"""

import json
from collections import Counter
from pathlib import Path

import httpx
from agents_md import ParsedAgentsMd, format_agents_summary

from ollama_client import (
    extract_turn_metrics,
    format_session_metrics_summary,
    format_turn_metrics,
    ollama_chat,
)
from prose_rescue import parse_prose_tool_call, turn_signature
from recipe import (
    _tool_result_succeeded,
    load_recipe,
    recipe_done,
    step_aware_continue_prompt,
    template_recipe,
)
from salvage import format_salvage_status, salvage_comment, salvage_pr
from tools import DISPATCH, TOOL_SCHEMAS, log_tool_call, repo_pin_error

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
    agents_md: ParsedAgentsMd | None = None,
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
    # `agents_md` is session state: #108's gate reads the verification
    # commands from here. Conventions are NOT injected into the system
    # prompt — the model fetches AGENTS.md itself via the recipe's Step 0.
    if agents_md is not None:
        print(f"AGENTS:         {format_agents_summary(agents_md)}")
    print(f"Recipe:         {recipe_path}  ({recipe_title})")
    print(f"Model:          {model}")
    print(f"Params:         {params}")
    print(f"Options:        {options or '(defaults)'}")
    print(f"Turn timeout:   {turn_timeout:g}s")
    print(f"Tools:          {len(TOOL_SCHEMAS)} declared")
    print()
    print("=== Session start ===")

    succeeded: set[str] = set()
    pinned_repo = params.get("repo", "")
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
                    args_dict = fn_args if isinstance(fn_args, dict) else {}
                    # Repo pinning (#119): the model's owner/repo args are
                    # steered by untrusted content, so any call not targeting
                    # the session's `--params repo` is refused before a gh
                    # subprocess spawns. main() guarantees `repo` is set;
                    # an empty pin (direct run_session callers) skips the check.
                    pin_err = repo_pin_error(args_dict, pinned_repo) if pinned_repo else None
                    if impl is None:
                        result = (
                            f"ERROR: unknown tool {fn_name}. Available: {sorted(DISPATCH.keys())}"
                        )
                    elif pin_err is not None:
                        result = pin_err
                    else:
                        try:
                            result = impl(args_dict)
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
