# eval-17 result

Three-attempt re-roll of the qwen3.6 + recipe + AGENTS.md path against the
canonical `health_track#51` task (the same target eval-10 through eval-14
ran against). Triggered after PR #64 merged AGENTS.md into `health_track`
on `develop` — the first session in which Step 0's four `get_file_contents`
probes return real content rather than 404s.

Goal: validate #42's acceptance criterion — "does AGENTS.md actually load
and matter?" — by re-running #51 and comparing code-quality against
eval-14 (the baseline, run without AGENTS.md content).

Result: **the acceptance criterion remains unmeasured.** Three consecutive
attempts (17, 17b, 17c) all terminated before the model wrote any code.
The three runs failed in three different shapes, but with the same root
cause: model emits text suggesting completion or hand-off → no follow-up
tool call → goose treats session as done. AGENTS.md's content effect on
code quality cannot be evaluated because no run reached the code-writing
phase.

The infrastructure side did validate cleanly — see "What worked" below.

## Verdict

Verdict: FAIL

The experiment failed at "qwen3.6 reliably completes the recipe with
AGENTS.md loaded into Step 0." All three retries terminated early with
zero code written, zero `push_files`, zero `create_pull_request`, zero
issue comments. (The verdict is FAIL per `evals/README.md`'s machine-
readable convention; the more nuanced framing is "AGENTS.md content
effectiveness is unverifiable today, pending a fix to the reliability
regression.")

## What ran

- Recipe + wrapper: latest `main` after PR #64 (AGENTS.md in `health_track`)
  and after PR #52 (HW baseline / model-swap evidence).
- Model: `qwen3.6:latest`, GOOSE_CONTEXT_LIMIT 131072, `GOOSE_MAX_TURNS=100`.
  qwen3.6 digest confirmed unchanged on `bazzite.local` since eval-14 (so
  this is not upstream model drift).
- Params: identical across all three retries — `issue_number=51`,
  `repo=why-pengo/health_track`. Wrapper auto-injects
  `base_branch=develop`.
- Target task: `health_track#51` — `GET /api/hydration/daily` endpoint.
  Same task targeted in eval-10 through eval-14.
- Logs: `evals/eval-17/goose-session.log`,
  `evals/eval-17b/goose-session.log`, `evals/eval-17c/goose-session.log`.

## What worked

### 1. AGENTS.md mechanically loads

eval-17b and eval-17c both fired all four Step 0 `get_file_contents` probes
against `health_track`:

- `AGENTS.md` (root) → content (~180 lines)
- `backend/AGENTS.md` → content (~340 lines)
- `frontend/AGENTS.md` → content (~250 lines)
- `docs/AGENTS.md` → 404 (file doesn't exist — expected; the recipe probes
  for it speculatively)

PR #44's "inject AGENTS.md guidance" wiring is end-to-end validated. In
eval-15/16 the same probes returned 404s because the files didn't exist;
now they return real content. This is reusable infrastructure for any
future evaluation.

### 2. Recipe Step 0 ordering held in 17b/17c

Both runs read the issue (`issue_read #51`) before the AGENTS.md probes,
then the context files the issue references (`analytics.py`, sleep router,
`test_sleep.py`). Same sequence eval-14 followed. The recipe's
context-gathering shape is intact.

### 3. Self-correction signal in 17b/17c

Both runs initially tried `/work/backend/app/...` (the
`claude_and_goose` mount, not the target repo) and then recovered by
switching back to `github__get_file_contents`. That's the model
recognising the mounted-repo confusion and self-correcting — a
positive in-context reasoning signal. eval-17b additionally produced a
clear textual reflection: "I see — the `/work` directory is not the
health_track repo. Per the rules, I should only use MCP tools."

### 4. eval-17c reached `create_branch`

Notably, eval-17c successfully created
`goose/issue-51-hydration-daily` on `health_track` before terminating.
This is further than eval-15/16 and proves the model can advance past
context-gathering into write-phase tool calls. But no commits were
pushed onto the branch — see failure modes below.

## What didn't

Three retries, three failure shapes — all sharing one root cause.

### eval-17 — terminated after Step 0 system-prompt read

- Log: 187 lines, 1 tool call.
- Sequence: model's first action was `shell: cat /work/prompts/goose-system.md`.
  Shell returned the full ~5,000-char system prompt as stdout. Model
  then emitted no further text and no further tool calls. Session ended.
- Hypothesis: model treated the shell stdout (which is itself the
  instruction text it was supposed to be following) as a "completion of
  the read step" and produced no follow-up.

### eval-17b — terminated mid-exploration

- Log: 352 lines, ~21 tool calls.
- Sequence: shell-cat system prompt → issue_read → 4 AGENTS.md fetches
  (success) → analytics.py → sleep router → wrong-path shell attempts
  → MCP recovery → 8 more context reads → terminated mid-flight at line
  352 with no further tool calls or model text.
- Hypothesis: model was still in exploration phase, emitted a turn
  with no tool call and no clear "I'm done" text, and goose closed the
  session. No `push_files` ever attempted.

### eval-17c — loss-of-frame, "delegate to sub-agent"

- Log: 307 lines, 18 tool calls.
- Sequence: same as 17b through context-gathering, then
  `list_branches` → `create_branch goose/issue-51-hydration-daily`
  (succeeded) → read 2 more reference files → emitted:
  > "I have all the context I need to execute issue #51 [...] Let me
  > delegate this to a sub-agent that can work through the requirements
  > methodically."
  
  Then `shell: cd /work && echo "Ready to create hydration daily
  endpoint"` and terminated.
- Hypothesis: classic loss-of-frame. The model invented a "delegate to
  sub-agent" capability that does not exist in Goose, gave a
  placeholder shell command in lieu of actually proceeding, and the
  session ended.

### The shared root cause

In all three runs: model emits a turn whose payload is either
(a) text suggesting completion / hand-off, or (b) a no-op tool call →
goose interprets the turn as terminal → session ends with exit 0.

`GOOSE_MAX_TURNS=100` was never hit — tool-call counts (1, 21, 18) are
nowhere near the cap. Goose is terminating because the model is
signalling "done," not because it ran out of budget.

## The reliability-cliff hypothesis

The diff between eval-14 (1551 lines, 5 commits, full PR) and the
eval-17 series (sessions stopping at 187 / 352 / 307 lines, no commits)
is small:

1. PR #51 merged — Step 3 push_files-vs-developer-write callout adds
   ~30 lines to the recipe.
2. PR #64 (this session) — AGENTS.md content landed in
   `health_track:develop`. Each Step 0 fetch that previously returned
   404 now returns hundreds of lines of content.

Combined, Step 0 now spends meaningfully more tokens before the model
reaches the "implement the task" phase. The hypothesis: that early
context spend pushes qwen3.6 into a state where it loses recipe-frame
earlier — manifesting as the various "emit something, stop" behaviours
above.

This is **testable by bisection** (revert one change at a time and
re-run) but out of scope for this eval. Filed as a follow-up issue
against #45.

## What this preserves

- **End-to-end AGENTS.md wiring confirmed working.** Step 0 fetches
  fire and return real content. Future runs against any repo with an
  `AGENTS.md` will have it loaded into the executor's context.
- **eval-17c proves write-phase capability is reachable.** Not just
  reads — `create_branch` worked, which means the path from
  context-gathering to actual repo mutation is open when the model
  doesn't lose frame.
- **Methodology lesson.** Single-shot evaluations of a probabilistic
  executor are not interpretable. The three retries with three
  distinct failure shapes show that what looks like an isolated bug
  on any one run can be a structural reliability issue across
  retries. Future evals should bake in a k-of-n attempt convention or
  be explicit about which runs are anecdote vs evidence.

## Follow-ups

- **File a new issue under #45** capturing the reliability-cliff
  hypothesis and a bisect plan: (a) revert PR #51 Step 3 callout +
  re-run, (b) revert AGENTS.md content (or run against a repo without
  it) + re-run, (c) cross-tabulate to identify which change
  regressed.
- **Delete the orphan branch** `goose/issue-51-hydration-daily` on
  `health_track` — it has only the `develop` HEAD commit (the AGENTS.md
  merge), no Goose-authored changes.
- **Do not yet ship eval-17/17b/17c work to `main`.** The data is
  real but the cause is unknown. Once the bisect points to the
  regressor, then bundle and PR.
- **Add to harness backlog**: investigate why goose terminates
  exit-0 when the model emits an empty/placeholder turn instead of
  prompting the model to continue or warning explicitly. Today's
  silent termination is hard to debug — at minimum the wrapper could
  detect "no `push_files` + no `create_pull_request` after N tool
  calls" and log a warning.

## Next time

- Run the bisect described in the follow-up issue before any new
  AGENTS.md-related work, so we know whether the regression is from
  PR #51 (recipe text) or PR #64 (target-repo content) or both.
- For any new harness change that touches the executor's prompt or
  Step 0 fetched content, plan for k-of-n re-roll evidence rather than
  a single eval. This session demonstrates how easily a single lucky
  run (eval-14) can mask a real regression that 3-of-3 retries expose.
- If the bisect points to AGENTS.md content as the cause, consider
  whether the recipe's Step 0 should fetch all three files
  unconditionally, or whether it should be selective (e.g. only fetch
  the AGENTS.md most relevant to the issue's domain). Smaller Step 0
  budget might restore eval-14-class reliability.
