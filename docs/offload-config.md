# Offload knobs for Ollama under Goose

Reference for what we can and can't control about model placement (GPU vs CPU/RAM) on `bazzite` when running Goose against Ollama. Closes Subtask 2 of #50.

> **Superseded in part by #78.** The runner no longer uses Goose, and `ollama_chat()` now POSTs to native `/api/chat`, so per-request `options` (`num_ctx`, `num_gpu`, `seed`, `temperature`, ...) are first-class. Use the CLI flags `--num-ctx N` and `--ollama-option key=value` (or a recipe `options:` block) to set anything from the table below — Modelfiles are no longer the only lever. The "Goose-side" and "Modelfile" sections below remain accurate as historical context for evals 14–22 and as a map of what every option actually does, but the *only-way-to-set-them* framing no longer applies.

## TL;DR

| Layer | Knob | How to set | Available? |
|---|---|---|---|
| Goose | `num_ctx` (context window) | `GOOSE_CONTEXT_LIMIT` in `goose.yaml` | ✅ |
| Ollama | CPU layer offload (`num_gpu`) | Modelfile `PARAMETER num_gpu N` | ✅ |
| Ollama | All KV → CPU (`low_vram`) | Modelfile `PARAMETER low_vram true` | ✅ (coarse) |
| Ollama | KV cache quantization | `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (server env) | ✅ (server-wide) |
| Ollama | `mmap` / `mlock` / `num_thread` | Modelfile `PARAMETER` | ✅ |
| **llama.cpp** | **MoE expert offload (`--n-cpu-moe`)** | Not exposed by Ollama | ❌ |
| **llama.cpp** | **Fine KV cache offload (`--no-kv-offload`)** | Not exposed by Ollama | ❌ |

If we need the bottom two, we leave Ollama and drive llama.cpp's `llama-server` directly.

## Goose-side: essentially zero offload control

Goose 1.35.0's Ollama provider (`crates/goose/src/providers/ollama.rs`) calls Ollama's **OpenAI-compatible** endpoint `POST v1/chat/completions`, not native `/api/chat`. The full set of fields it places in Ollama's `options` block:

```
options.num_ctx       # from GOOSE_CONTEXT_LIMIT
options.num_predict   # from max_tokens
```

That's the whole list. Goose does not pass `num_gpu`, `num_thread`, `low_vram`, `main_gpu`, `use_mmap`, `use_mlock`, `f16_kv`, or anything else.

The `ModelConfig.request_params` map exists as an escape hatch but merges at the **top level** of the payload, not into `options`. Worse, OpenAI-compat strips Ollama-specific `options.*` fields server-side anyway.

**Practical implication**: nothing in `goose.yaml` will affect offload. The only variables here worth touching for offload experiments are `GOOSE_CONTEXT_LIMIT` (which drives `num_ctx`, dominating KV memory at long context) and the timeout knobs (`OLLAMA_STREAM_TIMEOUT`, `OLLAMA_TIMEOUT`) so CPU-offloaded slow runs don't false-stall.

## Modelfile: the only Ollama-native lever for offload

Custom model variants get created on bazzite via `ollama create <name> -f Modelfile`. Each variant becomes a separate model entry (visible in `ollama list`), so different offload profiles are clean A/B candidates.

Documented `PARAMETER` directives ([Ollama Modelfile docs](https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx)): `num_ctx`, `temperature`, `seed`, `stop`, `num_predict`, `draft_num_predict`, `top_k`, `top_p`, `min_p`, `repeat_last_n`, `repeat_penalty`.

Undocumented but accepted by the parser (verified in Ollama source, same underlying options struct as the API):
- `num_gpu` — number of transformer layers to keep on GPU. Set lower than the model's total layer count to push the rest to CPU.
- `low_vram` — boolean. `true` pushes the entire KV cache to CPU. Coarse hammer but useful when even reduced `num_gpu` doesn't free enough VRAM.
- `main_gpu` — which GPU index to use as primary (irrelevant on single-GPU bazzite).
- `use_mmap` — `true` (default) lets the OS page model weights you can't fit in RAM. Important when working with models larger than free RAM.
- `use_mlock` — `true` pins weights into RAM (prevents swap). Usually `false`.
- `num_thread` — CPU threads for non-GPU layers. Set to physical core count when CPU layers are doing real work.
- `f16_kv` — `true` keeps KV cache in f16 (default). Less relevant now that KV quantization via server env is available.
- `num_batch` — physical batch size for prompt processing.

### Modelfile templates

**Profile A — Llama 3.3 70B Instruct Q4 with aggressive CPU offload** (target #50's primary experiment):

```dockerfile
FROM llama3.3:70b-instruct-q4_K_M

PARAMETER num_ctx 32768
PARAMETER num_gpu 20
PARAMETER low_vram false
PARAMETER use_mmap true
PARAMETER use_mlock false
PARAMETER num_thread 12

# Start with num_gpu=20 (out of 80 transformer layers). Bisect from there:
# - if it doesn't load → lower num_gpu (more layers to CPU)
# - if it loads with VRAM headroom → raise num_gpu (more layers on GPU = faster)
# Aim for ~28 GiB VRAM (87% — leaves headroom for KV cache growth).
```

Then `ollama create llama3.3-70b-offload -f Modelfile` on bazzite, and `GOOSE_MODEL: llama3.3-70b-offload:latest` in `goose.yaml`.

**Profile B — qwen3.6 at 256K context with KV pushed to CPU** (optional, only if Profile A doesn't pan out):

```dockerfile
FROM qwen3.6:latest

PARAMETER num_ctx 262144
PARAMETER low_vram true
PARAMETER use_mmap true
PARAMETER num_thread 12
```

`low_vram=true` is the coarse-but-only way to keep model weights on GPU while sending the KV cache to CPU. (Fine-grained `--no-kv-offload` from llama.cpp is *not* exposed.)

## Server-wide Ollama env (set on bazzite's Ollama systemd unit)

These affect every model loaded by the server, not per-model. Worth setting unconditionally for the offload experiments:

```
OLLAMA_FLASH_ATTENTION=1        # required to enable KV quantization
OLLAMA_KV_CACHE_TYPE=q8_0       # halves KV memory (q4_0 is 4x reduction but quality risk)
OLLAMA_KEEP_ALIVE=-1            # never unload — reloads are slow, confound timing measurements
OLLAMA_NUM_PARALLEL=1           # serial workload — avoids duplicate KV cache per parallel slot
```

`OLLAMA_KV_CACHE_TYPE` silently falls back to f16 on architectures without proper q8_0 support ([#15043](https://github.com/ollama/ollama/issues/15043)). On the 5090 (CUDA 12+) it should work; verify with first measurement.

## What's NOT possible without leaving Ollama

### MoE expert offload (`--n-cpu-moe`)

llama.cpp merged `--cpu-moe` / `--n-cpu-moe` in Aug 2025 ([PR #15077](https://github.com/ggml-org/llama.cpp/pull/15077)) for keeping cold MoE expert tensors on CPU. This is exactly the lever that matters most for qwen35moe / qwen3.6 and DeepSeek-V3.

Ollama state: **not exposed**.
- [Issue #11772](https://github.com/ollama/ollama/issues/11772) — open feature request, no movement.
- [PR #12333](https://github.com/ollama/ollama/pull/12333) — proposed `num_moe_offload` PARAMETER. Stalled. Maintainers want it automatic.
- [PR #15207](https://github.com/ollama/ollama/pull/15207) — automatic MoE offload attempt. Closed unmerged after benchmarks showed no win.

Ollama's automatic layer scheduler does *something* with MoE (silently spills some layers to `CUDA_Host` pinned RAM), but it mis-estimates VRAM on MoE models and provides no control or visibility ([#14351](https://github.com/ollama/ollama/issues/14351)).

**If MoE expert offload is the experiment we want, the runner has to be `llama-server` from llama.cpp directly.** Goose can still talk to it (llama-server exposes an OpenAI-compat endpoint), but configuration moves from Modelfile to `llama-server` CLI flags.

### Fine-grained KV cache offload (`--no-kv-offload`)

llama.cpp's `--no-kv-offload` keeps model weights on GPU but the KV cache in CPU RAM — exactly what we want for long context on a 32GB card.

Ollama state: **not exposed**. [Issue #9750](https://github.com/ollama/ollama/issues/9750) tracks this; no PR. Ollama instead reduces GPU layer count when VRAM gets tight, which evicts *weights* (slow per token) rather than just KV cache (fast). The `low_vram=true` PARAMETER is a coarse approximation but doesn't let you keep most weights on GPU.

Same workaround as MoE offload: `llama-server` directly.

### What happens at OOM

When `num_ctx` and `num_gpu` together exceed VRAM: typically hard `cudaMalloc failed: out of memory` and the runner exits ([#8447](https://github.com/ollama/ollama/issues/8447)). Before crashing, the scheduler aggressively shrinks `num_gpu`, pushing whole layers (weights + their KV slice) to CPU. It does **not** keep weights on GPU and spill only the KV cache.

So when bisecting `num_gpu`, the failure mode is loud — model fails to load, error message, no silent degradation.

## Implications for #50 experiment design

The original #50 plan assumed offload was a configurable axis we could sweep. The reality:

| Experiment | Achievability under Ollama |
|---|---|
| Baseline qwen3.6 at 131K context | ✅ already done (eval-14) |
| Llama 3.3 70B Q4 with CPU layer offload | ✅ Modelfile `PARAMETER num_gpu N` |
| qwen3.6 at 256K with KV → CPU | ⚠️ via `low_vram=true` (coarse — all KV, not partial) |
| DeepSeek-Coder v2 with MoE expert offload | ❌ requires switching runner to `llama-server` |
| Fine KV offload at 256K | ❌ requires switching runner to `llama-server` |

**Recommendation**: do the Modelfile-driven 70B experiment first (achievable, primary). If 70B-class produces materially better recipe-completion behavior on #51, that decides #47 in our favor and the question of "should we leave Ollama for MoE-aware runners?" can be deferred.

If 70B-class doesn't move the needle, that's the trigger to consider `llama-server` as the runner — and a much bigger scope decision than #50 originally implied.

## How to verify a Modelfile applied correctly

After `ollama create`, before running a full eval:

```bash
ollama show <variant-name>           # shows PARAMETER values baked in
ollama run <variant-name> "hi"       # loads the model with those params
ollama ps                            # shows ACTUAL CONTEXT + PROCESSOR (GPU/CPU split)
```

`ollama ps`'s `PROCESSOR` column shows the actual split — e.g. `60% GPU / 40% CPU`. This is the ground truth for whether offload took effect, more reliable than reading `num_gpu` back.

Note: a standalone `ollama run "hi"` uses Ollama's default `num_ctx` (32768) regardless of Modelfile, because the CLI doesn't pass num_ctx through. To verify the model loads at the intended context, drive it through Goose (which sets `num_ctx` per request from `GOOSE_CONTEXT_LIMIT`) or hit the `/api/chat` endpoint directly with `options.num_ctx` set.

## Sources

- [Goose Ollama provider source](https://github.com/block/goose/blob/main/crates/goose/src/providers/ollama.rs) — confirms only `num_ctx` + `num_predict` reach Ollama
- [Ollama Modelfile docs](https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx)
- [Ollama FAQ — KV cache, flash attention, keep_alive](https://docs.ollama.com/faq)
- [llama.cpp PR #15077 — `--n-cpu-moe`](https://github.com/ggml-org/llama.cpp/pull/15077)
- [Ollama PR #12333 — `num_moe_offload` (unmerged)](https://github.com/ollama/ollama/pull/12333)
- [Ollama issue #11772 — MoE offload feature request](https://github.com/ollama/ollama/issues/11772)
- [Ollama issue #9750 — `--no-kv-offload` feature request](https://github.com/ollama/ollama/issues/9750)
