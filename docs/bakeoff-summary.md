# Bake-off summary — runner default model evaluation (#47)

> **Note (2026-06-21, correction):** The architecture characterization of `qwen3.6:latest` was incomplete in the original write-up. `/api/show` reports `general.architecture=qwen35moe` with 256 experts, top-8 active — it is a Qwen 3.5-family MoE, not a dense 36B model. Active params per token are roughly 3–5B (8/256 of the MoE plus shared attention). This explains the high observed throughput (~250 t/s gen on the PR #94 smoke check for #88) and means the bake-off compared two MoE candidates (`qwen3.6`, `qwen3-coder`) against one dense candidate (`qwen2.5-coder`). The 3/3 PASS verdict and the recommendation both still hold; inline annotations below have been amended.

> **Note (2026-06-27, recommendation superseded):** The recommendation below ("keep qwen3.6:latest as default") was the right call at filing — qwen3.6 was the only 3/3 PASS at the time and qwen2.5-coder's failure modes were unresolved. Two structural changes have since unlocked a re-eval: #89 confirmed `temperature=0.2` suppresses qwen2.5-coder's prose-blob failure mode (Appendix A) and #98 eliminated the within-batch branch-slug collision that was the remaining PARTIAL driver. The #101 re-eval (eval-35 / eval-35b / eval-35c) went **3/3 PASS at 8.67 avg turns / ~97s avg wall** — clearing the methodology bar with ~2.8x fewer turns than qwen3.6. **The default `RUNNER_MODEL` is now qwen2.5-coder:32b @ `temperature=0.2`** per [ADR-0008](adr/0008-qwen25-coder-default-runner-model.md), superseding [ADR-0006](adr/0006-qwen3-6-default-runner-model.md). The original 3/3 scoreline, methodology, and analysis below remain accurate as historical record; only the Recommendation section carries the supersession note inline.

## TL;DR

**Recommendation (original, 2026-06-21 — superseded 2026-06-27): keep `qwen3.6:latest` as the default `RUNNER_MODEL`.** Current default is qwen2.5-coder:32b @ `temperature=0.2` per [ADR-0008](adr/0008-qwen25-coder-default-runner-model.md). See the inline update in the Recommendation section below for the why.

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

> **Update (2026-06-27, #101 → ADR-0008):** Recommendation revised. After #98 eliminated the within-batch branch-slug collision, qwen2.5-coder:32b @ `temperature=0.2` was re-evaluated 3-of-3 against the canonical task (eval-35 / eval-35b / eval-35c) and went **3/3 PASS at 8.67 avg turns / ~97s avg wall** — clearing the methodology bar with ~2.8x fewer turns than qwen3.6's 24-turn average. **The default `RUNNER_MODEL` is now qwen2.5-coder:32b @ `temperature=0.2`**, per [ADR-0008](adr/0008-qwen25-coder-default-runner-model.md), superseding [ADR-0006](adr/0006-qwen3-6-default-runner-model.md). qwen3.6:latest remains a fully-supported override target. See `evals/eval-35/rollup.md` for the full trio writeup.

**Original recommendation (2026-06-21, superseded):** Keep `qwen3.6:latest` as the default `RUNNER_MODEL`. The current default holds.

Conditions under which this should be re-evaluated (historical — the first of these has now fired):

- **qwen2.5-coder at `temperature=0.2`** (resolved by #89 — see Appendix A) — variance did tighten (2 PASS + 1 PARTIAL vs 1 PASS + 1 PARTIAL + 1 FAIL at default temp), but not to 3/3. The remaining PARTIAL is the within-batch branch-slug collision pattern that's independent of temperature. qwen2.5-coder + low temp is the most promising alternative-default candidate identified to date; the within-batch collision is resolved by #98 (see Appendix A), so a clean rerun at low temp is now possible. **→ Fired 2026-06-27 via #101 / ADR-0008. Re-eval went 3/3 PASS. Default flipped.**
- **qwen3-coder with a post-PR stop signal** — if the overshoot pattern can be addressed via system prompt or temperature, qwen3-coder's clean speed becomes more attractive.
- **A new qwen3 family release** (e.g. qwen3-coder at larger scale with native tool-call discipline, or qwen3 family with extended training on structured outputs).

## Caveats and follow-ups

- **No per-call throughput (t/s) curves for the original bake-off runs (eval-27/28/30).** Those runs predate #88 — Ollama 0.30.7's `OLLAMA_DEBUG=1` doesn't surface per-call `eval_rate` in the server log, and `OLLAMA_DEBUG_LOG_REQUESTS=true` was the wrong tool (request-body dump, not metrics). Resolved going forward by PR #94 (closes #88): the runner now extracts `prompt_eval_count/duration`, `eval_count/duration`, `total_duration` from the `/api/chat` response body and surfaces them in every session.log. The #89 temperature reruns (eval-31..33c, see Appendix A) all carry per-call metrics; the original bake-off scoreline does not.
- **No code-quality review of the produced PRs.** Reliability is one axis of "which model is best"; correctness is the other. **See #47 subtask 5.**
- **All runs at default temperature (0.8).** Tested under #89; see Appendix A below. Net finding: low temperature is *not* a uniform tightening lever — it helps the prose-channel candidate (qwen2.5-coder) but hurts the native-tool-call candidates (qwen3-coder, qwen3.6). Default temperature stays uniform.
- **One task.** The bake-off ran against a single canonical issue. Different issue shapes (frontend-heavy, refactors, multi-file Python services other than the hydration shape) might reorder the candidates. Not surveyed; out of scope for this round.
- **`OLLAMA_DEBUG_LOG_REQUESTS=true` reverted from `scripts/start-ollama-bazzite.sh`** in this PR's first commit. While set during the bake-off it dumped one request-body JSON per `/api/chat` call into `/tmp/ollama-request-logs-*/` on bazzite. Clean those up if you haven't: `ssh bazzite.local 'rm -rf /tmp/ollama-request-logs-*'`.

## Appendix A: Temperature tuning investigation (#89)

Filed as a follow-up from this summary's "All runs at default temperature (0.8)" caveat. Re-ran each of the three evaluated candidates 3-of-3 at `temperature=0.2` against the same canonical task (`why-pengo/health_track#51`), with everything else matched to evals 27 / 28 / 30. Variance-first execution order: qwen2.5-coder → qwen3-coder → qwen3.6, so the highest-variance candidate's signal landed first.

### Setup

- Same recipe (`recipes/execute-issue.yaml`), same per-candidate `num_ctx` as the original bake-off (98304 / 102400 / 65536), same bazzite hardware + Ollama 0.30.7 / f16 KV.
- `temperature=0.2` passed via `--ollama-option temperature=0.2`.
- Per-call timing metrics surfaced via #88 (PR #94) — every eval-3X session.log now carries `[metrics: ...]` lines and an end-of-session summary, providing the per-call t/s curves the original bake-off lacked.
- Cleaned up `why-pengo/health_track` PRs + branches between candidate batches so each batch ran against a clean target-repo state (cross-batch contamination was discovered and corrected mid-investigation — eval-32/32b/32c were re-run after the cleanup).

### Per-candidate results

| Candidate | Default temp (eval-27/28/30) | `temperature=0.2` (eval-31/32/33) | Direction |
|---|---|---|---|
| qwen2.5-coder:32b (dense) | 1 PASS + 1 PARTIAL + 1 FAIL | **2 PASS + 1 PARTIAL** | **Improved.** Lost the FAIL. PASSes faster (8 + 10 turns vs default 9; eval-31 set a new project record). The remaining PARTIAL is within-batch branch-slug collision, not temperature. |
| qwen3-coder:30b-a3b-q4_K_M (MoE) | 2 PASS + 1 PARTIAL | 2 PASS + 1 PARTIAL | **Mixed.** PASS rate held. eval-32 was faster (15 vs 16 turns), but eval-32b's PASS took 55 turns vs default's 18 — heavy iterate-and-refine overshoot. PARTIAL was longer too (51 vs 28 turns). |
| qwen3.6:latest (MoE, ~3–5B active) | 3/3 PASS | 2 PASS + 1 PARTIAL | **Regressed.** Lost a PASS (eval-33 hit a `get_file_contents` loop after committing 1 file; salvage opened PR #86 from the partial commit). The 2 PASSes were faster (19 turns each vs default 21–28), and eval-33c was the project's first qwen3.6 run to reach `recipe_done` with **zero nudges** — but predictability matters more than mean speed for a production default. |

### Key finding: temperature interacts with tool-call channel discipline

The directional split tracks how each candidate emits tool calls, not whether it's "code-tuned" or "MoE":

- **Prose-channel models** (qwen2.5-coder emits 100% of tool calls in the content channel, requiring #84 to rescue them) **benefit from low temperature.** Low temp produces cleaner, more reliably parseable tool-call JSON. The specific failure mode that doomed eval-30c at default temp — an 18,689-character prose blob too large for the rescue parser — didn't recur. The rescue itself stays load-bearing; what changed is what it has to parse.
- **Native-tool-call models** (qwen3-coder + qwen3.6 both emit tool calls via the proper `tool_calls` field, zero prose rescues at either temperature) **regress at low temperature.** The randomness in default temperature is what *breaks out of* deterministic loops — iterate-and-refine on the same file (qwen3-coder eval-32b: 21 `create_or_update_file` calls for a 4-file issue), self-referential re-reading (qwen3.6 eval-33: 4 consecutive `get_file_contents` on the same path), verbose summary-instead-of-progress (qwen3.6 eval-33b's 7437-token gen turn). At low temp the model deterministically locks into these patterns instead of exploring out of them.

The intuition "lower temperature = more deterministic = better structured output" turns out to be only half right: it's only true when the *output* is the failure mode. When the failure mode is *behavioral loop avoidance*, low temp makes things worse.

### Recommendation

**Keep the uniform default temperature.** Do not ship per-candidate temperature overrides. The data doesn't support a single low-temp default (regresses qwen3.6 and qwen3-coder) and per-candidate routing logic adds operational complexity for a marginal win on one candidate.

For future onboarding of new candidates, a one-line heuristic: if a candidate emits tool calls through the prose channel (requires #84 to rescue), try `temperature=0.2` early. If it emits native `tool_calls`, leave temperature at default and look for other tuning levers.

### Secondary observations from the data

- **Within-batch branch-slug collisions were the dominant non-model failure mode** across this temperature investigation. eval-31c, eval-32c, and the discarded contaminated eval-33 all PARTIALed for the same reason — the runner had no logic to mutate the branch slug between same-task runs, so back-to-back runs converged on the same name and the second one hit 422 "PR already exists." Independent of temperature. **Resolved by #98** (investigation #97 → GO Approach E): the runner now generates `runner/issue-<N>-<YYYYMMDD-HHMMSS>` and passes it to the model as a templated param, so the model never picks the slug and back-to-back invocations get distinct branches. Shakedown captured in eval-34.
- **eval-33c is qwen3.6's first nudge-free PASS.** Demonstrates the model *can* drive the recipe without a step-aware nudge, but doesn't do so reliably under any tested configuration. Useful data point for any future system-prompt or recipe-shape iteration.
- **Per-call t/s curves landed for free** thanks to #88 — every eval-3X log carries them, and they confirmed the qwen3.6/qwen3-coder MoE active-params signature (gen rates 195–235 t/s) vs qwen2.5-coder's dense profile (60–64 t/s) without any extra instrumentation.

### Eval crosswalk

- `evals/eval-31/`, `evals/eval-31b/`, `evals/eval-31c/` — qwen2.5-coder at `temperature=0.2`
- `evals/eval-32/`, `evals/eval-32b/`, `evals/eval-32c/` — qwen3-coder at `temperature=0.2`
- `evals/eval-33/`, `evals/eval-33b/`, `evals/eval-33c/` — qwen3.6 at `temperature=0.2`
