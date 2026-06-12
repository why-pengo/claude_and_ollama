# eval-14 result

Validation run for PR #51 (Step 3 callout: use `push_files` / `create_or_update_file`, never developer.write) **and** PR #49 (Step 5/6 rewrite). Goal: with path discipline restored, does the model now reach Step 5 and open the PR?

Result: **PR #51 worked. PR #49 didn't.** Path discipline held — files actually landed on the branch via MCP. But Step 5 still never fired, and the failure mode is *different* and sharper than before — the model fell out of the recipe entirely, started searching for "the 5 issues in this PR" (no such thing — there's just #51), and asked the user for a diff that doesn't exist. **The workflow-completion gap is loss-of-frame, not a missing trigger.**

## Verdict

Verdict: PARTIAL

PR #51 (Step 3 tool callout) is fully validated. The model used `create_or_update_file` for every target-repo write, pushed 5 commits to the branch with real code, zero host pollution. PR #49 (Step 5/6 rewrite) remains unvalidated — the rewrite didn't move the workflow-completion gap. The gap is bigger than a prompt-wording problem.

## What ran

- Branch: `main` (PR #51 merged as `5fba22f`)
- Recipe + wrapper: post-PR-#51 (context bump + Step 5/6 rewrite + Step 3 callout + AGENTS.md Step 0 + default_branch resolution)
- Model: `qwen3.6:latest` (= `qwen35moe`, MoE, 262144 native context, 131072 budget)
- Params: `--params issue_number=51 --params repo=why-pengo/health_track` (wrapper auto-injected `base_branch=develop`)
- Target task: same as eval-10/11/12/13 — `health_track` #51 (multi-file backend, `GET /api/hydration/daily`)
- 49 tool calls before model went off-rails
- Session log: 1551 lines (up from eval-13's 994)

## Tool-call breakdown

| Tool | Count | Notes |
|---|---|---|
| `get_file_contents` (github) | 28 | reading target repo files |
| `create_or_update_file` (github) | **7** | **path discipline ✓ — PR #51 worked** |
| `edit` (developer) | 4 | tried to locally edit `/work/backend/...` (paths that don't exist) |
| `tree` (developer) | 2 | exploring `/work` filesystem when confused about state |
| `shell` (developer) | 2 | initial + later |
| `issue_read` (github) | 1 | Step 1 ✓ |
| `list_branches` (github) | 1 | Step 2 prep ✓ |
| `create_branch` (github) | 1 | from `develop` ✓ |
| `search_issues` / `search_pull_requests` / `list_pull_requests` (github) | 3 | **looking for "health_records" and a nonexistent multi-issue PR** |
| `write` (developer) | **0** | callout held |
| `push_files` | 0 | model preferred `create_or_update_file` per-file |
| `create_pull_request` | **0** | never called — still the open gap |
| `add_issue_comment` | 0 | never called |

## What worked

### 1. PR #51 (Step 3 callout) — clean validation

Direct comparison vs eval-13 (same model, same task, only PR #51 differs):

| Failure mode | eval-13 (no callout) | eval-14 (PR #51 merged) |
|---|---|---|
| `developer.write` to `/work/backend/` | ❌ 2 calls, both target-repo files | ✅ 0 calls |
| `create_or_update_file` / `push_files` for code | ❌ 0 calls | ✅ 7 calls |
| Branch ahead of `develop` | ❌ 0 commits | ✅ 5 commits |
| Host pollution (`backend/` in harness) | ❌ yes | ✅ none |
| Read-before-overwrite (`get_file_contents` before push) | ❌ no | ✅ yes — fetched `analytics.py` first |

The callout bit cleanly. The model used MCP tools without slipping, and even followed the read-before-overwrite hint by `get_file_contents`-ing the existing analytics.py before pushing changes.

### 2. Code landed and survived self-correction

Final branch state (`develop...goose/issue-51-hydration-daily`): 5 commits, ahead_by 5, behind_by 0.

| File | Status | Net change |
|---|---|---|
| `backend/app/schemas/hydration.py` | added | +17 |
| `backend/app/services/analytics.py` | modified | +88 / -1 |

Code on the branch is reasonable: `HydrationDaily` schema matches the spec, `get_hydration_daily` added to analytics service with correct mL→fl-oz conversion constant (`_WATER_ML_PER_OZ = 29.5735`) and metric-key mapping.

Interesting wrinkle: the model emitted Chinese characters (`不在` ≈ "not in") mid-Python in one push — a code-quality slip — but recognized the typo from its own output and re-pushed via `create_or_update_file` to fix it. The final state on the branch is clean (`if "T" not in base`, no Chinese chars). So the model can self-correct via the right tool when it notices a problem. The slip is captured separately as a quality observation, not a process failure.

### 3. Commit history showed iterative push behavior

5 commits, including 3 retries of the schema commit ("feat: add HydrationDaily schema..." × 3) plus a "fix: remove DailySummary" and a "feat: add hydration daily analytics" — the model pushed multiple times as it noticed issues, rather than holding everything in one big commit. Useful behavior to see, even if the commit messages are a bit noisy.

## What didn't

### 1. Step 5 + Step 6 still never fired

Same as eval-10, eval-11, eval-12, eval-13. `create_pull_request` and `add_issue_comment` calls are absent from the log. PR #49's Step 5/6 rewrite ("the moment your last file is pushed, call `create_pull_request`. Don't ask, don't defer, don't decide whether — just do it") is **not load-bearing**. The model didn't hold the instruction long enough to apply it.

### 2. The model fell out of the recipe entirely (new failure mode)

Around line 1240, after partially completing subtasks 1 and 2 (schema + analytics service), the model started exploring with `get_file_contents` on `backend/app/models/hydration_goals.py`, then `backend/app/routers/hydration_goals.py`. These are real-but-irrelevant files (hydration_goals is a different feature, sibling issue #50 on health_track, not in #51's scope).

It then ran:

```
search_issues:        query: "health_records health_tracker repo:why-pengo/health_track"
search_pull_requests: query: "health_records repo:why-pengo/health_track"
list_pull_requests:   state: open
```

And narrated:

> *"Now I need to understand the full scope of all issues in this PR. Let me check the main.py to see how routers are mounted and look for the health_records router to understand the records endpoint pattern."*
> *"Let me check the full PR diff to see all files being changed and get the router code."*

The model **invented context** — "all issues in this PR", "the full PR diff" — that doesn't exist. There is no diff. There is one issue. The model lost the recipe shape and started behaving like it was helping a human in a chat session.

Last narration:

> *"I don't see a diff in your message. Could you please share the actual diff or PR that shows all the changes (and the 5 issues they contain)?"*

The model addressed the **user**, in a recipe-driven run with no user in the loop, asking for a diff. Then stopped. Clean exit, no error — just gave up.

### 3. Tool-selection slip on *fixes*

The PR #51 callout said "use `push_files` or `create_or_update_file` for code that needs to land on the branch". The model honored this for **new file content**. But when it noticed the Chinese-char typo it had pushed and tried to fix it, it reached for `developer.edit` on a `/work/backend/...` path that doesn't exist in the harness directory. Four `edit` attempts, all failed with "No such file or directory".

So the callout teaches "push, don't write" for *adding* files but not for *fixing* files already on the branch. The right pattern there is `get_file_contents` (read current) → modify content in memory → `create_or_update_file` (push corrected). The model eventually got there via re-pushes, but the four failed `edit` attempts are evidence that path discipline guidance doesn't fully transfer from "write" to "modify".

### 4. Subtask coverage was incomplete

Issue #51 has 5 subtasks. Model completed (partially):
- ✅ Subtask 1: `HydrationDaily` schema (clean)
- ✅ Subtask 2: `get_hydration_daily` in analytics (with Chinese-char detour, recovered)
- ❌ Subtask 3: router (`backend/app/routers/hydration.py`) — never started
- ❌ Subtask 4: register router in `main.py` — never started
- ❌ Subtask 5: `backend/tests/test_hydration.py` — never started

When the model went off-rails around line 1240, it had finished subtask 2 and was looking for "the router pattern". Instead of writing the router file (subtask 3), it started looking for "the 5 issues in this PR" — a phrase that doesn't appear anywhere in the issue body. This is hallucinated scope, not the actual subtask list it just executed two items of.

## The loss-of-frame hypothesis is now sharp

Three independent eval failures (eval-12, eval-13, eval-14) at the workflow-completion gap, with very different prompts, all show the same shape: **the model executes early steps correctly, then loses the recipe frame and stops without completing the closing steps (PR + issue comment).** The mechanism is different each time:

| Eval | Where it lost the frame | What it did instead |
|---|---|---|
| eval-12 | Mid-Step-3, after pushing some files | Announced intent to "check the analytics service" then clean-stopped |
| eval-13 | Wrong tool for entire Step 3 | Wrote 574 lines of fabricated analytics.py locally |
| eval-14 | After subtask 2, looking for the next pattern | Searched GitHub for nonexistent "5 issues in this PR", asked the user for a diff |

The common shape: model treats the procedural recipe as a stack of "things I might do" rather than a contract it must complete. As tool-result context grows, the recipe frame fades and the model drifts into "general helpfulness" mode — explore more files, ask questions, look for context — even though the recipe explicitly said "open the PR after your last push".

**Implication**: more recipe text can't fix this. PR #49's "don't ask, don't defer, don't decide whether — just do it" was about as direct as natural-language instruction gets. The model didn't disobey — it forgot the instruction existed.

This pattern is consistent with what we'd expect from a model that's strong at chat-style helpfulness and weaker at long-procedural-recipe adherence. qwen3.6 / qwen35moe is a general-purpose MoE, not a code-or-tool-procedure specialist.

## What this means for #45 / #47 / #50

- **#45's hypothesis space narrows further.** We've now ruled in/out:
  - Context budget (eval-12): partial — fixes coherence, not completion
  - Path discipline (eval-13/14 + PR #51): fixable via prompt
  - Step 5/6 wording (eval-14 + PR #49): **not load-bearing** — the model can't hold instructions through long runs
  - **Capability ceiling**: now the leading explanation for the residual workflow-completion gap
- **#47 (multi-model bake-off) is the most credible next experiment.** If qwen3.6 can't hold a recipe frame through 1500 lines of tool results, a different model (instruction-tuned for tool-use, larger, or both) may. This is the empirical question that resolves #45.
- **#50 (CPU/RAM offload) is the enabling investigation for #47.** Most candidate models that might be stronger at procedural recipe adherence (70B-class, DeepSeek-Coder v2, etc.) require offload on the 5090. So #50 → #47 in sequence.
- **The PR-completion gap may also need a runtime guardrail rather than a prompt rule.** Captured as a follow-up below.

## Action items

- [ ] **Stop iterating on the recipe to close the workflow-completion gap.** Three different prompt iterations (Step 5/6 rewrite, context bump, Step 3 callout) haven't moved it. The intervention surface is exhausted at the prompt layer.
- [ ] **Start #50** — figure out what offload config lets us run larger / different models on bazzite.
- [ ] **Then #47** — bake-off across qwen3.6 (baseline), one 70B-class with offload, one MoE-coder candidate (DeepSeek-Coder v2 if feasible). Same task (#51), same recipe.
- [ ] **Document the loss-of-frame pattern** as evidence in #45 and reference it from #47's framing.
- [ ] **Update the recipe's Step 3 callout to cover *fixes*** as well as new files — single line: "to fix or modify a file already on the branch, use `get_file_contents` then `create_or_update_file`, not `developer.edit`." Cheap, plausibly closes the tool-selection slip on edits. Could be folded into a future PR with other small changes.

## HW measurements (baseline for #50)

btop captures during the eval-14 run on bazzite (RTX 5090, Ryzen 9 9900X, 96GB DDR5). Three moments sampled:

| Moment | GPU % | PWR (W) | Temp (°C) | VRAM clock | P-state | TX/RX (MiB/s) |
|---|---|---|---|---|---|---|
| Between tokens (model loaded, idle) | 0% | 109 | 53 | 13801 MHz | P1 | 1.79 / 1.23 |
| Active token generation | **89%** | **261** | 55 | 13801 MHz | P1 | 156 / 14.0 |
| Post-run, model still resident | 0–1% | 11.0 | 41 | 405 MHz | P8 | 1.89 / 1.51 |

VRAM stays at **26.9 GiB / 85%** across all three samples (steady — model weights don't grow during a run). Screenshots: `btop-between-tokens.png`, `btop-active-generation.png`, `btop-deep-idle.png` (to be added).

### Reframe vs Jon's pre-eval-12 read

Pre-eval-12 the hypothesis was "GPU/PWR spikes are slow → MoE is underutilizing HW." These captures show the opposite: when the model is *actively generating*, GPU sits at 89% and PWR at 261W. That's not underutilized. The "slow spikes" we were watching are the **gaps between** generation events — dominated by MCP tool-call wait time (GitHub API roundtrips, file reads), not model compute.

So the underutilization framing for #50 was partially wrong. The real picture:

- **GPU compute**: well-used during generation (89% peak). No headroom here to harvest.
- **VRAM**: 85% used at 131K context. ~5 GB headroom. This is what bounds further context scaling and what offload can free.
- **Power budget**: 261W peak vs ~575W TDP → ~50% headroom. Bigger models could draw more without hitting thermal/power limits.
- **Thermal**: 55°C peak — well inside envelope. Cooling is not a constraint.
- **System RAM**: 7.5 GiB used at idle (no Ollama); 8.7 GiB used with qwen3.6 loaded (`free -m` on bazzite). Delta: ~1.3 GiB. The model lives 100% on GPU (`ollama ps` confirms `PROCESSOR: 100% GPU`), so system RAM cost is just the Ollama process itself. **~87 GiB of system RAM is unused and available for offload.**
- **Ollama default context wrinkle**: `ollama ps` after a standalone `ollama run "hi"` showed `CONTEXT: 32768` — Ollama's default. The 131072 we set in `goose.yaml` only takes effect when Goose calls Ollama through the API with `options.num_ctx=131072`. Worth knowing for the measurement protocol — a `ollama run`-driven probe is *not* equivalent to a Goose-driven run for VRAM purposes.

### Implication for #50

The offload investigation isn't about *using* unused GPU. It's about *freeing VRAM* to fit different/larger models that can then use the unused power budget. That reshapes Subtask priority in #50 — the "qwen3.6 at 256K context + KV offload" experiment is less interesting than the "fit a 70B-class model via aggressive CPU layer offload" experiment, since the former just expands what's already plateaued and the latter unlocks a capability candidate.

## Follow-ups beyond this eval

- **Runtime guardrail for "must open PR after last push"**: a post-recipe hook (in the wrapper) that sees the model exit without calling `create_pull_request` despite commits on the branch could either (a) prompt the model to call it explicitly, or (b) fail the run with a loud signal. This bypasses the "model forgot the instruction" problem entirely. Worth a separate issue if #47 doesn't resolve the gap via model swap.
- **Commit-message hygiene** is a minor issue — three commits in a row titled "feat: add HydrationDaily schema..." is noisy. Probably falls out naturally if a stronger model lands; not worth a recipe fix today.
- **The Chinese-char emission (`不在` instead of `not in`)** is the first multilingual slip we've seen from qwen3.6. Worth noting as a data point on quant artifacts (qwen models are Chinese-origin, the model may be defaulting to native-language tokens under certain conditions). Not a recipe problem.

## Next time

- The "what is the *earliest* step we still distrust?" framing from eval-13's "next time" worked here. eval-14 was set up to isolate Step 5/6 (PR #49) after PR #51 fixed Step 3. It did exactly that, and gave us a clean answer (Step 5/6 rewrite isn't load-bearing).
- Five consecutive evals on the same task (eval-10 → eval-14) is the limit of useful repetition. Future runs at #51 should change the variable that matters next — model — not the same model with another prompt tweak.
- The result here is genuinely informative: we now know the residual gap is capability/architecture, not prompt. That's worth a PARTIAL even though no PR was opened.
