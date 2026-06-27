# ADR-0001: Replace Goose with a direct-Ollama runner

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

The original `claude_and_goose` harness drove execution through Goose 1.35.0, which owned the session loop: read the recipe, call the model, dispatch tool calls, decide when to stop. Across the eval-17 and eval-19 series (6 attempts total on the canonical `health_track#51` task), Goose terminated with exit 0 every time the model emitted a turn without a structured tool call — even though `GOOSE_MAX_TURNS=100` was nowhere near hit. The model would emit prose ("I have all the context I need..."), or a placeholder shell command, or simply nothing, and Goose treated the no-tool-call turn as session-complete.

The eval-19 writeup framed this as the *structural reliability ceiling*: harness-slimming experiments (cutting prompt mass ~70% in 6f1e55a) helped attempts get further on average but did not change the termination class. Whatever the model emitted that wasn't a tool call, Goose would exit 0 silently. No nudge, no continue prompt, no observable failure — just session end with zero commits, zero PRs.

The direct-Ollama runner (`runner/run_recipe.py`) was prototyped in PR #54 to test the hypothesis that the loop ownership *was* the ceiling. The runner POSTs to Ollama directly, owns the dispatch loop, and on a no-tool-call turn nudges the model to continue rather than exiting. Across eval-20, eval-22, eval-23 the runner produced **6 review-able artifacts in 6 attempts** with salvage active (vs Goose's 0-of-6 on the same target). The architectural thesis was validated end-to-end.

## Decision

The runner owns the execution loop. Goose is retired from this project. All future runner work happens against `runner/run_recipe.py`; the harness writes its own dispatch, nudge, and salvage logic; `github__*` tools are wrappers around the `gh` CLI directly.

## Consequences

- The harness can intervene when the model stops emitting tool calls — nudges, step-aware continue prompts, and the salvage fallback are all reachable because the runner owns the loop.
- Tool call shape is no longer constrained by Goose's OpenAI-compat surface. Native Ollama options (`num_ctx`, `num_gpu`, `seed`, `temperature`, ...) become reachable — see [ADR-0002](0002-use-ollama-native-api-chat.md).
- All session telemetry (per-turn metrics, prompt size, generation rate, tool-call channel discipline) is observable in the runner because the runner is what makes the API calls.
- The harness now carries the full weight of "what should the model do next when it doesn't know" — see [ADR-0007](0007-loop-detection-and-prose-rescue-are-load-bearing.md). What used to be a Goose feature became our problem to solve.
- Older eval directories (`evals/eval-NN/goose-session.log`) keep their original filenames for audit-trail honesty. Don't rename them.

## References

- Issue: #43, #45 (the eval-17/eval-19 series that motivated the decision)
- PR: [#54](https://github.com/why-pengo/claude_and_ollama/pull/54) (initial runner + salvage), [#80](https://github.com/why-pengo/claude_and_ollama/pull/80) (native /api/chat)
- Evals: `evals/eval-17/`, `evals/eval-19/` (Goose's 0-of-6 ceiling); `evals/eval-20/`, `evals/eval-22/`, `evals/eval-23/` (runner validates the thesis)
- Doc: `docs/harness-complexity-audit.md` (the slimming experiment that ruled out prompt mass as the cause)
