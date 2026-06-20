# eval-30 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen2.5-coder:32b`
- Options: `{'num_ctx': 98304}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2`
- Pre-flight: 100% GPU resident at 98304
- **First qwen2.5-coder run with PR #87 (#84 prose-shaped-tool-call rescue) active.** First of the post-#84 3-of-3 trio.

## What worked

- **Cleanest run in the project's history. 9 turns end-to-end.** PR #81 opened on health_track, status comment posted on #51.
- **Every single turn rescued by #84** — the model never once used native `tool_calls`:
  ```
  [runner: rescued prose-shaped tool call → github__get_file_contents]
  [runner: rescued prose-shaped tool call → github__issue_read]
  [runner: rescued prose-shaped tool call → github__create_branch]
  [runner: rescued prose-shaped tool call → github__create_or_update_file]
  [runner: rescued prose-shaped tool call → github__get_file_contents]
  [runner: rescued prose-shaped tool call → github__create_or_update_file]
  [runner: rescued prose-shaped tool call → github__create_or_update_file]
  [runner: rescued prose-shaped tool call → github__create_pull_request]
  [runner: rescued prose-shaped tool call → github__add_issue_comment]
  ```
- Recipe completed at turn 9 — fewer turns than any previous PASS in any eval.

## What didn't

- Nothing on this run. The model executed cleanly with rescue carrying every tool call.

## Verdict

Verdict: **PASS**

Proves #84 closes the eval-29 gap. With the rescue active, qwen2.5-coder:32b becomes a viable runner candidate — and a remarkably fast one when it executes cleanly. Whether this 9-turn cleanness is reproducible is the question 30b and 30c answer (spoiler: it's not — see `docs/bakeoff-summary.md` for the variance picture).

## Next time

- Bake-off complete; no per-eval next-time items.
- The 9-turn baseline here makes a strong case that *if* qwen2.5-coder's variance can be tightened (e.g. via temperature tuning per #89), it could be the speed-winner candidate worth promoting.
