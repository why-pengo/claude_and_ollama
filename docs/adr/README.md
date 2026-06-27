# Architecture Decision Records

Durable home for significant architectural decisions in this project. Each ADR is one file, numbered, immutable once Accepted. If a decision changes, write a new ADR that supersedes the old one — don't edit history.

See [`0000-template.md`](0000-template.md) for the blank starting point, and CLAUDE.md's "Architecture decisions" section for when to author a new one.

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-replace-goose-with-direct-ollama-runner.md) | Replace Goose with a direct-Ollama runner | Accepted | 2026-06-14 |
| [0002](0002-use-ollama-native-api-chat.md) | Use Ollama-native `/api/chat` instead of `/v1/chat/completions` | Accepted | 2026-06-20 |
| [0003](0003-park-cpu-offload-as-production-lane.md) | Park CPU offload as a production lane | Accepted | 2026-06-20 |
| [0004](0004-go-all-api-driven.md) | Go all-API-driven — retire per-model Modelfiles | Accepted | 2026-06-20 |
| [0005](0005-use-f16-kv-cache.md) | Use f16 KV cache (not q8_0) on the bazzite Ollama server | Accepted | 2026-06-20 |
| [0006](0006-qwen3-6-default-runner-model.md) | `qwen3.6:latest` is the default `RUNNER_MODEL` | Accepted | 2026-06-21 |
| [0007](0007-loop-detection-and-prose-rescue-are-load-bearing.md) | Loop detection and prose-shaped tool-call rescue are load-bearing, not optional | Accepted | 2026-06-20 |

## One-liners

- **0001 (Goose → runner):** The runner owns the dispatch loop; Goose is retired. The architectural fix to the eval-19 exit-0-on-prose-only-turn reliability ceiling.
- **0002 (/api/chat):** Per-request Ollama options are first-class. CLI flags and recipe `options:` blocks.
- **0003 (offload parked):** Partial-GPU offload raised the ceiling but hurt the floor. Model selection biases toward fully-VRAM-resident candidates.
- **0004 (all-API-driven):** Modelfiles retired. Variants expressed at call site, not at model-creation site.
- **0005 (f16 KV):** No thumb on the scale for the bake-off. KV cache stays at f16 across all candidates.
- **0006 (qwen3.6 default):** Verbose-but-correct beats fast-but-fragile for a default. 3/3 PASS in the bake-off.
- **0007 (rescues load-bearing):** Loop detection (#85) and prose-shaped tool-call rescue (#84) are production features, not optional. Bake-off was only fair because both were on.

## Status legend

- **Proposed** — opened as part of an active debate, not yet in force.
- **Accepted** — in force. Most ADRs in this project are retroactive Accepted at filing time.
- **Deprecated** — the decision no longer applies and no replacement is needed.
- **Superseded by [ADR-NNNN]** — a newer ADR replaces this one; that newer ADR's Context section explains why.
