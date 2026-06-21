# eval-30c result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen2.5-coder:32b`
- Options: `{'num_ctx': 98304}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2`
- Pre-flight: 100% GPU resident at 98304
- Third of 3 qwen2.5-coder runs in the #47 bake-off (post-#84)

## What worked

- First 7 of 11 turns rescued cleanly via #84 — got through AGENTS.md read, issue read, branch creation, one `create_or_update_file`, and a status comment.

## What didn't

- **At turn 7, model emitted an 18,689-character prose blob.** Likely trying to inline a full file's worth of source code as commentary/narrative rather than as a `create_or_update_file` argument. The rescue's JSON parser doesn't handle blobs of that shape (no balanced `{...}` containing a tool call; the content reads as a long markdown-shaped narrative).
- Runner nudged. Model produced one more rescuable call (`create_branch`), then emitted three more prose-only turns (1128, 1128, 490 chars — the 1128 repetition suggests a near-stable but non-tool-call state in the model's context).
- 3-empty-turn guard fired at turn 11.
- Salvage opted out: PR #81 (from eval-30b's run) already existed on the same branch slug.

## Verdict

Verdict: FAIL

No new artifact from this run. Different failure mode from eval-29: there the model emitted *clean* tool-call JSON in the wrong channel (rescue covered it once #84 existed). Here the model emitted a *non-tool-shaped* prose blob that the rescue can't recover from. This is the variance qwen2.5-coder shows under default temperature — not a rescue gap.

## Next time

- Bake-off complete; no per-eval next-time items.
- The 18,689-char prose blob is a candidate for #89's temperature-tuning investigation. At lower temperature, the model would be more likely to stay on the high-probability `create_or_update_file` token path rather than drifting into a narrative emission of file contents.
- Loop detection (#85) wasn't the guard that fired here — the empty-turn guard was. That's the right one for this failure shape (model produced no parseable tool call, repeated state), not loop detection (no repeated signatures).
