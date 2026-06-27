"""Ollama chat client + per-turn / per-session metrics helpers.

Wraps Ollama's native `/api/chat` endpoint and pulls the timing fields
out of the response so the runner can log per-turn throughput and an
end-of-session summary (#88). Extracted from `run_recipe.py` so the
session loop can call into it without owning HTTP concerns.
"""

import httpx


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
