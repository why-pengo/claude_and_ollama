# eval-12 result

Experiment A of #45 / #47 investigation: same task, same model, **context bump from 64K → 128K** (well within qwen3.6 / qwen35moe's 256K native ceiling). Goal: determine whether the multi-file backend reliability cliff is context-budget driven.

Result: **context was load-bearing for the bad failure modes** (task conflation, host pollution, floundering, hallucinated tools) but **not for the workflow-completion gap** (PR + issue comment). 128k context produces materially better code, cleaner runs, and ends in a different failure mode than 64k did.

## Verdict

Verdict: PARTIAL

Big improvement in coherence and code quality. The model now produces correct, well-placed code. But it still doesn't complete the recipe loop — stops one or two steps before opening a PR or commenting on the issue. The cause is **not context budget**; needs a different intervention.

## What ran

- Branch: `experiment/qwen3.6-128k-context` (single change: `GOOSE_CONTEXT_LIMIT: 65536 → 131072` in `goose.yaml`)
- Recipe + wrapper: post-PR-#44 (default_branch resolution, AGENTS.md fetch in Step 0)
- Model: `qwen3.6:latest` (= `qwen35moe`, MoE architecture, 262144 native context)
- Params: `--params issue_number=51 --params repo=why-pengo/health_track` (wrapper auto-injected `base_branch=develop`)
- Target task: same as eval-10 + eval-11 — `health_track` #51 (multi-file backend, `GET /api/hydration/daily`)
- 31 tool calls before clean stop (vs eval-10's 22, eval-11's 54 before manual stop)
- Container: `claude-and-goose-runtime`

## What worked

### 1. Context was load-bearing for the worst failure modes

Direct comparison vs eval-11 (same task, same prompt, only context differs):

| Failure mode | eval-11 (64k) | eval-12 (128k) |
|---|---|---|
| Task conflation (#51 → #50 / hydration_goals) | ❌ wrote wrong-task code | ✅ correct task throughout |
| Host pollution (`/work/backend/` leak) | ❌ stray files in harness | ✅ clean (only `goose.yaml` modified, which is *my* edit) |
| Floundering (`get_me`, `search_repositories`, hallucinated `code_generation_editor`) | ❌ multiple | ✅ none |
| Tool calls before stop | 54 (manually stopped) | 31 (natural stop) |
| Second `create_branch` call | ❌ yes | ✅ no |

All four "bad coherence" failure modes from eval-11 are gone. The model held its place in the task, named the right files, used the right MCP tools.

### 2. Code quality is high

The branch `goose/issue-51-daily-hydration` (sha `b90dcf29`) on `develop` contains:

| File | Status | Notes |
|---|---|---|
| `backend/app/main.py` | +2 / -0 | router registration line |
| `backend/app/routers/hydration.py` | +21 added | `GET /api/hydration/daily` endpoint, Query aliases for `from`/`to`, proper auth + db deps |
| `backend/app/schemas/hydration.py` | +14 added | `HydrationDaily` Pydantic schema |
| `backend/app/services/hydration.py` | +72 added | service layer wrapping `analytics.get_daily_series` |

Same patterns the issue spec asked for (Query alias, FastAPI dep injection, delegating to the analytics service). Missing the test file (eval-11 didn't get there either), but the production code is correct.

### 3. Marquee fixes from PR #44 still hold

- `create_branch from_branch: develop` ✓
- Wrapper-injected `base_branch=develop` ✓
- All four AGENTS.md paths attempted in order ✓ (model narrated: *"All AGENTS.md files are 404 — no additional guidance. The issue has all required sections... Let me now explore the repo and fetch referenced files."*)

## What didn't

### 1. No PR opened, no issue comment

Same as eval-10 and eval-11. Recipe Step 5 and Step 6 weren't executed. The model wrote the production code, registered the router in `main.py`, and announced intent to inspect one more file:

> *"Good, main.py is updated. Now I need to check on the analytics service to verify the `get_daily_series` function exists and understand its interface."*

Then emitted nothing further. Exit 0, no error. **This is the model treating the response as complete** — not a stream truncation (the sentence is grammatically finished, no mid-token cutoff). Goose interpreted it as end-of-generation and stopped.

This is **not a context issue**. We've gone from 64K to 128K. If context were the gate, the model would have made more progress this run. Instead it stopped at almost the same point eval-10 did — both around 7 file writes in.

### 2. `git clone` attempted once

Same as eval-10/-11. One SSH-style attempt (`git@github.com:...`), failed because no ssh in container. The "Never run git clone" rule still drops when the model gets confused about `/work` vs the target repo. Backstops held.

### 3. Test file not written

The issue's Acceptance criteria implies tests; the model didn't get to them before stopping. Related to the workflow-completion gap.

## Hypothesis for the persistent gap

The model is hitting a "natural stopping point" mid-task rather than running out of resources. Three sub-hypotheses, in order of testability:

1. **Recipe Step 5 wording is too soft.** `# Step 5 — Open the PR (only if files changed)` makes PR creation conditional. The model may be parsing the parenthetical as a *test* it has to consciously decide on, and on a chain-of-thought turn focused on subtask completion, that test never gets re-evaluated. **Cheap fix to try**: rephrase Step 5 to be unconditional given that earlier steps already pushed files.

2. **Recipe is too long for qwen3.6 to coherently traverse Steps 3-6 in one chain.** The model gets through subtasks (Step 3), but synthesis steps (4-6) are far from where its current focus is in the prompt. **Cheap fix to try**: move PR-creation guidance closer to Step 3, or restructure so each push includes a "if this is the last file, open the PR" line.

3. **Model capability ceiling.** qwen3.6 / qwen35moe may not be a strong instruction-follower over long procedural recipes. Other models might handle this better even with the same prompt. **Tests this**: #47 bake-off.

(1) and (2) are recipe iterations, cheap. (3) is the bigger experiment.

## What this means for #45 / #47

**#45's hypothesis space is narrower now.** Context-saturation is partially confirmed (it explains task conflation + pollution + floundering) but doesn't explain the workflow-completion gap. So:

- **Keep the 128K context bump.** It's a real improvement, validated end-to-end. Worth merging on its own.
- **The PR-completion gap is a separate, narrower problem.** Next experiment: trial the Step 5 rephrasing (cheap, single-recipe-edit).
- **#47 bake-off is more relevant than it looked an hour ago.** If multiple recipe-prompt iterations don't crack the PR-completion gap, the bake-off becomes the path forward.

## Action items

- **Merge the context bump** (experiment branch `experiment/qwen3.6-128k-context`). Real win on its own merits.
- **File a follow-up**: investigate recipe Step 5 wording for unconditional PR opening on push success. Probably one cheap eval to test the fix.
- **#47 (bake-off) should be the next non-cheap experiment** if Step 5 rephrasing doesn't close the gap.

## Follow-ups beyond this eval

- The `git clone` rule continues to drop under multi-file backend pressure (1 attempt this run vs 2 in eval-11). Independent of context budget. Runtime guardrail likely the right home.
- Per-step recipe instructions seem to lose salience the further the model gets from them in the chain. Worth thinking about whether the recipe should re-state PR + comment expectations inline with the final push, not as separate later steps.

## Next time

- Hardware-utilization observation → architecture discovery (qwen35moe MoE) → context-budget hypothesis → cheap experiment → meaningful improvement. Good loop.
- The remaining failure mode (workflow incompletion) is now isolated from the others. That's progress even though the eval is PARTIAL.
- Three runs at this task (eval-10, eval-11, eval-12) was the right size to characterize what context does and doesn't fix. Won't need to repeat the same scope on the next experiment.
