# eval-13 result

Validation run for PR #49 (`GOOSE_CONTEXT_LIMIT: 65536 → 131072` + Step 5/6 rewrite). Goal: determine whether the unconditional, push-tied Step 5/6 wording closes the workflow-completion gap that eval-12 left open.

Result: **the experiment didn't test what it was designed to.** Step 5/6 never had a chance to fire because Step 3 broke earlier — the model wrote files to the container's local filesystem instead of pushing them via the GitHub MCP, so "the moment your last file is pushed" (the trigger Step 5 was rewritten around) never happened.

## Verdict

Verdict: FAIL

Path-discipline regression (use `push_files` / `create_or_update_file`, not the developer extension's `write`) blocked the run before the rewrite could be evaluated. Same shape as eval-11's mixed-tool failure, but more complete — eval-11 mostly used MCP and slipped once; eval-13 used the wrong tool for *every* file write. The Step 5/6 rewrite remains unvalidated in practice.

## What ran

- Branch: `main` (PR #49 merged as `475c3d9`)
- Recipe + wrapper: post-PR-#49 (context bump + Step 5/6 rewrite + AGENTS.md Step 0 + default_branch resolution)
- Model: `qwen3.6:latest` (= `qwen35moe`, MoE, 262144 native context)
- Params: `--params issue_number=51 --params repo=why-pengo/health_track` (wrapper auto-injected `base_branch=develop`)
- Target task: same as eval-10/11/12 — `health_track` #51 (multi-file backend, `GET /api/hydration/daily`)
- 22 tool calls total
- Session log: 994 lines

## Tool-call breakdown

| Tool | Count | Notes |
|---|---|---|
| `shell` (developer) | 2 | one initial, one `head` to verify own writes |
| `issue_read` (github) | 1 | Step 1 ✓ |
| `get_file_contents` (github) | 13 | Step 0 + Step 1 context loading ✓ |
| `list_branches` (github) | 1 | Step 2 prep ✓ |
| `create_branch` (github) | 1 | from `develop` ✓ |
| `write` (developer) | **2** | **wrote to `/work/`, not to GitHub** |
| `edit` (developer) | 2 | fixing an `asyncio.gate` hallucination |
| `push_files` / `create_or_update_file` | **0** | never called — root cause |

No `create_pull_request`, no `add_issue_comment`. Naturally, since no files were pushed.

## What worked

### 1. Step 0 (AGENTS.md fetch) and Step 1 (issue read) clean

All four AGENTS.md paths attempted (`AGENTS.md`, `backend/AGENTS.md`, `frontend/AGENTS.md`, `docs/AGENTS.md`), all 404 (expected — #42 not done yet), narrated cleanly. `issue_read` on #51 was the first GitHub call.

### 2. Step 2 (branch creation) clean

`list_branches` then `create_branch` from `develop` with slug `goose/issue-51-hydration-daily-endpoint`. The wrapper-injected `base_branch=develop` was honored end-to-end. Branch existed on health_track at HEAD = `develop` HEAD (i.e. empty — never received any commits).

### 3. 128K context bump held its gains from eval-12

Comparing to eval-11 (the closest comparable failure mode):

| Failure mode | eval-11 (64K) | eval-13 (128K) |
|---|---|---|
| Task conflation (#51 → #50) | ❌ wrote wrong-task code | ✅ correct task throughout |
| Multiple `create_branch` calls | ❌ yes | ✅ one |
| `git clone` attempted | ❌ twice | ✅ zero |
| Hallucinated tools (`code_generation_editor`) | ❌ multiple | ✅ none |

Coherence wins from eval-12 carried over. This isn't a context regression.

## What didn't

### 1. Wrong tool for every file write (the root cause)

The model used the developer extension's `write` to create files inside `/work/`:

| Call | Path | Size |
|---|---|---|
| `write` #1 | `backend/app/schemas/hydration.py` | 19 lines |
| `write` #2 | `backend/app/services/analytics.py` | **574 lines (overwrote a hallucinated rewrite)** |

The second `write` is particularly bad: `analytics.py` already exists in health_track with real content (sleep functions, etc.). The model fabricated 574 lines of "what analytics.py probably looks like" — most of it plausible-looking sleep code — and `write` clobbered the local copy with that fabrication. Then it spent two `edit` calls fixing an `asyncio.gate` typo *inside the fabrication*.

Because `write` targets the container's filesystem and not GitHub, none of this reached health_track. The branch on health_track stayed empty.

This also produced **host pollution**: the harness repo (mounted at `/work`) gained an untracked `backend/` directory after the container exited. Cleaned up post-run by `rm -rf backend/`.

### 2. Step 5 + Step 6 unreachable

The whole point of the run was to test whether the rewritten Step 5 ("the moment your last file is pushed, call `create_pull_request`") fires reliably. Because Step 3 never pushed, the trigger condition was never met. The Step 5/6 rewrite remains untested.

### 3. Scope creep at the end

Final narration:

> *"Good, the analytics service is correct. Now let me check the sleep router to add date filters:"*

Then no further output. Sleep router isn't part of #51. The model invented additional work, stopped emitting before doing it. Either the model treated this as a clean stop or hit some upstream limit (no error in the log, exit 0 — looks like a clean stop).

### 4. Run-to-run variance on path discipline

eval-12 used `push_files` correctly. eval-13 (same model, same prompt, same context limit) used `write`. Nothing in PR #49 should have changed this — context grew, Step 5/6 was rewritten, but the Step 3 path-discipline guidance is the same. This is a brittleness signal: the model isn't reliably choosing the right tool family across runs.

## Why this might be happening

Three hypotheses, ordered by how cheaply they can be tested:

1. **`developer.write` is more "natural" to the model than MCP `push_files` for code-authoring tasks.** The developer tools look like an IDE/shell; `push_files` looks like a remote API. When the model is in "writing code" mode (Step 3 is procedural code work), it gravitates to the more code-shaped tool. The system prompt does say to use `push_files` (goose-system.md L84), but that rule may be losing salience by the time Step 3 runs.

2. **The recipe doesn't reinforce path discipline at Step 3.** Step 3 currently says: *"For each checklist item: Make the single concrete change it describes. Verify it. Commit with a conventional-commit message."* No mention of which tool to use to make the change. The "which tool" rule lives in goose-system.md, separated by hundreds of lines of other context. A single-line callout in Step 3 ("Use `push_files` or `create_or_update_file` — never `write` — to send code to the target repo") could be cheap and load-bearing.

3. **Same root as the workflow-completion gap.** Both this and the eval-12 PR-creation gap are forms of "model loses track of late-stage workflow rules under prompt+tool-result pressure". The fix might not be more rules but fewer steps / shorter recipe / runtime guardrail.

## What this means for #45 / #47 / #50

- **The workflow-completion gap remains the open question** — eval-13 didn't move it either way.
- **Path discipline is brittle across runs**, not robustly held. Strengthens the case that prompt iteration alone isn't enough.
- **#50 (offload) and #47 (bake-off) become more attractive** — if the prompt-only path keeps surfacing new failure modes, bigger models or different architectures may be the more reliable path forward.
- Worth one cheap recipe iteration to test hypothesis (2) — add the Step 3 tool-callout — before declaring prompt iteration exhausted. That's eval-14.

## Action items

- [ ] **Strengthen Step 3 with explicit tool guidance.** One sentence: "Use `push_files` (multi-file) or `create_or_update_file` (single-file). Never the developer extension's `write` for code that needs to reach the target repo — that writes to the container, not GitHub."
- [ ] **Run eval-14** with the Step 3 callout against #51 again. If the model uses `push_files` and lands on the original workflow-completion question, the Step 5/6 rewrite finally gets tested.
- [ ] **Restore #51 to `ready-for-execution`** (label may have been removed by the partial run, verify).
- [ ] Capture this as evidence in #45 — path discipline is run-to-run brittle, not just a one-time eval-11 slip.

## Follow-ups beyond this eval

- Consider whether `developer.write` should be disabled entirely for cross-repo runs. The recipe knows whether `repo` is the harness or a different target — there's no scenario in cross-repo execution where writing to `/work/` is correct. Could be a runtime guardrail (extension filter) rather than another prompt rule.
- The "model fabricates a 574-line file then edits typos in the fabrication" loop is a striking failure mode — the model has no way to detect it was hallucinating because it has no ground-truth view of the real file's content. `get_file_contents` to read the target file before overwriting would be the disciplined pattern. Worth a prompt hint.

## Next time

- Three attempts at #51 (eval-10, eval-11, eval-12) characterized the workflow-completion gap. Now a fourth attempt (eval-13) showed path discipline is also brittle. Future runs at this task should switch up the variable — same task, different model (#47) is the next non-cheap experiment after the cheap Step 3 callout.
- The eval-13 framing assumed Step 5/6 was the next bottleneck. It wasn't. Pre-flight question for future evals: "what's the *earliest* step we still distrust?" — and design the eval to land there.
