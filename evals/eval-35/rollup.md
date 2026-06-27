# eval-35 trio roll-up — qwen2.5-coder@temperature=0.2 re-eval (#101)

3-of-3 re-eval of `qwen2.5-coder:32b` at `temperature=0.2` against `why-pengo/health_track#51`, the canonical bake-off task, now that PR #98 has eliminated the within-batch branch-slug collision failure mode that drove eval-31c's PARTIAL.

## Scoreline

| Run | Verdict | Turns | Wall | Branch | PR | Model self-label |
|---|---|---|---|---|---|---|
| eval-35 | **PASS** | 8 | 93.4s | `runner/issue-51-20260627-081006` | [#91](https://github.com/why-pengo/health_track/pull/91) | ✅ done |
| eval-35b | **PASS** | 8 | 95.3s | `runner/issue-51-20260627-081227` | [#92](https://github.com/why-pengo/health_track/pull/92) | ⚠️ partial |
| eval-35c | **PASS** | 10 | 102.7s | `runner/issue-51-20260627-081519` | [#93](https://github.com/why-pengo/health_track/pull/93) | ✅ done |
| **Aggregate** | **3/3 PASS** | **8.67 avg** | **97.1s avg** | — | — | — |

All three runs back-to-back, no manual state reset between them (per #98), warm model throughout.

## Comparison to the bake-off

| Candidate | PASS | PARTIAL | FAIL | Avg turns (PASS) |
|---|---|---|---|---|
| qwen3.6:latest (current default, ADR-0006) | 3/3 | 0 | 0 | 24 |
| qwen3-coder:30b-a3b-q4_K_M | 2/3 | 1/3 | 0 | 17 |
| qwen2.5-coder:32b (default temp, pre-#98) | 1/3 | 1/3 | 1/3 | 9 (single run) |
| **qwen2.5-coder:32b @ temp=0.2 (post-#98, this re-eval)** | **3/3** | **0** | **0** | **8.67** |

qwen2.5-coder @ 0.2 + #98 is now the **only candidate other than qwen3.6 to clear 3/3 PASS**, and it does so in roughly **one-third the turn count** (8.67 vs 24) and roughly **one-third the wall time** (~97s vs qwen3.6's typical ~250-300s PASSes).

## What changed since the bake-off

1. **#98 (runner-owned branch naming via templated `{{ branch }}`)** eliminated the branch-slug collision that drove eval-31c's PARTIAL. Three back-to-back runs against the same task now each get distinct `runner/issue-51-<timestamp>` branches; `create_branch` and `create_pull_request` succeed first-try every time.
2. **`temperature=0.2`** suppresses the giant-prose-blob failure mode that drove eval-30c's FAIL at default temp (the 18,689-char prose blob that overwhelmed #84's JSON parser). Across these three runs no prose blob exceeded the parseable limit.
3. The combination of #98 + temp=0.2 collapses qwen2.5-coder's previously-extreme variance (9 / 28 / 11 turns at default temp) into a tight cluster (8 / 8 / 10 turns).

## Failure modes observed

- Runner axis: **none.** No collisions, no 422 errors, no loop-detect engagement, no nudge cascades beyond the standard "commit done — now open the PR" prompt.
- Artifact axis (out of scope for #101 verdict but worth recording): committed-file completeness varied between runs. eval-35 and eval-35b committed 2 files (schema + service); eval-35c committed 4 files (schema + service + router + test file). All three omitted the `main.py` router registration. This variance is at the model-decision layer (which subtasks to attempt), not the runner-completion layer (which is uniformly PASS). The #47 subtask 5 axis is the right place for this.

## Trade-offs to acknowledge

| Axis | qwen3.6 (current) | qwen2.5-coder @ 0.2 |
|---|---|---|
| 3/3 PASS | ✅ | ✅ |
| Avg turns (PASS) | 24 | 8.67 (~2.8x faster) |
| Avg wall (PASS) | ~250-300s | ~97s (~2.5-3x faster) |
| Tool-call channel | 100% native `tool_calls` | 100% prose channel via #84 rescue |
| Single point of failure | None | If #84 rescue regresses, qwen2.5-coder breaks |
| Variance ceiling at this config | Bounded (3/3 in bake-off, eval-32 series clean) | Bounded across 5 runs at this config (eval-34 2/2 + eval-35 trio 3/3) — but historically high without #98 + temp=0.2 |

The rescue-dependency is the real trade. qwen2.5-coder cannot run without #84 — eval-29 proved that. Promoting it to default makes the rescue **load-bearing for default-case execution**, not just for one alternative candidate.

Mitigation: #84 has been stable across all evals since landing. The rescue path has test coverage. The risk is bounded by the test suite + the eval cadence catching any regression before it ships.

## GO/NOGO

**GO** — promote `qwen2.5-coder:32b` at `temperature=0.2` to the default `RUNNER_MODEL`, superseding ADR-0006.

The methodology bar (3/3 PASS) is cleared. The previously-flagged condition from the bake-off ("the speed advantage from eval-30's 9-turn outlier needs to actually reproduce for the switch to be worth the rescue-dependency trade") is met decisively: not one but three runs in the 8-10 turn band, with a tight wall-time cluster (~93-103s). The reliability characteristic that motivated keeping qwen3.6 (the variance ceiling) was specifically attacked by #98 + temp=0.2 and is now bounded across 5 consecutive successful runs (eval-34 2/2 + eval-35 trio 3/3).

The rescue-dependency trade-off is real but acceptable: #84 is stable, tested, and load-bearing for qwen2.5-coder regardless of its default status.

## Follow-through

1. Write ADR-0008 superseding ADR-0006 with the new evidence.
2. Update `docs/bakeoff-summary.md`'s recommendation section.
3. File a small follow-up implementation issue to flip the default in `runner/run_recipe.py` (`RUNNER_MODEL` default + any recipe-level `options:` block for `temperature=0.2`).
4. Post GO recommendation comment on #101.
