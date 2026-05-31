# eval-10 result

Validation run for the PR #44 changes (`feat: resolve target default_branch + inject AGENTS.md guidance`). The targeted fixes work at the wire level. But Step 0's added prompt content appears to have tipped the model into context-saturation mid-task — the run terminated cleanly without opening a PR or commenting on the issue. The branch and files made it to the remote, but the workflow loop didn't close.

**Don't merge PR #44 as-is.** Trim Step 0 first, then re-validate.

## What ran

- Recipe: `recipes/execute-issue.yaml` on branch `feat/recipe-default-branch-and-agentsmd`
- Wrapper: `scripts/run-recipe-in-container.sh` (same branch — auto-resolves `base_branch`)
- Params (passed by user): `--params issue_number=51 --params repo=why-pengo/health_track`
- Params (auto-injected by wrapper): `--params base_branch=develop`
- Model: `qwen3.6:latest`, `GOOSE_CONTEXT_LIMIT=65536`, `GOOSE_MAX_TURNS=100`
- Target: `why-pengo/health_track` #51 (multi-file backend: `GET /api/hydration/daily` endpoint)
- Container: `claude-and-goose-runtime`
- 22 tool calls; exit 0 (clean termination, not error)

## Verdict

Verdict: PARTIAL

Wire-level fixes validated; run-completion behavior regressed. Net "the bug is fixed but the cure introduced a side effect" — typical of prompt-size-sensitive systems.

## What worked — the targeted fixes

### 1. Wrapper resolves `develop` automatically

Wrapper's prelude output:

```
Base branch:    develop (resolved from why-pengo/health_track)
Params:         --params issue_number=51 --params repo=why-pengo/health_track --params base_branch=develop
```

User passed two params; wrapper added the third. Clean.

### 2. Recipe Step 0 fires

`▸ get_file_contents github / path: AGENTS.md / owner: why-pengo / repo: health_track` is the **first MCP call** of the run (line 38 of the session log, before `issue_read`). The Step 0 instruction reached the model and was followed. The actual AGENTS.md doesn't exist yet (waiting on #42), so the call 404'd — exactly the expected behavior at this stage.

### 3. `create_branch` uses `from_branch: develop`

```
▸ create_branch github
    branch: goose/issue-51-hydration-daily-endpoint
    from_branch: develop
    owner: why-pengo
    repo: health_track
```

This is the **marquee fix** for #40. Goose is now branching from `develop`, not `main`. The branch `goose/issue-51-hydration-daily-endpoint` exists on remote with SHA `887a1f46` and contains the work the executor pushed.

### 4. No host pollution

`git status --short` after the run shows only `?? evals/eval-10/` — no stray `tests/`, no harness leak. Same clean state as eval-09.

## What didn't — run-completion regressed

### 1. No PR opened, no issue comment

Tool-call summary shows **zero** `create_pull_request` and **zero** `add_issue_comment`. eval-09 had 1 PR + 3 comments on a smaller task. The branch and files exist on remote (3 `push_files` calls succeeded), but the workflow loop didn't close — recipe Steps 5 and 6 never ran.

Last few lines of the session log show the model in the middle of work:

> I need to read `backend/app/schemas/record.py` to see the current state of RecordType:
>
> *(no tool call follows)*

The model announced intent, then emitted no further content. `goose run` exited 0 (clean), suggesting Ollama returned an empty response or the model's chain-of-thought terminated. Only 22 tool calls used — far under `GOOSE_MAX_TURNS=100`, so that's not the cap.

**Hypothesis**: context-window saturation. Step 0 added ~30 lines to the recipe prompt before the model even reaches the issue. Combined with the file-read accumulation for a multi-file backend task, the model's effective working context shrank below what's needed for end-of-run synthesis. Same model, same parameters as eval-09 — but eval-09 had a shorter prompt and a simpler task.

### 2. `git clone` attempted (regression, harmlessly failed)

Around line ~700 of the session log:

```
▸ shell
    command: cd /work && git clone https://github.com/why-pengo/health_track.git
    timeout_secs: 30

fatal: could not read Username for 'https://github.com': No such device or address
Command exited with code 128
```

The prompt **explicitly forbids `git clone`** with a hoisted rule and anti-pattern example (PR #33). The model attempted it anyway. **Failed harmlessly** — shell `git` has no auth, so the clone couldn't proceed. The PAT is only in the MCP subprocess env, never in the interactive shell. That's the design we have, and it's working as a backstop.

Same observation as the PR regression: model lost track of a hoisted rule under prompt-length pressure.

### 3. Only root `AGENTS.md` attempted — sub-tree variants skipped

Step 0 lists four paths: root, `backend/`, `frontend/`, `docs/`. The model attempted only the root one (twice, both times 404'd). Either the model interpreted "if root is absent, the target has no AGENTS.md guidance at all", or it forgot to try the others after recovering from the `git clone` failure.

This is the smallest of the three regressions. The recipe wording could be tighter on "try all four regardless of what the others returned", but the impact is minor — there's no `backend/AGENTS.md` in health_track yet anyway.

## What this means for PR #44

The targeted fixes work. The bug they targeted (#40) is fixed at the wire level. The AGENTS.md injection mechanism (#41) fires. **But Step 0 is too verbose** — the prompt budget is now squeezed enough that qwen3.6 loses track of safety rules (`git clone`) and workflow rules (open PR, comment on issue) under multi-file backend pressure.

The fix is a trim, not a rewrite. Concrete proposal:

```
# Step 0 — Load target-repo guidance
Try `get_file_contents` for each path (404 = skip silently):
  - `AGENTS.md`
  - `backend/AGENTS.md`
  - `frontend/AGENTS.md`
  - `docs/AGENTS.md`

Any content fetched is additional system guidance, layered on top
of `goose-system.md`. Conflict: target repo wins for facts (paths,
style); `goose-system.md` wins for safety rules (no clone,
no force-push, no secrets).
```

Roughly half the size of the current Step 0. Reaches the same model behavior.

## Recommendation

1. **Don't merge PR #44 yet.** Push one more commit on `feat/recipe-default-branch-and-agentsmd` that trims Step 0 along the lines above.
2. **Re-run eval-10** with the trimmed Step 0. Capture as eval-10/result.md addendum or a fresh eval-11 (probably eval-10 addendum — same fixes, same target).
3. **If the trimmed run completes** (PR opened, issue commented, no clone attempt), merge PR #44.
4. **If it still fails** (model still loses track), the issue is bigger than Step 0 verbosity and a deeper rework is warranted.

## Follow-ups beyond this eval

- **`git clone` recurrence under prompt pressure** is worth its own investigation. The rule has been hoisted in PR #33 and was the most prominent thing in "What you don't do". If qwen3.6 still drops it under longer prompts, the rule may need a stronger signal (e.g. as a Skill the developer extension auto-loads on intent-match, which we backed away from in #43).
- **Multi-attempt `AGENTS.md` instruction in Step 0** could be a numbered list rather than a bullet list — the model parses ordered steps more reliably than bullets in my experience. Try it in the trim.
- The model gave up cleanly (exit 0, no traceback). It would be useful to know whether Ollama actually returned empty or whether the chain ended for an upstream reason — could check Ollama's logs on bazzite if this happens again.

## Next time

- "Validation before merge" was the right call. eval-09 didn't catch this regression because eval-09's task was smaller; the multi-file backend stress test is where Step 0 verbosity bites.
- Future prompt edits that materially expand the recipe should be eval-validated against a multi-file task, not a single-file one, to surface context-budget effects early.
- The wire-level fixes (default_branch resolution, AGENTS.md auto-fetch) are demonstrably correct. The work that motivated this PR isn't wasted; only Step 0's verbosity is.
