# ADR-0006: `qwen3.6:latest` is the default `RUNNER_MODEL`

- **Status:** Accepted
- **Date:** 2026-06-21

## Context

Issue #47 commissioned a bake-off across three candidates against the canonical `health_track#51` task — three runs each, identical recipe, identical configuration, on the post-offload-parked bazzite baseline (f16 KV per [ADR-0005](0005-use-f16-kv-cache.md), fully GPU-resident per [ADR-0003](0003-park-cpu-offload-as-production-lane.md)). The reliability scoreline:

| Candidate | PASS | PARTIAL | FAIL |
|---|---|---|---|
| **qwen3.6:latest** (MoE 36B total, ~3–5B active) | **3/3** | 0 | 0 |
| qwen3-coder:30b-a3b-q4_K_M | 2/3 | 1/3 | 0 |
| qwen2.5-coder:32b | 1/3 | 1/3 | 1/3 |

qwen3.6 is verbose-but-correct: always needs at least one step-aware nudge to push from write phase into `create_pull_request`, takes ~24 turns when passing, but lands every time. qwen3-coder is faster (16–28 turns) but exhibits a post-PR overshoot loop that #85 has to catch. qwen2.5-coder is extreme variance: a 9-turn PASS in eval-30 (cleanest run in project history at the time) alongside a FAIL in eval-30c. For a production-default decision, the floor matters more than the ceiling.

The decision was reaffirmed under temperature tuning (#89, see `docs/bakeoff-summary.md` Appendix A): low temperature is not a uniform reliability lever — it helps the prose-channel candidate (qwen2.5-coder) but hurts the native-tool-call candidates (qwen3.6, qwen3-coder). Default temperature stays uniform at Ollama's 0.8.

## Decision

`qwen3.6:latest` is the default `RUNNER_MODEL` for `runner/run_recipe.py`. Override via the `RUNNER_MODEL` env var or `--model` flag for experiments and per-eval comparisons.

## Consequences

- Production runner expects qwen3.6's verbose-but-correct shape. The step-aware nudge mechanism stays load-bearing because qwen3.6 reliably uses it (a one-nudge-per-run rhythm).
- The bake-off methodology — 3-of-3 per candidate, same task, same configuration — becomes the bar for any future default-model change. Single-shot wins like eval-30's 9-turn PASS don't override floor performance.
- Code-quality across candidates is not assessed by this ADR (see #47 subtask 5). Reliability is one axis; correctness of the produced PRs is the other. A future code-quality review could revise this ranking without contradicting the reliability data.
- Conditions to re-evaluate this default are documented in `docs/bakeoff-summary.md`'s "Recommendation" section. The most concrete trigger: qwen2.5-coder at `temperature=0.2` after #98 closed the within-batch branch-slug collision — a clean rerun is now possible and could plausibly tighten that candidate to 3/3.

## References

- Issue: #47
- PR: [#90](https://github.com/why-pengo/claude_and_ollama/pull/90) (recommendation), [#94](https://github.com/why-pengo/claude_and_ollama/pull/94) (per-call metrics for future re-runs), [#96](https://github.com/why-pengo/claude_and_ollama/pull/96) (temperature investigation that reaffirmed)
- Evals: `evals/eval-27/`, `evals/eval-28/`, `evals/eval-30/` series (the bake-off scoreline)
- Doc: `docs/bakeoff-summary.md` (full methodology, per-candidate analysis, Appendix A on temperature)
- Related: [ADR-0003](0003-park-cpu-offload-as-production-lane.md), [ADR-0005](0005-use-f16-kv-cache.md) (the configuration the bake-off ran against), [ADR-0007](0007-loop-detection-and-prose-rescue-are-load-bearing.md) (rescue mechanisms that the bake-off relied on)
