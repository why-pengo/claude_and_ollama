# eval-27 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, resolved `base_branch=develop`
- Model: `qwen3-coder:30b-a3b-q4_K_M` (MoE, ~30B / active ~3B, Q4_K_M)
- Options: `{'num_ctx': 102400}`
- Turn timeout: 600s
- Bazzite env: `OLLAMA_FLASH_ATTENTION=1`, **f16 KV** (`OLLAMA_KV_CACHE_TYPE` removed), `OLLAMA_DEBUG=1`
- Pre-flight: model warmed at `num_ctx=102400` and verified 100% GPU resident via `/api/ps` before kickoff
- First bake-off candidate under the new constraints from PR #81 (parked offload, f16 KV, per-request `num_ctx`)
- First end-to-end run with PR #86's loop-detect guard active (default `--loop-detect-threshold 4`)

## What worked — the headline

**Best end-to-end run in this project's history.** 16 turns, zero nudges, zero salvage intervention, zero loop-detect trips, zero prose-only turns. The model called a tool on every single turn from start to finish.

Final log line:

```
=== Recipe complete: PR + issue comment both fired (turn 16) ===
```

For comparison, the prior end-to-end milestone was eval-25c at 22 turns with `llama3.3:70b q3` under heavy CPU offload — also clean, but with substantially more friction and at ~1 t/s throughput. eval-27 reached the same recipe state in 27% fewer turns at much higher throughput.

### Tool-call trajectory (all 16 turns)

| Turn | Tool | Step |
|---|---|---|
| 1 | `github__get_file_contents` | AGENTS.md |
| 2 | `github__issue_read` | issue #51 |
| 3 | `github__create_branch` | from develop |
| 4–8 | `github__get_file_contents` (×5) | schema, analytics, sleep router, main.py, sleep tests |
| 9–13 | `github__create_or_update_file` (×5) | schema, analytics, router, main registration, tests |
| 14 | `github__push_files` | bundles the 5 files |
| 15 | `github__create_pull_request` | PR #76 opened |
| 16 | `github__add_issue_comment` | status comment on #51 |

Every read happens before the corresponding write. Every write goes to the correct path. The branch is created off `develop` (matching the resolved base). The PR targets `develop`. The status comment references the PR number.

### Artifact: PR #76 on `why-pengo/health_track`

- Title: `feat: GET /api/hydration/daily — combined per-day shape (sub-issue of #48)` (matches issue title, conventional commit prefix)
- Base: `develop`. Head: `runner/issue-51-get-api-hydration-daily-combined-per-day-shape-sub-issue-of-48`
- 5 files changed, +319 / −68 lines
- Body opens with `Closes #51` — issue will auto-close on merge
- All 5 subtasks from the issue accounted for in changed files:
  - `backend/app/schemas/hydration.py` (HydrationDaily schema)
  - `backend/app/services/analytics.py` (get_hydration_daily service function)
  - `backend/app/routers/hydration.py` (the endpoint)
  - `backend/app/main.py` (router registration)
  - `backend/tests/test_hydration.py` (tests)

## What didn't

Nothing in the runner-execution sense. The model drove the recipe cleanly without harness intervention.

Caveats for the bake-off summary (not failures of this run, but bookkeeping):

- **PR quality not yet reviewed.** The runner produced a PR, but whether the *code* is correct (mL→fl-oz conversion, JWT enforcement, missing-metric returns null not 0, tests actually exercise the acceptance criteria) is a separate human review pass. That's the "code quality" axis of #47.
- **No throughput numbers captured here.** `OLLAMA_DEBUG=1` was on during the run but the t/s curve under f16 KV at 100k context wasn't extracted from the serve log into this result. Worth doing as part of the bake-off summary so we can compare against the parked-offload curve in `docs/offload-config.md`.

## Verdict

Verdict: PASS

First fully-resident, f16-KV, native-tool-calling, end-to-end bake-off PASS. Sets a new baseline for what the runner is capable of when the model side cooperates.

## Next time

- Capture the t/s curve from the bazzite serve log (`OLLAMA_DEBUG=1` was on) and add it to the bake-off comparative summary. This is the first f16-KV data point — directly comparable to the eval-26-era q8_0 curve in `docs/offload-config.md`.
- Human-review PR #76's code: correctness, conversion accuracy, JWT enforcement, test coverage of the issue's acceptance criteria. That's the "PR quality" axis for #47 that turn-count alone doesn't speak to.
- Run the qwen3.6 baseline confirmation at `--num-ctx 65536` (its sweet-spot context) and the `qwen2.5-coder:32b` rerun at `--num-ctx 96000` to fill out the bake-off comparative table.
- Worth a separate explicit check whether the `OLLAMA_DEBUG=1` log output is large enough to want rotation set up before running 2–3 more candidates back to back.
