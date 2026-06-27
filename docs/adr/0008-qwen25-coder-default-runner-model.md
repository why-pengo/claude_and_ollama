# ADR-0008: `qwen2.5-coder:32b` at `temperature=0.2` is the default `RUNNER_MODEL`

- **Status:** Accepted
- **Date:** 2026-06-27

## Context

[ADR-0006](0006-qwen3-6-default-runner-model.md) made `qwen3.6:latest` the default `RUNNER_MODEL` because it was the only bake-off candidate to clear 3/3 PASS, and reliability dominated speed for a production default. At the time, qwen2.5-coder:32b's bake-off scoreline was 1 PASS + 1 PARTIAL + 1 FAIL — its 9-turn eval-30 PASS was the project's fastest run, but eval-30b's 28-turn loop and eval-30c's prose-blob FAIL ruled it out.

Two structural changes since then unlocked a re-evaluation:

1. **#89's temperature investigation** (`docs/bakeoff-summary.md` Appendix A) established that low temperature is the right setting *specifically for prose-channel models*. At `temperature=0.2`, qwen2.5-coder went 2 PASS + 1 PARTIAL — the remaining PARTIAL was the within-batch branch-slug collision, not model behaviour. The giant-prose-blob FAIL mode that doomed eval-30c didn't recur.
2. **#98 (runner-owned branch naming)** eliminated the within-batch branch-slug collision. The runner now generates `runner/issue-<N>-<YYYYMMDD-HHMMSS>` at session start; the model uses it via the templated `{{ branch }}` recipe param. Back-to-back invocations against the same task get distinct branches; `create_branch` and `create_pull_request` succeed first-try. eval-34 (the #98 shakedown) confirmed this with 2/2 qwen2.5-coder@0.2 PASSes against the worst-case combo.

Issue #101 commissioned the 3-of-3 re-eval that closes the loop. Eval-35 / eval-35b / eval-35c ran qwen2.5-coder:32b @ `temperature=0.2` back-to-back against `why-pengo/health_track#51` under the post-offload-parked configuration ([ADR-0003](0003-park-cpu-offload-as-production-lane.md), [ADR-0005](0005-use-f16-kv-cache.md)). All three PASSed:

| Run | Verdict | Turns | Wall | PR |
|---|---|---|---|---|
| eval-35 | PASS | 8 | 93.4s | health_track#91 |
| eval-35b | PASS | 8 | 95.3s | health_track#92 |
| eval-35c | PASS | 10 | 102.7s | health_track#93 |
| **Aggregate** | **3/3 PASS** | **8.67 avg** | **97.1s avg** | — |

Compared to qwen3.6's 3/3 PASS at 24-turn average: same reliability, ~2.8x fewer turns, ~2.5–3x less wall time. The "9-turn outlier needs to actually reproduce for the switch to be worth the rescue-dependency trade" condition flagged in the original bake-off summary's Notes is met decisively — three runs in the 8–10 turn band, not a single outlier. Across this new configuration the variance ceiling is bounded across five consecutive successful runs (eval-34 2/2 + eval-35 trio 3/3).

The trade-off accepted: qwen2.5-coder is 100% prose-channel — it cannot run without #84's rescue. Promoting it to default makes #84 load-bearing for the default-case execution path, not just for one alternative candidate. This is consistent with [ADR-0007](0007-loop-detection-and-prose-rescue-are-load-bearing.md)'s explicit framing of #84 as production-essential.

## Decision

`qwen2.5-coder:32b` at `temperature=0.2` becomes the default `RUNNER_MODEL` for `runner/run_recipe.py`. The runner will ship this candidate as its default and `recipes/execute-issue.yaml` will ship `temperature=0.2` as the default per-request Ollama option. Override paths stay unchanged: `RUNNER_MODEL` env var / `--model` flag for the model and `--ollama-option temperature=<value>` for the temperature.

This decision supersedes [ADR-0006](0006-qwen3-6-default-runner-model.md). qwen3.6:latest stops being the default and remains a fully-supported override target.

**Implementation staging.** This ADR records the decision; the code change lands in #103 (the follow-up implementation issue filed alongside the ADR's PR). At this ADR's merge time the runner's hardcoded `RUNNER_MODEL` default in `runner/run_recipe.py` still reads `qwen3.6:latest`. The decision-record change and the code change were deliberately split so each is reviewable in isolation. The ADR's status is Accepted because the decision itself is binding — no more debate, evidence is in (eval-35 trio), recommendation is GO — even though the line of code that reflects it lands in a separate PR.

## Consequences

Once #103 implements the flip:

- Production runner expects qwen2.5-coder's 100% prose-channel shape. #84's prose-shaped tool-call rescue becomes load-bearing for the default execution path, not just for an alternative candidate. Any regression to #84 affects default-case reliability immediately.
- Default-case PASS profile changes from "verbose-but-correct, ~24 turns, one nudge per run" to "tight, ~8–10 turns, occasional nudge from the empty-turn guard." Default wall-time-per-task drops from ~250–300s to ~100s.
- Default temperature is no longer Ollama's 0.8 — the recipe carries `temperature=0.2` as the default Ollama option. Per-candidate temperature overrides via `--ollama-option` continue to work; the runner's no-arg invocation ships the low-temp setting.
- qwen3.6:latest stays a fully-supported override candidate. The bake-off scoreline (3/3 PASS at default temp, 2/3 PASS at low temp per #89 Appendix A) remains the reference data for picking it as an override.

Independent of #103's merge:

- The bake-off methodology — 3-of-3 against the same canonical task, same configuration — stays the bar for default-model changes. This decision is the result of the methodology being applied a second time, against a different config (low temp + #98), and clearing it.
- Code-quality across candidates is still not assessed by this ADR (see #47 subtask 5). The eval-35 trio's artifacts varied in completeness (2-file, 2-file, 4-file commits across three runs against the same 5-subtask issue). Reliability is one axis; correctness of the produced PRs is the other.
- The mitigation for the rescue-dependency: #84 has been stable across every eval since landing, has direct test coverage in `tests/`, and the eval cadence catches regressions. If #84 ever needs to ship behind a feature flag, a qwen3.6 fallback recipe is a one-line override.

## References

- Issue: #101 (this investigation), #47 (the original bake-off), #89 (temperature investigation), #98 (runner-owned branch naming that eliminated the collision blocker), #103 (follow-up implementation of the default flip)
- PR: [#102](https://github.com/why-pengo/claude_and_ollama/pull/102) (this ADR + eval-35 trio + bake-off update)
- Evals: `evals/eval-35/`, `evals/eval-35b/`, `evals/eval-35c/` (the 3-of-3 re-eval), `evals/eval-34/` (#98 shakedown), `evals/eval-31/` series (the #89 temperature data this re-eval was predicted by)
- Doc: `docs/bakeoff-summary.md` (recommendation section updated alongside this ADR), `evals/eval-35/rollup.md` (full trio writeup)
- Related: [ADR-0006](0006-qwen3-6-default-runner-model.md) (superseded by this ADR), [ADR-0003](0003-park-cpu-offload-as-production-lane.md) and [ADR-0005](0005-use-f16-kv-cache.md) (the configuration the re-eval ran against), [ADR-0007](0007-loop-detection-and-prose-rescue-are-load-bearing.md) (the rescue this default now depends on)
