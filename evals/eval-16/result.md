# eval-16 result

Second model-swap experiment under #50, after eval-15's Llama 3.3 70B Q3 attempt was invalidated by tool-call integration issues. This run swapped to `qwen2.5-coder:32b` — a code-tuned 32B model that fits GPU-only (no offload), tested in eval-04 under an old harness, plausibly more compliant with procedural tool-call workloads.

Goal: bypass the offload axis to focus purely on the model-swap question: does a non-qwen3.6 model drive the recipe correctly through Goose's tool-call integration?

Result: **same class of integration failure as eval-15.** Different mechanism this time — qwen2.5-coder's template *does* declare the correct tool-call format (`<tool_call>...</tool_call>` tags), but the model doesn't comply with its own template's instruction. It emits OpenAI-shaped JSON instead, which Ollama's parser doesn't recognize. The recipe loop terminated after 4 tool-call attempts (none of which actually fired through to Goose's tool dispatcher).

## Verdict

Verdict: INVALID

The recipe-completion question (does a non-qwen3.6 model help?) remains unanswered. Two consecutive model-swap attempts (eval-15: Llama 3.3 70B, eval-16: qwen2.5-coder:32b) failed at the tool-call integration boundary before either model could demonstrate capability on the recipe. Combined with eval-04's earlier qwen2.5-coder failure, this points to a structural property of the Goose + Ollama OpenAI-compat stack — not a per-model bug.

## What ran

- Recipe + wrapper: post-PR-#51 (same as eval-15)
- Model: `qwen2.5-coder:32b` (already pulled, ~19 GB, fits GPU-only)
- Wrapper-forwarded env: `GOOSE_MODEL=qwen2.5-coder:32b` (no context override needed — Ollama defaults handle it)
- Params: same as eval-15 — issue #51 against `why-pengo/health_track`
- Session log: 20 lines, 0 recognized tool calls (`▸` markers absent — compare to eval-14's many)

## What happened

The model emitted 4 tool-call attempts for Step 0 (the AGENTS.md probes):

```
{"name": "github__get_file_contents", "arguments": {"owner": "why-pengo", "repo": "health_track", "path": "AGENTS.md"}}
{"name": "github__get_file_contents", "arguments": {"owner": "why-pengo", "repo": "health_track", "path": "backend/AGENTS.md"}}
{"name": "github__get_file_contents", "arguments": {"owner": "why-pengo", "repo": "health_track", "path": "frontend/AGENTS.md"}}
{"name": "github__get_file_contents", "arguments": {"owner": "why-pengo", "repo": "health_track", "path": "docs/AGENTS.md"}}
```

Key contrast with eval-15:
- eval-15 (Llama 3.3): invented a bad tool name (`github__issue`, real one is `issue_read`) — *plus* the integration failed
- eval-16 (qwen2.5-coder): **correct tool name** (`get_file_contents`) with the same `github__` namespace prefix; correct OpenAI-format keys (`arguments` not `parameters`); structurally valid JSON

So my eval-15 read ("the model is bad at recalling tool names under load") was at best partial. eval-16 shows that even when the model recalls names correctly, the integration still doesn't fire. **The bug isn't the model — it's the parser/template alignment.**

## Diagnostic that pinned the failure

Two probes after the failed eval:

**1. Template inspection** — does qwen2.5-coder:32b's template declare tool-call syntax?

```
You are provided with function signatures within <tools></tools>:
...
For each function call, return a json object with function name and arguments
within <tool_call></tool_call> with NO other text. Do not include any backticks
or ```json.
```

Yes — the template explicitly instructs the model to wrap each tool call in `<tool_call>...</tool_call>` tags. Ollama's parser looks for those tags to detect a tool call. **Without the tags, the parser leaves the response as content.**

**2. Bare curl probe** — does the model comply with its own template's instruction?

```bash
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:32b",
    "messages": [{"role": "user", "content": "What files are in the repo?"}],
    "tools": [{"type": "function", "function": {"name": "list_files", ...}}]
  }' | jq '.choices[0].message'

# Returned:
{
  "role": "assistant",
  "content": "{\"name\": \"list_files\", \"arguments\": {\"path\": \"./\"}}"
}
```

**No `<tool_call>` tags.** No `tool_calls` array. The model emitted OpenAI-format JSON instead of the qwen2.5 tag-wrapped format its own template specifies. Identical pattern to the recipe run — confirms it's not a recipe-complexity issue.

(Compare to eval-15's curl probe, where Llama 3.3 *did* produce a valid `tool_calls` array. So the integration works in isolation for Llama 3.3 but breaks under the recipe's tool-rich context. For qwen2.5-coder it doesn't even work in isolation.)

## The deeper finding (the lesson worth capturing)

**Goose's tool-call integration via Ollama OpenAI-compat is uniquely well-tuned for qwen3.6.**

The Goose → Ollama path goes through `v1/chat/completions` (per `docs/offload-config.md`). Ollama's OpenAI-compat shim relies on each model's template to declare the tool-call output format, and on the model to comply with it. The conditions for that integration to work cleanly are:

1. The template has tool-call markers Ollama's parser recognizes (qwen3.6 ✓, qwen2.5-coder ✓, llama3.3 ✓)
2. The model actually complies with the template's tool-call format under real workloads (qwen3.6 ✓, others ✗)
3. The model doesn't invent tool names (qwen3.6 ✓, llama3.3 ✗ in eval-15, qwen2.5-coder ✓ in eval-16)

qwen3.6 is the only model on bazzite today that satisfies all three. Other models fail at (2) or (3) regardless of how capable they are at coding or recipe completion.

This is consistent with eval-04's earlier qwen2.5-coder failure (under the much older harness — same root cause, not a recipe-iteration regression).

## What this means for #50 / #47

The straightforward "swap the model" hypothesis isn't pursuable today through the Goose-via-Ollama-OpenAI-compat stack. To meaningfully bake off models against qwen3.6, we'd need one of:

| Path | Cost | Notes |
|---|---|---|
| Patch Goose to use Ollama's native `/api/chat` endpoint | High | Richer tool-call protocol; bigger code change; was scoped OUT (Jon: "skip B") |
| Per-model TEMPLATE overrides | Medium-high | Write Modelfile that forces the model to emit `<tool_call>` tags or whatever the parser wants. Fragile, needs tuning per model, no guarantee the model complies |
| Find a model whose template + behavior happen to align | Medium | Pull more candidates, run the curl probe first. Dice-rolling without a clear hit-rate prior |
| Switch the runner entirely (llama-server direct) | High | Same scope blow-up as MoE-offload required — surfaced in `docs/offload-config.md` |

None of these are cheap. The #50 + #47 investigations as currently framed are **paused pending a decision on which path to invest in.**

## What this preserves (the actual value)

Even though no recipe-completion capability question was answered:

1. **HW baseline for the harness** — `evals/eval-14/result.md` documents qwen3.6 at 131K context with real numbers (VRAM, RAM, PWR, GPU%, btop screenshots). Reusable for any future experiment.
2. **Offload knob surface mapped** — `docs/offload-config.md` documents what's available under Ollama (Modelfile CPU layer offload, KV quantization), what isn't (MoE expert offload, fine KV offload), and what would require leaving Ollama. Future investigations skip the re-discovery.
3. **HW offload mechanically validated** — eval-15 proved that 40-layer GPU offload with 70B-class models works end-to-end (loaded, ran, used CPU+GPU as planned). When/if a runnable model becomes available, the offload path is known-good.
4. **Per-invocation model + context overrides** — `scripts/run-recipe-in-container.sh` now forwards `GOOSE_MODEL` and `GOOSE_CONTEXT_LIMIT`. Future bake-offs don't need `goose.yaml` edits.
5. **Tool-call integration boundary identified** — the specific class of "template says X, model emits Y, parser sees Y as content" is now documented. Whoever picks this up later won't repeat the eval-15/16 investigation cost.

## Action items

- [x] eval-16 result writeup
- [ ] **Bundle this work into a PR** — wrapper changes, Modelfile, `docs/offload-config.md`, eval-14/15/16. Same pattern as PR #51.
- [ ] **Update #50** with the lesson learned: Subtasks 1 + 2 complete; Subtasks 3 + 4 + 5 paused pending a decision on which integration path to invest in.
- [ ] **Decide on next session**: continue investing in #47-style bake-off (which requires resolving the tool-call integration boundary), or pivot to other harness improvements (e.g. #42 AGENTS.md for health_track) that aren't blocked.

## Next time

- The two consecutive INVALID verdicts (eval-15, eval-16) confirm the workflow shape: "experiment requires a model swap" → "model swap requires integration work" → "integration work is out of scope" → pause. Worth a fast curl-probe-first gate on any future model-swap experiment: *if `curl ... tools=[{...}]` doesn't return `tool_calls`, the model is non-viable under current Goose, full stop. No point pulling, no point Modelfile-tuning, no point eval-prep.*
- The qwen3.6-uniqueness finding is the single most important piece of harness knowledge from this session. It explains why eval-04 failed, why eval-15 failed differently, and why eval-16 failed similarly-but-differently. Goose-side investment is the unlock.
