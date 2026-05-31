# eval-11 result

Re-run of eval-10 against `health_track` #51 with **trimmed Step 0**, on the same `feat/recipe-default-branch-and-agentsmd` branch. The trim achieved its specific goal — all four `AGENTS.md` paths got attempted reliably. But a deeper failure mode surfaced: under multi-file backend pressure on `qwen3.6:latest`, the model conflated **#51** (the task this run was given) with **#50** (the earlier task that produced PR #61), wrote `hydration_goals` files instead of `hydration/daily` files, attempted `git clone` twice, and floundered through `get_me` / `search_repositories` / a hallucinated `code_generation_editor` tool before being stopped manually.

PR #44's targeted fixes still validate. The new finding is that **multi-file backend tasks on qwen3.6 have an underlying reliability problem that PR #44 didn't cause and doesn't fix.**

## Verdict

Verdict: PARTIAL

PR #44 targets validated; merge recommended. The deeper multi-file-backend reliability issue is independent and pre-existing — surface in a follow-up.

## What ran

- Same recipe + wrapper as eval-10, on `feat/recipe-default-branch-and-agentsmd`, plus the **Step 0 trim** committed as `c9ab3a3` (~half the verbosity of the original Step 0).
- Params: `--params issue_number=51 --params repo=why-pengo/health_track` (wrapper auto-injected `base_branch=develop`).
- Same target task as eval-10: `#51 — GET /api/hydration/daily` (multi-file backend).
- Deleted the leftover `goose/issue-51-hydration-daily-endpoint` branch from eval-10 first for a clean slate.
- **Run was stopped manually** after ~10 minutes of floundering. Container `docker stop`'d, captured artifacts.
- 54 tool calls before stop (vs eval-10's 22, eval-09's 31, eval-08's 34).

## What worked — the targeted fixes (Step 0 trim)

### Step 0 now reliably tries all four AGENTS.md paths

The eval-10 regression — model attempting only the root `AGENTS.md` — is gone. In eval-11 the model attempted all four paths in order, narrating cleanly:

```
▸ get_file_contents github / path: AGENTS.md
▸ get_file_contents github / path: backend/AGENTS.md
▸ get_file_contents github / path: frontend/AGENTS.md
▸ get_file_contents github / path: docs/AGENTS.md
```

Followed by:

> *"All 4 AGENTS.md files return 404 — none exist. The issue body is complete with Goal, Context, Subtasks, Acceptance criteria, and Out of scope. Let me proceed to Step 2."*

That's the trim doing exactly what it was supposed to. The numbered list + tighter language + explicit "attempt all four" instruction landed.

### Marquee #40 fix continues to hold

```
▸ create_branch github
    branch: goose/issue-51-get-hydration-daily
    from_branch: develop
```

Same as eval-10. `develop` resolution is robust across the verbose-Step-0 and trimmed-Step-0 prompt sizes.

### Wrapper-injected `base_branch` still clean

```
Base branch:    develop (resolved from why-pengo/health_track)
```

Same as eval-10.

## What didn't — the deeper reliability problem

### 1. Task confusion: #51 → #50

The damning evidence: when the run was stopped, **the host pollution in `/work/backend/`** contained:

```
backend/app/routers/hydration_goals.py
backend/app/schemas/hydration_goals.py
```

These are `hydration_goals` files (which is **#50 / PR #61** — already merged). The actual task **#51** is the `hydration/daily` endpoint, a totally different shape. The model started writing the wrong task's code mid-run.

The model re-read the issue 3 times (`▸ issue_read github` × 3) — suggesting it noticed something was off and tried to re-orient, but ended up further confused rather than corrected. Combined with the `▸ tree`, `▸ get_me`, `▸ search_repositories` calls (none of which the recipe asks for), and a hallucinated `▸ code_generation_editor` (not a real tool — got back "Tool not found"), the model was clearly lost.

**Hypothesis**: tool-result accumulation includes content from both `hydration_goals.py` (read via `get_file_contents` for pattern-matching) and `hydration_daily` references (from the issue body). On a context-pressured run, the model started anchoring on the wrong domain.

### 2. `git clone` attempted twice

Both failed harmlessly:

```
▸ shell / cd /work && git clone https://github.com/why-pengo/health_track.git
    fatal: could not read Username for 'https://github.com'

▸ shell / cd /work && git clone git@github.com:why-pengo/health_track.git
    error: cannot run ssh: No such file or directory
```

Defense in depth held: no PAT in shell env, no ssh binary in container. Same pattern as eval-10's single clone attempt — now doubled. The "Never run git clone" rule (hoisted in PR #33) is **dropping under multi-file backend pressure**, independent of Step 0 size.

### 3. Host pollution

The harness `/work/backend/` ended up with two stray Python files. Cleaned up via `rm -rf backend/` post-run. The model wrote files inside `/work` thinking it was the target repo's backend dir, even though it had earlier confirmed via `▸ shell ls /work` that `/work` is the harness (CLAUDE.md, Dockerfile, etc. visible).

Same class of bug as eval-08's `tests/` leak. The match-the-neighbors path-discipline rule in `goose-system.md` (also from PR #39) is **also dropping under multi-file backend pressure**.

### 4. No PR opened (stopped before potential PR)

We stopped the run manually after the floundering became obvious. Two scenarios:

- The model would have eventually produced a PR if we'd let it run (10+ more minutes likely).
- The model was stuck in a confusion loop and a PR would not have appeared.

eval-10 (which we did let run to completion) ended with exit 0 and no PR. eval-11 was on a worse trajectory than eval-10 at the stop point — second `create_branch` call, hallucinated tools, two clone attempts, wrong-task pollution. Generous reading: PR might have eventually appeared. Cynical reading: this run was unrecoverable.

## What this means for PR #44

**The targeted fixes work and are valuable on their own**:
- Cross-repo runs now default to the target's actual integration branch (no more PRs against `main` when the repo uses `develop`).
- AGENTS.md mechanism is wired and ready for #42 to deliver real guidance.
- These hold across both verbose (eval-10) and trimmed (eval-11) Step 0 versions.

**The multi-file-backend reliability problem is pre-existing and independent**:
- eval-08 (no Step 0, hardcoded `main`): produced a PR but with path-slip + missing issue comment.
- eval-10 (verbose Step 0, develop resolution): produced a branch + files, stopped before PR.
- eval-11 (trimmed Step 0, develop resolution): produced a branch + (wrong-task) files, looped into confusion before PR.

Three runs, three different failure modes — but all on multi-file backend on qwen3.6. The common thread isn't anything PR #44 changed. The signal is that **qwen3.6 + multi-file backend** is operating near a reliability cliff.

Single-file or smaller tasks (eval-04, eval-06, eval-07 on harness, eval-09 cross-repo) are fine. Multi-file frontend untested. Multi-file backend specifically is the brittle case.

## Recommendation

**Merge PR #44.** The fix is sound for the bugs it targets. eval-10 and eval-11 both confirmed:
- `develop` resolution works end-to-end (the original #40 bug is solved).
- AGENTS.md fetch mechanism fires reliably (the #41 mechanism is real).

Hold the merge any longer and we're gating it on a problem PR #44 didn't introduce — eval-08 (without these changes) failed in a different but equally significant way.

**File a follow-up issue**: "Multi-file backend tasks on qwen3.6 hit reliability cliff — investigate". Scope of that follow-up:
- Compare three failure modes (eval-08, eval-10, eval-11) for common patterns
- Decide whether to (a) lower task complexity expectations for the model, (b) increase context limit, (c) re-evaluate model choice, (d) split multi-file work into single-file leaf issues at planning time
- May want to test a more capable Ollama model before changing other variables

**Don't re-run eval-11 again**. We have enough data points; another run would just produce a fourth failure mode without changing the answer.

## Follow-ups to file beyond PR #44

- Multi-file backend reliability on qwen3.6 (described above).
- The `git clone` rule needs reinforcement under prompt-pressure. Could try moving it from the prompt into a runtime guardrail — the container backstops are working, but they're catching attempts that the rule should prevent before they happen.
- The path-discipline rule (PR #39's "match the neighbors") similarly drops under pressure — `backend/` pollution in eval-11 wouldn't have happened if it had held.

## Next time

- **Validation-before-merge surfaced a problem we couldn't have caught by review alone.** That practice continues to pay off.
- **Two eval runs were enough to characterize the multi-file-backend issue.** A third would have been waste; cut the loss when the pattern is clear.
- **Pollution check (`git status` after every run)** has become the most-load-bearing post-run-check. Worth promoting to the wrapper's exit path: print `git status --short` automatically.
