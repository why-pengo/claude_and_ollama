# eval-25b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, resolved `base_branch=develop`
- Model: `llama3.3:70b-instruct-q3_K_M`
- Options: `{'num_ctx': 131072, 'num_gpu': 30}` — first eval with options on the wire at 131K context
- Runner branch: `chore/issue-78-native-api-chat` (PR #80, commit 14a358b)
- Bazzite env: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` enabled via fresh `start-with-kv-quant.sh` restart

## What worked

- **Options reached the loader, verified via `/api/ps`:**
  ```json
  { "name": "llama3.3:70b-instruct-q3_K_M",
    "context": 131072, "size_total_gb": 58, "size_vram_gb": 22,
    "processor": "38% GPU" }
  ```
  `num_ctx=131072` and `num_gpu=30` both honored on reload. KV quant verified earlier in the pre-eval smoke (size dropped 56→46 GB at 65K context after the env switch).
- **Recipe loop made real progress** — 11 tool calls in before timeout, going further than qwen3.6 ever did in eval-24/24b:
  - github__get_file_contents (AGENTS.md)
  - github__issue_read (#51)
  - github__add_issue_comment (status comment)
  - github__issue_read (re-read, possibly for context refresh)
  - github__create_branch × 2 (`runner/issue-51-hydration-daily-endpoint`)
  - github__get_file_contents × 8 (codebase exploration — analytics.py, sleep router, conftest, schemas/, routers/, main.py, record model, etc.)
- Throughput steady at `tg = 1.29 t/s` per the bazzite server log — expected for 70B q3 at 37% GPU offload (memory-bandwidth bound on the CPU side).

## What didn't

- **`httpx.ReadTimeout: timed out`** during turn ~12, mid-generation (probably writing the schema file content).
- Root cause: `runner/run_recipe.py` had `httpx.Client(timeout=600.0)` hardcoded. At 1.29 t/s, that caps a single response at ~770 generated tokens before httpx raises. Fine for qwen3.6 at ~30 t/s; chokes a 70B writing real code.
- Salvage didn't fire because the timeout raised out of `ollama_chat()` directly (not via the 3-no-tool-call path that wraps in `attempt_salvage`). Branch was created but no commits landed; orphan was cleaned up before this writeup (branch already 404 by the time I checked).

## Fix

Added `--turn-timeout SECONDS` CLI flag (default 600 — preserves current behavior for qwen3.6 evals). Threaded through `run_session` → `httpx.Client(timeout=N)`. The session header now prints `Turn timeout: Ns` for log visibility.

For eval-25c, pass `--turn-timeout 3600` (1h per turn — generous enough for any single response at 1.3 t/s throughput).

## Verdict
Verdict: PARTIAL

- ✅ Per-request options end-to-end on `/api/chat` — `num_ctx=131072` and `num_gpu=30` both reached the loader and the model honored them
- ✅ 70B-class model running productively at 11 tool calls deep (vs. ~5 for qwen3.6 before stall)
- ❌ Recipe didn't complete due to harness timeout, not model behavior
- ✅ Timeout fix landed in this PR; eval-25c will retest with the new flag

## Next time

- eval-25c: same params, add `--turn-timeout 3600`. Caps the second smoke criterion in #78 properly.
- The encouraging signal — 11 tool calls and still going strong — is a positive data point for #47's "does model scale matter?" question, but premature to conclude until a full run completes.
- Consider whether the hardcoded 600s default should bump given how easy it is to hit on 70B-class. Leaving at 600 keeps backwards compatibility for the qwen3.6 cycle, but a doc note on `--turn-timeout` in CLAUDE.md may save future-Jon a re-rerun.
