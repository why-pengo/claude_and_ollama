# eval-33b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen3.6:latest` on `bazzite.local`
- Options: `num_ctx=65536`, `temperature=0.2`
- Back-to-back after eval-33. Model warm.

## What worked

- 19 turns to recipe complete. PR and comment both fired by the model.
- Native `tool_calls` end-to-end (zero rescues — qwen3.6 keeps its bake-off discipline at low temp).
- 1 nudge fired (the "you have committed files, now open the PR" step-aware nudge) — same shape as eval-28b at default temp.

## What didn't

- The 1 nudge is the canonical qwen3.6 pattern — model commits files, then needs a poke to advance to `create_pull_request`. Default temp showed the same shape. Not a regression.
- 7437-token gen on turn that triggered the nudge — the model produced a long natural-language summary of what it had done instead of moving to step 5. The runner's nudge re-anchored it to the recipe and step 5 fired immediately after.

## Verdict

Verdict: PASS

## Notes

- `[session metrics: turns=19 | prompt=716441 tok @ 42929.5 t/s | gen=36082 tok @ 216.4 t/s | wall=189.3s]`
- 19 turns is faster than the default-temp baseline's 21–28 turns (eval-28/28b/28c). The verbose-but-correct pattern compressed slightly under low temp.
- Gen rate 216 t/s, consistent with qwen3.6's MoE active-params signature.
