# ADR-0005: Use f16 KV cache (not q8_0) on the bazzite Ollama server

- **Status:** Accepted
- **Date:** 2026-06-20

## Context

During the eval-25 series, `OLLAMA_KV_CACHE_TYPE=q8_0` (paired with `OLLAMA_FLASH_ATTENTION=1`) was set server-side on bazzite to quantize the KV cache and squeeze a 70B q3 model into VRAM. It worked for survivability — eval-25c was the first end-to-end PASS in project history — but it applies to *every* model loaded under that server, not just the one that needed it.

Once [ADR-0003](0003-park-cpu-offload-as-production-lane.md) parked offload, the q8_0 KV setting's motivation evaporated. Quantizing KV across every candidate adds a quality confound to the #47 bake-off — code-tuned models in particular lean on attention precision, and silently halving it server-wide while comparing candidates isn't a fair test. The "no thumb on the scale" stance was the only defensible bake-off configuration.

## Decision

`OLLAMA_KV_CACHE_TYPE` is unset on `scripts/start-ollama-bazzite.sh`. The KV cache runs at f16 default. `OLLAMA_FLASH_ATTENTION=1` stays on (it doesn't quantize anything; it improves the attention kernel path). This is the bake-off-comparable baseline; every model fields the same KV precision.

## Consequences

- Bake-off comparisons are fair across candidates. The reliability ranking out of the #47 bake-off is interpretable as model-quality differences, not as candidate-times-server-config interactions.
- Aggregate VRAM headroom shrinks slightly because KV is now f16. Candidates that fit at their target context under q8_0 may need a smaller `num_ctx` under f16. Pre-flight `/api/ps` checks catch this before counting runs.
- If a future model genuinely needs q8_0 KV to fit (and is otherwise a strong candidate), revisit this ADR rather than silently flipping the env back. The bake-off-quality cost of server-wide KV quantization needs to be reckoned with explicitly.
- Server-bound vs per-model: Ollama doesn't expose KV cache type as a per-request option, so this stays server-side. A genuinely per-model KV-type need would force a Modelfile back into play, which intersects with [ADR-0004](0004-go-all-api-driven.md). The header comment in `start-ollama-bazzite.sh` flags this trade-off.

## References

- Script: `scripts/start-ollama-bazzite.sh` (header comment documents the "intentionally NOT here" rationale)
- Eval that motivated q8_0 in the first place: `evals/eval-25c/`
- Follows from: [ADR-0003](0003-park-cpu-offload-as-production-lane.md)
- Bake-off: `docs/bakeoff-summary.md` (uses f16 KV throughout)
