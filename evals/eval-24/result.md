# eval-24 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, resolved `base_branch=develop`
- Model: `qwen3.6:latest`
- Options: `(defaults)` — no `--num-ctx` or `--ollama-option` flags; first smoke of #78's `/api/chat` swap
- Runner branch: `chore/issue-78-native-api-chat` (PR #80, commit 5f84656)

## What worked

- `/api/chat` endpoint reachable end-to-end: request URL swap, native response envelope (`resp["message"]`), tool-call id synthesis on assistant message, dispatch loop, gh tool execution all flowed cleanly across 18 turns.
- Model successfully drove the early recipe steps: read `AGENTS.md`, read issue #51, browsed `backend/app/services/analytics.py`, `backend/app/routers/sleep.py`, the conftest, the record model, and authored a coherent `backend/app/schemas/hydration.py`.
- `github__push_files` committed the schema to branch `runner/issue-51-hydration-daily-endpoint`. The `mode` field defaulted correctly (no regression from the option-threading work).

## What didn't

- **Model stall at step 5 (PR call) — pre-existing.** After pushing the schema file, qwen3.6 fell into the eval-19/20 prose-only-turn pattern: 3 consecutive no-tool-call turns despite the step-aware nudge. Same failure shape this model has shown on this recipe before (eval-18). Not a regression introduced by #78.
- **Salvage path crashed — regression introduced by #78.** `_extract_branch` did `json.loads(tc["function"]["arguments"])` unconditionally. Native `/api/chat` returns `arguments` as a **dict**, not a JSON string → `TypeError: the JSON object must be str, bytes or bytearray, not dict`. The main dispatch loop already had the `TypeError` fallback for this shape; `_extract_branch` did not. Salvage died before it could open a mechanical PR from the partially-completed branch.

## Fix

Fixed in `chore/issue-78-native-api-chat` (post-eval-24 commit):
- `_extract_branch` now mirrors the dispatch loop's pattern: `json.loads` first, on `(JSONDecodeError, TypeError)` fall back to using `raw if isinstance(raw, dict) else {}`.
- Regression test `TestExtractBranch::test_handles_dict_arguments_from_native_api_chat` pins the dict-shape path.

`grep 'json.loads.*tc\["function"\]\["arguments"\]'` shows the two call sites (dispatch loop + extractor); both now handle both shapes.

## Verdict
Verdict: PARTIAL

- `/api/chat` plumbing works (primary acceptance criterion of #78) ✅
- Native arguments-as-dict revealed an unfixed callsite, now patched ✅
- Recipe loop did not complete to PR/comment, but the stall is a model-behavior issue with qwen3.6, not a #78 regression. Salvage now able to recover next run.

## Next time

- Re-run eval-24b on the same recipe/params with the salvage fix in place. Confirm salvage opens a mechanical PR from the orphaned branch when the model stalls at step 5 again.
- Then proceed to eval-25 (llama3.3:70b-instruct-q3_K_M with `--num-ctx 65536 --ollama-option num_gpu=30`) — that's the second smoke criterion in #78.
- Consider DRY-ing the `json.loads(args) → TypeError fallback` pattern into a helper if a third callsite appears.
