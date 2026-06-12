# eval-15 result

First 70B-class experiment under #50. Target: Llama 3.3 70B Instruct Q3_K_M on bazzite with CPU layer offload (40 GPU / 40 CPU layers), 65K context, via Goose's standard OpenAI-compat path through Ollama.

Goal: determine whether a 70B-class model closes the workflow-completion gap that qwen3.6 (36B MoE) couldn't.

Result: **the experiment could not answer its original question.** The HW side worked perfectly (model loaded, layer split matched the spec, RAM filled as planned, run executed). But on the first attempted GitHub MCP tool call after Step 0, Llama 3.3 emitted a tool-invocation JSON with an invented/incorrect tool name (`github__issue` instead of the real `issue_read`). Goose couldn't dispatch the unknown name, treated the malformed call as content, and the recipe loop terminated after 4 tool calls.

## Verdict

Verdict: INVALID

Not a model-capability verdict — the model never got to demonstrate capability on the recipe. The failure mode is **instruction-following under tool-rich prompts**: Llama 3.3 Q3 couldn't reliably recall the exact names of the ~10 GitHub MCP tools Goose declared, and invented a half-namespaced version that doesn't exist. The recipe-completion question (does 70B help?) remains open.

## What ran

- Recipe + wrapper: post-PR-#51 (context bump + Step 5/6 rewrite + Step 3 tool callout + AGENTS.md Step 0 + default_branch resolution)
- Model: `llama3.3-70b-offload` (custom Modelfile, base `llama3.3:70b-instruct-q3_K_M`, `num_gpu=40`, `num_ctx=65536`)
- Wrapper-forwarded env: `GOOSE_MODEL=llama3.3-70b-offload`, `GOOSE_CONTEXT_LIMIT=65536`
- Params: `--params issue_number=51 --params repo=why-pengo/health_track` (wrapper auto-injected `base_branch=develop`)
- Target task: same as eval-10/11/12/13/14 — `health_track` #51 (multi-file backend, `GET /api/hydration/daily`)
- 4 tool calls, then early termination
- Session log: 45 lines

## What worked

### 1. HW side: textbook offload behavior

| Metric | Value | Notes |
|---|---|---|
| Layer split | 40/80 on GPU (49%) | Matches `PARAMETER num_gpu 40` |
| VRAM at load | 28.0 GiB / 32.6 GiB (86%) | Targeted ratio achieved on first bisect |
| System RAM | 22.2 GiB used (+ 73.9 GiB cached as mmap'd weights) | Up from eval-14's 8.7 GiB — the +13.5 GiB is the CPU-resident model weights |
| GPU peak | 71% / 241W during active generation | Healthy, not bottlenecked |
| CPU peak | 48% overall, multiple cores 80-100% during CPU-phase work | Offload is doing real work |
| PCIe traffic | TX 1.5 GiB/s, RX 17.8 GiB/s during generation | The cost of the offload boundary |
| Inference speed | 2.97 t/s generation (eyeball from "hi" probe) | ~10× slower than qwen3.6 baseline, expected for this offload ratio |
| KV cache type | f16 (not q8_0 as configured) | `OLLAMA_KV_CACHE_TYPE` env didn't reach the llama-server subprocess; non-blocking for this experiment |

The btop screenshots (`btop-eval15-*.png` — to be added when Jon syncs them) document the three distinct phases:
1. **Active generation**: GPU busy + CPU streaming layers — both engines doing work
2. **CPU-heavy phase**: GPU idle, CPU saturated at ~48% overall with many cores 80-100% — offloaded layers processing
3. **Tool-call wait**: both engines idle — Goose waiting on GitHub MCP roundtrips

### 2. Recipe Step 0 + system prompt loading

All 4 AGENTS.md probes fired cleanly (`AGENTS.md`, `backend/AGENTS.md`, `frontend/AGENTS.md`, `docs/AGENTS.md`). The model demonstrated correct procedural recall *up to* the point where tool calling complexity ramped up.

### 3. Wrapper extension (this run)

PR-pending: `scripts/run-recipe-in-container.sh` now forwards both `GOOSE_MODEL` and `GOOSE_CONTEXT_LIMIT` from the parent env. The wrapper printed:

```
Model:          llama3.3-70b-offload (overriding goose.yaml default)
Context limit:  65536 (overriding goose.yaml default)
```

Confirming the per-invocation override path works for bake-off experiments without `goose.yaml` edits.

## What didn't

### 1. Tool-call format breakdown — the experiment-ending failure

After Step 0, when the model needed to read the GitHub issue (Step 1), it emitted:

```json
{"name": "github__issue", "parameters": {"number": "51", "owner": "why-pengo", "repo": "health_track"}}
```

This is structurally a valid Llama 3.3 tool call. But:

- `github__issue` is not a real tool. The actual tool is `issue_read` (no `github__` prefix in Goose's declarations to the model).
- The model invented a namespaced version, presumably half-remembering "this is a GitHub extension tool, must be prefixed."
- Goose received this through Ollama's OpenAI-compat layer, couldn't dispatch the unknown name, and treated it as content/text.
- The session loop interpreted "model emitted content, no tool call" as "model is done" and terminated.

Total tool calls: 4 (the AGENTS.md probes). Zero `issue_read`, `create_branch`, `push_files`, `create_pull_request`, `add_issue_comment` — none of the real recipe execution.

### 2. KV cache quantization didn't take effect

The Ollama server was launched with `OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_FLASH_ATTENTION=1` env vars. But the llama-server subprocess was invoked without `--cache-type-k` / `--cache-type-v` flags, and the load log shows `K (f16): 10240.00 MiB, V (f16): 10240.00 MiB` — full f16, not q8_0.

So the env var didn't propagate to the subprocess in Ollama 0.30.7's manual-serve setup. Non-blocking for this eval; would matter for context-scaling experiments. Filing as a follow-up.

### 3. The `llama3.3:70b-instruct-q4_K_M` pull bug (separate issue)

Side discovery: pulling the Q4_K_M variant fails with deterministic ~250ms EOF in Ollama 0.30.7, while Q3_K_M and smaller blobs pull cleanly. Cause is undiagnosed — some pre-download validation on the q4_K_M blob silently fails. Not blocking this experiment (q3 is plenty for the capability question), but documented for the record.

## Diagnostic that pinned the failure

After the recipe run, a bare curl directly to Ollama's OpenAI-compat endpoint:

```bash
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.3-70b-offload",
    "messages": [{"role": "user", "content": "What files are in the repo?"}],
    "tools": [{
      "type": "function",
      "function": {"name": "list_files", "description": "List files.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}
    }]
  }' | jq '.choices[0].message'
```

Returned a clean tool call:
```json
{
  "role": "assistant",
  "content": "",
  "tool_calls": [
    {"id": "call_tohwlmhk", "index": 0, "type": "function",
     "function": {"name": "list_files", "arguments": "{\"path\":\"/\"}"}}
  ]
}
```

So the stack is healthy:
- Ollama's OpenAI-compat parser does convert Llama 3.3's JSON output into `tool_calls`
- The model can emit valid tool calls when given a single tool
- The bug is **the model's instruction-following under many-tool + long-prompt conditions**, not integration

A diff of our derived Modelfile vs base also confirmed only `PARAMETER` additions — TEMPLATE was inherited cleanly. So template wasn't lost either.

## What this means for #50 / #47

- **The 70B-via-CPU-offload hypothesis is not refuted** — it's untested. We need a model that drives Goose's recipe correctly so we can ask the capability question at all.
- **The "many tools + long prompt → invented tool names" failure mode is a real category** — likely a Q3 quantization sensitivity plus model-side instruction-following weakness. Higher quants (Q4_K_M, Q5_K_M) might do better, but we can't pull Q4_K_M today, and Q5 won't fit even with offload.
- **The natural next candidate is `qwen2.5-coder:32b`** (already pulled, fits GPU-only):
  - Code-focused training — plausibly better at procedural-tool-recall under load
  - Fits in VRAM at 19 GB — no offload, much faster inference
  - Last tested in eval-04 under the pre-PR-#39 harness — worth re-testing now that path-discipline (PR #51), Step 5/6 mandate (PR #49), and AGENTS.md (PR #44) are in place
- **#50's offload investigation can pause** until we have a model that drives recipes correctly through this stack. There's no point measuring "70B offloaded vs qwen3.6" if the 70B can't even start the recipe.
- **The KV cache quantization env issue** should be revisited eventually — it would buy 50% KV memory for free, useful for any larger-context experiment.

## Action items

- [ ] **Run eval-16 with `qwen2.5-coder:32b`** against #51 to test path A. Same task, no offload needed, much faster.
- [ ] **Bundle this run's harness artifacts into a PR** — wrapper extension, Modelfile, eval-14 + eval-15 docs, `docs/offload-config.md`. Commit hygiene before more iteration.
- [ ] **Document the Q4_K_M pull bug** as a side-note in `docs/offload-config.md` for the next person who tries Llama 3.3 on Ollama 0.30.7.
- [ ] **Investigate `OLLAMA_KV_CACHE_TYPE` propagation** in manual-serve setup — not blocking but a free 50% KV memory savings on the table.
- [ ] **If qwen2.5-coder:32b also fails the tool-name recall test**, the next move is either (a) pull a more recent tool-tuned model (e.g. qwen3-coder, mistral-small-3) or (b) accept that the model-capability question requires going beyond what's available today on bazzite.

## Follow-ups beyond this eval

- The invented-tool-name failure mode is interesting in itself. If we see it across multiple models, it suggests Goose's tool declarations should be more prominent in the recipe (e.g. "use exactly these tool names: …") or that the recipe needs to declare them up front. Worth a separate investigation if it generalizes.
- Llama 3.3's behavior here is consistent with broader patterns — instruction-tuned chat models often handle tool calls fine in isolation but degrade under recipe-style procedural workloads with 10+ tools available.

## Next time

- The HW prep + load + bisect for offloaded models takes serious effort (this took most of a session). For #47's bake-off, do the model-and-tool-calling viability check FIRST (cheap curl test or small probe via Goose), THEN invest in offload tuning. Saves hours when a candidate fails at the tool-call layer.
- The Q4_K_M pull bug + KV cache env propagation issue are both worth noting on the harness side. Future offload experiments will hit one or both.
- Five attempts at #51 with qwen3.6 (eval-10 through eval-14) + this eval-15 = the task has been thoroughly worked. eval-16 is run-six on the same target; if it produces another failure mode characterization, we should consider whether the task itself is appropriate as a model-capability probe or if we need a smaller benchmark task.
