# Architecture Decision Records

Durable home for significant architectural decisions in this project. Each ADR is one file, numbered, immutable once Accepted. If a decision changes, write a new ADR that supersedes the old one — don't edit history.

See [`0000-template.md`](0000-template.md) for the blank starting point, and CLAUDE.md's "Architecture decisions" section for when to author a new one.

## Index

| # | Title | Summary | Status | Date |
|---|---|---|---|---|
| [0001](0001-replace-goose-with-direct-ollama-runner.md) | Replace Goose with a direct-Ollama runner | The runner owns the dispatch loop; Goose is retired. The architectural fix to the eval-19 exit-0-on-prose-only-turn reliability ceiling. | Accepted | 2026-06-14 |
| [0002](0002-use-ollama-native-api-chat.md) | Use Ollama-native `/api/chat` instead of `/v1/chat/completions` | Per-request Ollama options are first-class. CLI flags and recipe `options:` blocks. | Accepted | 2026-06-20 |
| [0003](0003-park-cpu-offload-as-production-lane.md) | Park CPU offload as a production lane | Partial-GPU offload raised the ceiling but hurt the floor. Model selection biases toward fully-VRAM-resident candidates. | Accepted | 2026-06-20 |
| [0004](0004-go-all-api-driven.md) | Go all-API-driven — retire per-model Modelfiles | Modelfiles retired. Variants expressed at call site, not at model-creation site. | Accepted | 2026-06-20 |
| [0005](0005-use-f16-kv-cache.md) | Use f16 KV cache (not q8_0) on the bazzite Ollama server | No thumb on the scale for the bake-off. KV cache stays at f16 across all candidates. | Accepted | 2026-06-20 |
| [0006](0006-qwen3-6-default-runner-model.md) | `qwen3.6:latest` is the default `RUNNER_MODEL` | Verbose-but-correct beats fast-but-fragile for a default. 3/3 PASS in the bake-off. | Superseded by [ADR-0008](0008-qwen25-coder-default-runner-model.md) | 2026-06-21 |
| [0007](0007-loop-detection-and-prose-rescue-are-load-bearing.md) | Loop detection and prose-shaped tool-call rescue are load-bearing, not optional | #85 and #84 are production features, not optional. Bake-off was only fair because both were on. | Accepted | 2026-06-20 |
| [0008](0008-qwen25-coder-default-runner-model.md) | `qwen2.5-coder:32b` at `temperature=0.2` is the default `RUNNER_MODEL` | Re-eval after #98 cleared the collision blocker: 3/3 PASS at 8.67 avg turns. Supersedes ADR-0006. | Accepted | 2026-06-27 |
| [0009](0009-mechanical-remediation-over-model-effort.md) | Deterministic gate failures are remediated mechanically, never delegated to the model | eval-40: the model oscillated on byte-exact formatting even with the diff in context; formatting has a perfect 0.5s mechanical solver. | Accepted | 2026-07-11 |

## Status legend

- **Proposed** — opened as part of an active debate, not yet in force.
- **Accepted** — in force. Most ADRs in this project are retroactive Accepted at filing time.
- **Deprecated** — the decision no longer applies and no replacement is needed.
- **Superseded by [ADR-NNNN]** — a newer ADR replaces this one; that newer ADR's Context section explains why.
