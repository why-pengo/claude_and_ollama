# eval-24b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, resolved `base_branch=develop`
- Model: `qwen3.6:latest`
- Options: `(defaults)` — second smoke of #78's `/api/chat` swap, this time with the eval-24 salvage fix in place
- Runner branch: `chore/issue-78-native-api-chat` (PR #80, commit c93fbeb)
- Pre-run cleanup: deleted orphan branch `runner/issue-51-hydration-daily-endpoint` from eval-24 so the runner could recreate it from a clean base

## What worked

- `/api/chat` plumbing held up across another full session (12 turns).
- Model drove early steps the same way as eval-24: context read, branch created, schema authored at `backend/app/schemas/hydration.py`, committed to `runner/issue-51-hydration-daily-endpoint`.
- **Salvage fired cleanly when the model stalled** — no `TypeError` from `_extract_branch` this time. Marker output:
  ```
  === 3 consecutive no-tool-call turns; giving up (turn 12) ===

  === Salvage attempt: branch=runner/issue-51-hydration-daily-endpoint → base=develop ===
    ✓ Salvage PR opened: https://github.com/why-pengo/health_track/pull/74 (1 commits)
    ✓ Salvage comment posted: https://github.com/why-pengo/health_track/issues/51#issuecomment-4757354906
  ```
- Salvage PR #74: title matches the issue, body uses the standard salvage template (Closes #51, "Mechanical PR opened by the runner's salvage step", verification disclaimer, subtasks-not-auto-ticked note). Head `runner/issue-51-hydration-daily-endpoint`, base `develop`.
- Salvage comment on issue #51 carries the `⚠️ partial — salvaged PR:` marker and PR link.

## What didn't

- **Same model stall at step 5 (PR call).** qwen3.6 again fell into the prose-only-turn pattern after pushing the schema file (turn 12 this time vs. turn 18 in eval-24 — fewer recoverable nudges before tripping the limit). Pre-existing behavior, not a #78 regression. Salvage now mitigates it correctly under `/api/chat`.

Note: the run was piped through `tee evals/eval-24/session.log` (eval-24's path) rather than eval-24b's, so it initially overwrote eval-24's log. Recovered by copying the new content to `evals/eval-24b/session.log` and restoring the original eval-24 log from git HEAD (c93fbeb). Both files now reflect their correct runs.

## Verdict
Verdict: PASS (for #78's salvage path)

- `/api/chat` end-to-end ✅
- Salvage fix from c93fbeb works against native /api/chat dict arguments ✅
- Reproduced eval-24's stall pattern under the fix; salvage opened the PR + posted the comment that previously crashed ✅
- Model recipe-completion is still pre-existing PARTIAL, but that's outside #78's scope

## Next time

- eval-25: `llama3.3:70b-instruct-q3_K_M` with `--num-ctx 65536 --ollama-option num_gpu=30` — the second smoke criterion in #78. Bigger model context + first real options flow on the wire.
- Decide on PR #74's fate (incomplete implementation — typically the workflow would be close-don't-merge for salvaged-partial PRs; review and act before opening eval-25 so the branch can be reused or named differently).
- Eventually: consider whether the model-stall failure mode on step 5 warrants its own follow-up issue. It's now consistently reproducing on qwen3.6 + this recipe; that's a known signal, not noise.
