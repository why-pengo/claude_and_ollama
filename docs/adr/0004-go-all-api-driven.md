# ADR-0004: Go all-API-driven — retire per-model Modelfiles

- **Status:** Accepted
- **Date:** 2026-06-20

## Context

Modelfiles were the only Ollama-native lever for offload tuning under Goose (`docs/offload-config.md`'s "Modelfile is the only Ollama-native lever" framing). Each variant was a separate `ollama create`'d entry, so different offload profiles became clean A/B candidates — but at the cost of bake-off arithmetic blowing up: M models × N option combinations means M×N Modelfiles to maintain.

Two upstream decisions changed the picture together:

- [ADR-0002](0002-use-ollama-native-api-chat.md): native `/api/chat` makes every Ollama option settable per-request.
- [ADR-0003](0003-park-cpu-offload-as-production-lane.md): we no longer need the bottom rows of the offload-knob table at all.

What's left for Modelfiles to do? In principle: server-side defaults that should ride with the model rather than the call site. On inspection of every Modelfile in `modelfiles/` at the time of PR #80, every `PARAMETER` directive in active use mapped to a per-request `/api/chat` option. None remained server-bound.

## Decision

Modelfile-based per-model pre-configuration is retired. Pulled stock Ollama models are the only model entries on bazzite. Variants are expressed at the call site via `--num-ctx`, `--ollama-option key=value`, or the recipe's `options:` block. The `modelfiles/` directory is dropped (PR #80 deleted `llama3.3-70b-offload.Modelfile`, the last live entry).

## Consequences

- Bake-off methodology simplifies. The N option combinations live in CLI flags and eval scripts, not in Ollama state. No `ollama create` step before a new variant — just pass the options.
- Bazzite's `ollama list` is now a clean mirror of upstream model identities. Audit-trail diffs (`/api/show` output) are interpretable against the public registry rather than against bespoke local variants.
- The server-side `start-ollama-bazzite.sh` script becomes the only place for genuinely server-wide configuration. Its header comment documents the "what's intentionally NOT here" choices — see [ADR-0005](0005-use-f16-kv-cache.md).
- If a future model genuinely requires server-bound configuration (a parameter Ollama doesn't expose per-request), reckon with the all-API-driven direction before adding a Modelfile back. The header comment in `start-ollama-bazzite.sh` flags this explicitly.

## References

- PR: [#80](https://github.com/why-pengo/claude_and_ollama/pull/80) (deleted the last live Modelfile)
- Doc: `docs/offload-config.md` (Modelfile sections retained as historical)
- Follows from: [ADR-0002](0002-use-ollama-native-api-chat.md), [ADR-0003](0003-park-cpu-offload-as-production-lane.md)
