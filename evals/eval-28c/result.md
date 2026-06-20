# eval-28c result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen3.6:latest` (36B)
- Options: `{'num_ctx': 65536}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2`
- Pre-flight: 100% GPU resident at 65536
- Third of 3 qwen3.6 runs in the #47 bake-off

## What worked

- End-to-end PASS at turn 21 — leanest of the three qwen3.6 runs.
- Native `tool_calls` throughout — no rescue dependency.
- Single step-aware nudge.
- Recovered cleanly from a `create_pull_request` retry and a `create_branch` retry without tripping loop detection.

## What didn't

- 10 file reads before first write — middle of the qwen3.6 range (eval-28: 11, eval-28b: 16).
- Same retry-on-PR-attempts pattern as 28b but less severe — fewer retries before success.

## Verdict

Verdict: PASS

Completes qwen3.6's **3/3 PASS** in the #47 bake-off — the only candidate to hit 3/3 in this round. Turn counts across runs: 23, 28, 21 (avg 24). See `docs/bakeoff-summary.md` for the recommendation that follows.

## Next time

- Bake-off complete; no per-eval next-time items.
