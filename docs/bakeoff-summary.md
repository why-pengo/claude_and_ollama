# Bake-off summary — runner default model evaluation (#47)

> **Note (2026-06-21, correction):** The architecture characterization of `qwen3.6:latest` was incomplete in the original write-up. `/api/show` reports `general.architecture=qwen35moe` with 256 experts, top-8 active — it is a Qwen 3.5-family MoE, not a dense 36B model. Active params per token are roughly 3–5B (8/256 of the MoE plus shared attention). This explains the high observed throughput (~250 t/s gen on the #88 smoke check) and means the bake-off compared two MoE candidates (`qwen3.6`, `qwen3-coder`) against one dense candidate (`qwen2.5-coder`). The 3/3 PASS verdict and the recommendation both still hold; inline annotations below have been amended.

## TL;DR

**Recommendation: keep `qwen3.6:latest` as the default `RUNNER_MODEL`.**

Three candidates evaluated 3-of-3 against the same task on bazzite under the post-offload-parked configuration (f16 KV, fully GPU resident, per-request `num_ctx`). qwen3.6 is the only candidate that achieved 3/3 PASS. It's the verbose-but-reliable option; reliability dominates the ceiling-but-variable alternatives for a production-default decision.

| Candidate | PASS | PARTIAL | FAIL | Avg turns (PASS) |
|---|---|---|---|---|
| **qwen3.6:latest (MoE, 36B total / ~3–5B active)** | **3/3** | 0 | 0 | 24 |
| qwen3-coder:30b-a3b-q4_K_M | 2/3 | 1/3 | 0 | 17 |
| qwen2.5-coder:32b | 1/3 | 1/3 | 1/3 | 9 (single run) |

> **Recommendation strength.** Based on N=3 per candidate, against one canonical task, at Ollama's default temperature. Strong enough to keep the existing default; not strong enough to claim qwen3.6 dominates its alternatives across all conditions. A wider sample, lower temperature (#89), or a different task shape could reorder the speed/reliability trade-off — the conditions under which this should be re-evaluated are listed at the bottom.

## Methodology

- **Task**: `why-pengo/health_track#51` (GET /api/hydration/daily — combined per-day shape) across every run. Multi-file backend issue conforming to the canonical issue format. Picked per #47's subtask 1.
- **Protocol**: 3-of-3 per candidate (matches the eval-22/23 baseline shape). Same recipe (`recipes/execute-issue.yaml`), same params, runs back-to-back per candidate so the model stays warm.
- **Hardware**: bazzite — RTX 5090 (32 GB VRAM), Ryzen 9 9900X, 96 GB RAM, Ollama 0.30.7.
- **Configuration**: f16 KV cache (no quantization — `OLLAMA_KV_CACHE_TYPE` removed per the parked-offload decision in `docs/offload-config.md`). `OLLAMA_FLASH_ATTENTION=1`. Per-request `num_ctx` set to each candidate's resident ceiling.
- **Pre-flight**: each candidate warmed at the target `num_ctx`, verified `processor: 100% GPU` via `/api/ps` before kickoff.
- **Harness features active**: loop detection (#85, default threshold 4) on every run; prose-shaped tool-call rescue (#84) on every run *except eval-29*, which captured the pre-#84 failure mode as the historical proof that #84 was needed.
- **Temperature**: Ollama default (0.8) on every run — see #89 for the per-candidate temperature-tuning question this opens.

## Candidates

| Candidate | Context | Status | Rationale |
|---|---|---|---|
| qwen3-coder:30b-a3b-q4_K_M | 102400 | Evaluated | MoE (active ~3B), code-tuned, fully GPU resident at 100k |
| qwen3.6:latest | 65536 | Evaluated | MoE 256/8 (~3–5B active, 36B total), general-purpose; existing default; reliable baseline from eval-22/23 |
| qwen2.5-coder:32b | 98304 | Evaluated | Dense 32B, code-tuned; failed eval-04 under Goose but the runner + #84 deserve a fair re-eval |
| llama3.3:70b-instruct-q3_K_M | n/a | **DQ'd** | Required CPU offload to fit on the 5090; parked as a production lane on 2026-06-20 (see `docs/offload-config.md`) |

## Per-candidate results

### qwen3-coder:30b-a3b-q4_K_M

| Eval | Verdict | Turns | Notes |
|---|---|---|---|
| 27 | PASS | 16 | Clean end-to-end, zero nudges, zero rescues |
| 27b | PASS | 18 | Clean; one minor retry on `create_branch` |
| 27c | **PARTIAL** | 28 | PR landed early (~turn 20), then model went into duplicate-PR + comment-loop pattern. Loop-detect (#85) fired at turn 28, aborted cleanly |

**Pattern**: cleanest execution when it works — eval-27 at 16 turns was the cleanest run in project history at the time. But carries a tail-risk: after opening its PR, the model may continue past `recipe_done` and accumulate duplicate calls. #85 catches this.

All three runs produced review-able PRs on health_track. PR-number attribution is subtle here: eval-27 cleanly opened PR #76 and eval-27b cleanly opened PR #78. eval-27c picked a branch slug that matched an earlier run's branch (the model log shows it explicitly noting "the branch already exists"), so its salvage step found PR #77 already on that branch — we can't conclude from the runner's logs alone whether eval-27c's `create_pull_request` call landed PR #77 or whether #77 was inherited from a prior same-slug run.

### qwen3.6:latest (MoE, 36B total / ~3–5B active)

| Eval | Verdict | Turns | Notes |
|---|---|---|---|
| 28 | PASS | 23 | 1 step-aware nudge ("commit done — now open the PR") |
| 28b | PASS | 28 | 1 nudge, 4 attempts at `create_pull_request` before one stuck |
| 28c | PASS | 21 | 1 nudge, similar shape, leaner read phase |

**Pattern**: verbose-but-correct. Always needs at least one nudge to push from the write phase to the PR step. Multiple PR/branch retries are common but recovery is reliable. Native `tool_calls` throughout — zero rescue dependency. The most production-suitable candidate by reliability.

### qwen2.5-coder:32b

| Eval | Verdict | Turns | Notes |
|---|---|---|---|
| 29 | FAIL | 3 | **Pre-#84.** Model emitted well-formed tool-call JSON in the content channel; runner had no rescue; 3-empty-turn guard fired |
| 30 | PASS | **9** | Post-#84. Every turn rescued — 100% prose channel. Cleanest run in project history |
| 30b | **PARTIAL** | 28 | Post-#84. Overshoot loop after PR landed (same pattern as 27c). Loop-detect aborted |
| 30c | FAIL | 11 | Post-#84. Model emitted an 18,689-character prose blob (likely trying to inline a full file as commentary) — too large for the rescue's JSON parser. Three subsequent prose-only turns; 3-empty-turn guard fired |

**eval-29 is kept as historical record** — it's the proof that #84 was needed, not a model defect. The runner's bake-off scoreline counts the 3 post-#84 runs only.

**Pattern**: extreme variance. NEVER uses native `tool_calls` — 100% of its tool-call intent ships through the content channel. With #84 active, the rescue catches everything that's parseable. The 9-turn PASS is real and remarkable; the 28-turn loop and the 11-turn FAIL are also real. High ceiling, low floor.

### llama3.3:70b-instruct-q3_K_M — disqualified

Captured for historical record under `evals/eval-25b`, `eval-25c`, `eval-26`. eval-25c was the first end-to-end PASS in project history (22 turns under heavy CPU offload). eval-26 collapsed at turn 25 with the same model + same options — the variance review that drove the parked-offload decision (`docs/offload-config.md`, 2026-06-20). Not a viable production lane on the current hardware.

## Comparative analysis

### Completion rate (the primary axis)

- qwen3.6: 3/3 PASS = 100% recipe-complete, 100% review-able artifacts
- qwen3-coder: 2/3 PASS + 1/3 PARTIAL = 67% recipe-complete, 100% review-able (all runs landed PRs)
- qwen2.5-coder: 1/3 PASS + 1/3 PARTIAL + 1/3 FAIL = 33% recipe-complete, 67% review-able

### Speed (when PASSing)

- qwen2.5-coder: 9 turns (single PASSing run; spectacular but not reproducible)
- qwen3-coder: ~17 turns avg
- qwen3.6: ~24 turns avg

Speed differences are interesting but secondary — a 9-turn run that happens 1-in-3 times is worse than a 24-turn run that happens 3-in-3 times for production use.

### Tool-call channel discipline

| Candidate | Native `tool_calls` | Prose-rescued |
|---|---|---|
| qwen3.6 | 100% | 0% |
| qwen3-coder | ~100% | one prose blip in 27c, model recovered after a nudge |
| qwen2.5-coder | 0% | 100% (entirely #84-dependent) |

### Variance / reliability

- qwen3.6: tight — all three runs took 21–28 turns, all PASSed
- qwen3-coder: moderate — 16–28 turn spread, 2/3 clean PASS, 1/3 saved by guard
- qwen2.5-coder: extreme — 9 to 28 turns, with one outright FAIL alongside one clean PASS

### Code quality

**Not assessed in this summary.** All passing runs produced PRs on `why-pengo/health_track`; their code correctness (mL→fl-oz conversion accuracy, JWT enforcement, missing-metric null vs 0 handling, test coverage of the issue's acceptance criteria) is a separate human review pass — the "PR quality" axis of #47's subtask 5. Whichever candidate wins on reliability does not automatically win on code quality; we'd want both signals before a high-stakes default switch.

## Key findings beyond the candidate ranking

1. **3-of-3 was essential, not bureaucratic.** Single-shot eval-27 made qwen3-coder look dominant (16-turn clean PASS). Single-shot eval-30 made qwen2.5-coder look like the fastest executor in history (9 turns). Both impressions were wrong — 3-of-3 surfaced the tail-risk loops and high variance that single-shot runs hid. Jon's "we only did 1 run on each — do we not need 3 of 3?" mid-process correction reshaped the conclusion materially.

2. **#84 is load-bearing for qwen2.5-coder, not optional.** Without the prose-shaped-tool-call rescue, every qwen2.5-coder run is eval-29: a 3-turn FAIL with no artifact. With it, the model can produce competitive PASSes. The rescue is the difference between "model can drive the recipe" and "model is unusable" for this candidate. Any future candidate that doesn't use native `tool_calls` is similarly gated on #84.

3. **#85 fired in production twice.** eval-27c and eval-30b both produced their PR artifact early then got stuck in post-PR comment loops. Without loop detection both would have burned all 60 turns producing only duplicate API errors. Loop detection cut those runs to 28 turns — roughly half the wall-clock the 60-turn cap would have taken. (Exact minutes aren't recorded in the runner output and the GIN-access-log timings vary per-turn; the savings is "noticeable" not "precisely 60%".)

4. **Code-tuned models overshoot more than the general-purpose candidate.** Both qwen3-coder (27c) and qwen2.5-coder (30b) showed the "PR opened, but the model keeps going" pattern. qwen3.6 didn't do this in any of its 3 runs. Hypothesis: code-tuned training biases toward "complete the work thoroughly," which past `recipe_done` becomes overshoot. Worth investigating with temperature tuning under #89, or with stronger explicit-stop signals in the system prompt. (Architecture is a confounder, not a clean explanation: qwen3-coder is MoE and *also* overshot, so the pattern doesn't cleanly split on MoE-vs-dense; it tracks the code-tuned-vs-general-purpose axis instead.)

5. **Verbose-but-correct beats fast-but-fragile for a default.** qwen3.6's "always needs a nudge, takes 24 turns" pattern is the production-suitable choice. A 24-turn PASS every time is worth more than a 9-turn PASS one time in three.

## Recommendation

**Keep `qwen3.6:latest` as the default `RUNNER_MODEL`.** The current default holds.

Conditions under which this should be re-evaluated:

- **qwen2.5-coder at `temperature=0.2`** (per #89) — if low-temperature tightens its variance to something like 3/3 PASS, it becomes the speed-winner candidate worth promoting.
- **qwen3-coder with a post-PR stop signal** — if the overshoot pattern can be addressed via system prompt or temperature, qwen3-coder's clean speed becomes more attractive.
- **A new qwen3 family release** (e.g. qwen3-coder at larger scale with native tool-call discipline, or qwen3 family with extended training on structured outputs).

## Caveats and follow-ups

- **No per-call throughput (t/s) curves under f16 KV.** Ollama 0.30.7's `OLLAMA_DEBUG=1` doesn't surface per-call `eval_rate` in the server log, and `OLLAMA_DEBUG_LOG_REQUESTS=true` was the wrong tool (request-body dump, not metrics). The actual fields exist in the `/api/chat` response body but the runner doesn't extract them. **See #88.**
- **No code-quality review of the produced PRs.** Reliability is one axis of "which model is best"; correctness is the other. **See #47 subtask 5.**
- **All runs at default temperature (0.8).** Lower temperature would likely tighten the code-tuned candidates' variance. **See #89.**
- **One task.** The bake-off ran against a single canonical issue. Different issue shapes (frontend-heavy, refactors, multi-file Python services other than the hydration shape) might reorder the candidates. Not surveyed; out of scope for this round.
- **`OLLAMA_DEBUG_LOG_REQUESTS=true` reverted from `scripts/start-ollama-bazzite.sh`** in this PR's first commit. While set during the bake-off it dumped one request-body JSON per `/api/chat` call into `/tmp/ollama-request-logs-*/` on bazzite. Clean those up if you haven't: `ssh bazzite.local 'rm -rf /tmp/ollama-request-logs-*'`.
