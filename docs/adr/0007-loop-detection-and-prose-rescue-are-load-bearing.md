# ADR-0007: Loop detection and prose-shaped tool-call rescue are load-bearing, not optional

- **Status:** Accepted
- **Date:** 2026-06-20

## Context

Two model-side failure modes surfaced in close succession after the runner replaced Goose. Both look like "model didn't make a tool call" to a naive dispatch loop, but they need different responses.

**Sampling-collapse loops (eval-26).** `llama3.3:70b-instruct-q3_K_M` burned its full 60-turn budget alternating identical `github__get_file_contents` calls with identical prose blobs targeting `routers/hydration.py`. The existing 3-consecutive-empty-turn guard never fired because the tool-call turns kept resetting the counter. The runner had no way to notice "this is the same turn 12 times in a row" — every individual turn was structurally valid; the *signature pattern across turns* was the failure.

**Prose-channel tool calls (eval-29).** `qwen2.5-coder:32b` emitted well-formed tool-call JSON (`{"name": "github__get_file_contents", "arguments": {...}}`) but in the content channel instead of the structured `tool_calls` field. The runner saw no tool calls, hit the 3-empty-turn guard at turn 3, and exited with zero artifact. Re-classification at write-up time: this is a *harness coverage gap*, not a model competence gap. The model knew the right tool. The model knew the right argument shape. The model produced clean JSON. The runner couldn't see any of it.

PRs #86 (loop detection, #85) and #87 (prose rescue, #84) added the two missing mechanisms:

- **Loop detection.** Computes a hashable signature per assistant turn (tool name + canonical args, or prose-content hash). When any signature repeats N times since the last successful new tool name (`--loop-detect-threshold`, default 4), abort. Catches sampling-collapse without false-positiving legitimate "read, look at it, read again to verify" sequences.
- **Prose rescue.** Parses prose content for tool-call-shaped JSON. Recognises both the OpenAI `arguments` and llama `parameters` conventions, the `{"type": "function"}` wrapper, and normalises `github_X` → `github__X`. Refuses unknown tool names so it can't dispatch garbage.

Both have been load-bearing in production since: #85 fired in eval-27c and eval-30b (cutting wasted-turn budgets ~in half); #84 rescued every qwen2.5-coder turn in eval-30 (without it that candidate is unusable).

## Decision

Loop detection (#85) and prose-shaped tool-call rescue (#84) are load-bearing runner features, not optional rescues. They run on every session by default. `--no-loop-detect` exists for debugging legitimately-repetitive runs but is not a recommended production setting. The runner ships with both active.

## Consequences

- Any future model candidate that doesn't use native `tool_calls` is still evaluable. The bake-off field (#47) was only fair to qwen2.5-coder because #84 was active. Future candidates with weak tool-channel discipline land on the same footing.
- Wall-clock and turn budget are recoverable from sampling-collapse loops. Without #85 a stuck run consumes `max_turns × turn_timeout` before exiting; with #85 it bails after `loop_detect_threshold` repeats.
- The two mechanisms are tested in `tests/test_run_recipe.py` (TestRunSessionLoopDetect, TestRunSessionProseRescue, TestParseProseToolCall, TestTurnSignature). Changing them in a way that breaks those tests is a deliberate harness-quality decision, not a refactor detail.
- Recipe authors can rely on "if the model emits parseable tool-call JSON, it will be dispatched." Recipe text can lean on that — "your NEXT TOOL CALL must be X" works whether the model emits X in `tool_calls` or in content.
- The Goose-era loss-of-frame anti-patterns ("delegate to sub-agent", "Ready to create the X") are still possible — those are *prose without tool-call JSON*, which the rescue legitimately can't recover. The system prompt's "Every turn is a tool call" section still has to name those out explicitly.

## References

- Issues: #84 (prose rescue), #85 (loop detection)
- PRs: [#86](https://github.com/why-pengo/claude_and_ollama/pull/86) (loop detection), [#87](https://github.com/why-pengo/claude_and_ollama/pull/87) (prose rescue)
- Evals: `evals/eval-26/` (sampling-collapse motivating #85), `evals/eval-29/` (prose-channel motivating #84), `evals/eval-27/`, `evals/eval-30/` (both mechanisms firing in bake-off runs)
- Doc: `docs/bakeoff-summary.md` (key findings #2 and #3 reiterate that both are load-bearing)
- Code: `runner/run_recipe.py` — `parse_prose_tool_call`, `turn_signature`, `run_session` loop-detect block
