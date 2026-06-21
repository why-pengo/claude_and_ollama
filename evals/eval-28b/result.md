# eval-28b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen3.6:latest` (36B)
- Options: `{'num_ctx': 65536}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2`
- Pre-flight: 100% GPU resident at 65536
- Second of 3 qwen3.6 runs in the #47 bake-off

## What worked

- End-to-end PASS at turn 28.
- Native `tool_calls` throughout — no rescue dependency.
- Step-aware nudge moved it past the writes phase to the PR step, same as eval-28.
- Multiple `create_pull_request` attempts (4 in total) eventually succeeded. Loop detection did NOT trip — intervening reads varied the per-turn signature enough that counts never accumulated to threshold.

## What didn't

- Messier than eval-28: 16 file reads before first write (vs eval-28's 11). qwen3.6's exploratory style ran longer this time.
- 4 attempts at `create_pull_request` interleaved with reads before one succeeded — likely `head already has open PR` or similar 422-class errors on the early attempts.
- Second `create_branch` call at turn 29 (after the failed PR attempts) — the model may have decided to restart on a fresh branch.

## Verdict

Verdict: PASS

Confirms qwen3.6's reliability holds even when the run is "messy." The 28-turn count is on the high end of its range, but it still completed. See `docs/bakeoff-summary.md` for the comparative reliability finding.

## Next time

- Bake-off complete; no per-eval next-time items.
