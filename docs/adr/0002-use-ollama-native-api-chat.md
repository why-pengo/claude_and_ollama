# ADR-0002: Use Ollama-native `/api/chat` instead of `/v1/chat/completions`

- **Status:** Accepted
- **Date:** 2026-06-20

## Context

The initial direct-Ollama runner (PR #54) called Ollama's OpenAI-compatible endpoint `/v1/chat/completions` because it matched the request/response shape Goose had used and minimised the migration delta. That worked for the loop-ownership thesis but immediately constrained per-request control: the compat endpoint *silently drops* Ollama-specific `options.*` fields server-side. So `num_ctx`, `num_gpu`, `seed`, `temperature`, and every other Ollama-native knob was unreachable from the runner — exactly the offload-experiment surface `docs/offload-config.md` had documented as Modelfile-only under Goose.

That meant every model variant we wanted to A/B against had to be baked as a separate Ollama Modelfile, then `ollama create`'d as a distinct entry. Multiplying Modelfiles per option combination was the wrong altitude — the option set is small and orthogonal; the variants should be expressed at call site, not at model-creation site.

PR #80 switched `ollama_chat()` to native `/api/chat` and surfaced two CLI knobs — `--num-ctx N` and `--ollama-option key=value` (repeatable, coerced int/float/bool) — plus an optional `options:` block in the recipe YAML. CLI overrides recipe. Response shape adapter handles the few delta points (`message` at top level instead of inside `choices[0]`; native API omits `tool_call_id`, so the runner synthesises one).

## Decision

The runner calls Ollama's native `/api/chat` endpoint. Per-request options ship via the `options` field in the POST body. CLI flags (`--num-ctx`, `--ollama-option`) and recipe-level `options:` blocks are the user-facing surface for those knobs.

## Consequences

- Any Ollama option becomes reachable per-request without a Modelfile. Temperature studies (#89), context-size tuning, seed-pinning for reproducibility all happen at call site.
- The `modelfiles/` directory becomes load-bearing only for genuinely server-bound configuration (which on inspection turned out to be none for any model we kept). Deleted in PR #80 — see [ADR-0004](0004-go-all-api-driven.md).
- Response-shape divergence between OpenAI-compat and native means recipe authors and test fixtures need to expect the native shape. `tool_call_id` is synthesised by the runner; downstream code can keep treating it as opaque.
- Documentation of pre-#78 Modelfile-based offload tuning (`docs/offload-config.md`) is retained as historical reference but no longer reflects active configuration. The "Superseded in part by #78" admonition at the top of that file makes the boundary clear.

## References

- Issue: #78
- PR: [#80](https://github.com/why-pengo/claude_and_ollama/pull/80)
- Doc: `docs/offload-config.md` (sections covering Modelfile / Goose are now historical)
- Follows from: [ADR-0001](0001-replace-goose-with-direct-ollama-runner.md) — the runner owning the loop is what made this swap reachable.
