# eval-28 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen3.6:latest` (36B)
- Options: `{'num_ctx': 65536}` — qwen3.6's sweet-spot context (per-candidate ceiling on the 5090 at f16 KV)
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2`
- Pre-flight: 100% GPU resident at 65536
- First of 3 qwen3.6 runs in the #47 bake-off — baseline confirmation against the eval-22/23 results, now under the parked-offload / f16-KV / per-request `num_ctx` regime

## What worked

- End-to-end PASS at turn 23. PR opened on health_track, status comment posted on #51.
- Native `tool_calls` throughout — no rescue dependency.
- Exploratory but recoverable execution: 11 file reads before first write (qwen3.6's signature "look around first" style), then writes, then PR + comment.
- Step-aware nudge worked as designed — pushed the model from the writes phase to the PR step.

## What didn't

- One step-aware nudge needed at the writes→PR transition.
- Three separate `push_files` calls vs qwen3-coder's single one — qwen3.6 prefers smaller, file-at-a-time commits rather than bundling.
- A few `create_or_update_file` calls intermixed with the `push_files` series.

## Verdict

Verdict: PASS

Confirms qwen3.6 still drives the recipe cleanly under the new f16-KV / per-request configuration. Verbose but correct — the personality from eval-22/23 holds. Detailed comparison with the other candidates in `docs/bakeoff-summary.md`.

## Next time

- Bake-off complete; no per-eval next-time items.
