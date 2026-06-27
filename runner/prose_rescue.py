"""Prose-channel tool-call rescue + per-turn loop-detection signature.

eval-26 (llama3.3:70b q3) and eval-29 (qwen2.5-coder:32b) both showed
models that knew the right tool-call format and emitted well-formed
tool-call JSON — but in the content channel instead of via the
structured `tool_calls` field. `parse_prose_tool_call` recovers those
into the same shape a structured tool call would have taken so the
dispatch path runs unchanged.

`turn_signature` is the per-turn hash the session loop's loop-detector
keys on (#86, #87) — same family of recovery concerns since both deal
with "what shape did the model actually emit this turn?"
"""

import hashlib
import json
from collections.abc import Container


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
