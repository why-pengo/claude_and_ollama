# ADR-0003: Park CPU offload as a production lane

- **Status:** Accepted
- **Date:** 2026-06-20

## Context

The eval-25 series tested whether partial-GPU offload could make `llama3.3:70b-instruct-q3_K_M` viable on bazzite's 32 GB VRAM. eval-25c was the first end-to-end recipe completion in project history (22 turns), which made offload look like a real production lane. eval-26 then collapsed at turn 25 with the same model and same options — the throughput-vs-context curve halves `tg` past ~70K context, and the runs were operating deep into that ugly part of the curve.

The variance review concluded: offload raises the *ceiling* (a 70B model that wouldn't otherwise fit becomes addressable) but hurts the *floor* (the same configuration that PASSed once collapsed under wall-clock and turn-coherence stress). For a harness whose goal is a reliable two-agent loop, reliability comes from the floor. The right move was to bias model selection toward candidates that fit fully GPU-resident at production context sizes — qwen3.6 + salvage was already delivering 100% review-able PRs on the in-VRAM lane.

## Decision

Partial-GPU offload is parked as a production lane for the runner. Future model selection biases toward candidates that fit fully in VRAM at the target context size. `docs/offload-config.md` is retained as a diagnostic reference (the curve-and-knob inventory is still correct) but is no longer a tuning roadmap.

## Consequences

- The model menu shrinks: 70B-class candidates are off-table on the current hardware. qwen3.6, qwen3-coder, qwen2.5-coder, and similar smaller-or-MoE models are the bake-off field.
- Eval methodology gains a hard pre-flight check: every candidate must be 100% GPU-resident at its target `num_ctx` before counting. `/api/ps` confirms `processor: 100% GPU`.
- The "what if a future model genuinely needs CPU offload" question stays open. The bar to revisit this ADR is higher than a single ceiling demonstration like eval-25c — the threshold is a candidate that *consistently* outperforms qwen3.6 under CPU spillover, which we have no evidence anyone has produced.
- Server-side env knobs that only mattered for offload survivability (e.g. `OLLAMA_KV_CACHE_TYPE=q8_0`) lose their motivation — see [ADR-0005](0005-use-f16-kv-cache.md).
- llama.cpp's `--n-cpu-moe` and `--no-kv-offload` are still unreachable through Ollama. That fact no longer matters under this decision but the inventory in `docs/offload-config.md` keeps it documented in case future hardware changes the calculus.

## References

- Evals: `evals/eval-25b/`, `evals/eval-25c/`, `evals/eval-26/` (the ceiling-vs-floor data)
- Doc: `docs/offload-config.md` (retained as diagnostic; "parked" admonition at top of file)
- Related: [ADR-0004](0004-go-all-api-driven.md), [ADR-0005](0005-use-f16-kv-cache.md), [ADR-0006](0006-qwen3-6-default-runner-model.md) — all downstream of this call
