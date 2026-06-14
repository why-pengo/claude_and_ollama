# eval-23 result

Reproducibility check for eval-22's 3/3 PASS. Same task, same model,
same runner code (now on `main` @ 82879a1 after PR #54 merged) plus the
post-merge fixes (ae87496, 7ca2fa5). The eval-22 batch was the best
single-batch result the runner had produced (3/3 model PASS); the
question this batch asks: was it variance, or is the runner now
reliably 3/3-shaped?

k-of-3 on `health_track#51`. State reset between attempts.

Result: **2-of-3 model PASS + 1-of-3 salvage PASS = 3-of-3 review-able
artifacts.** The eval-22 3/3 didn't reproduce as a model-PASS run, but
salvage caught the partial cleanly and produced a real PR. This is the
first time salvage has fired in a live eval — the integration path is
now validated in flight, not just by smoke test.

## Verdict

Verdict: PASS

3-of-3 attempts produced a real PR with the implementation on it
(eval-23: PR #71 model; eval-23b: PR #72 salvage; eval-23c: PR #73
model). All three are review-able artifacts. The salvage attempt
posted both the PR and the `⚠️ partial` status comment as designed.

I'm calling this PASS even though it's not 3/3 model-PASS because the
harness's contract is "produce a review-able PR" and it did that in
every attempt. The model variance is real but salvage caps the
downside.

## What ran

All three attempts (eval-23, eval-23b, eval-23c) used identical
configuration:

- Branch: `main` @ 82879a1 (PR #54 squash-merged) plus follow-on fix
  commits ae87496 (code review correctness fixes) and 7ca2fa5
  (Copilot review fixes — URL encoding in salvage, etc.)
- Model: `qwen3.6:latest`
- Recipe + system prompt: post-merge state with `{{ base_branch }}`
  templating fixed
- Target: `health_track#51` — `GET /api/hydration/daily`
- State reset between attempts: PR closed, branch deleted.

Logs: `evals/eval-23/goose-session.log`,
`evals/eval-23b/goose-session.log`,
`evals/eval-23c/goose-session.log`.

## What happened — per attempt

### eval-23 — model PASS (turn 15, 17 tool calls, 4 nudges)

```
Step 0:  get_file_contents AGENTS.md  ✓
Step 1:  issue_read + 8 × get_file_contents  ✓
Step 2:  create_branch + shell (read-only)  ✓
Step 3:  3 × create_or_update_file
         [model emitted prose — 96 chars]
         [runner nudge → Step 5]
         → get_file_contents (verifying)
         [model emitted prose — 88 chars: "Confirmed the typo
          (Workop.start_dt at line ~189). Fixing it now..."]
         [runner nudge → Step 5]
         [runner nudge → Step 5]
         → github__create_pull_request  ✓ PR #71
Step 6:  [model emitted prose — 112 chars announcing PR opened]
         [runner nudge → Step 6 (add_issue_comment)]
         → github__add_issue_comment  ✓
```

This attempt is notable for two firsts:

1. **First time the Step-6-specific nudge fired in a live eval.** Model
   emitted prose ("PR #71 opened at ...") *after* `create_pull_request`
   succeeded but *before* calling `add_issue_comment`. The step-aware
   nudge correctly identified that `create_pull_request` had fired and
   `add_issue_comment` hadn't, and pushed for Step 6 specifically. Model
   recovered into the comment call.
2. **Model self-corrected a code typo mid-flight** ("Workop.start_dt"
   should be `Workout.start_dt`). Re-fetched the file, fixed it, then
   proceeded.

4 nudges is more than any eval-22 attempt, but the model recovered from
every one.

### eval-23b — SALVAGE PASS (turn 17, 21 tool calls, 3 nudges, salvage fired)

```
Step 0:  get_file_contents AGENTS.md  ✓
Step 1:  issue_read + 9 × get_file_contents  ✓
Step 2:  create_branch + 3 × get_file_contents  ✓
Step 3:  create_or_update_file + push_files + 2 × create_or_update_file
         + push_files (4 commits)
         [model emitted prose — 24 chars]
         [runner nudge → Step 5]
         → create_or_update_file (test file — last subtask)
         [runner nudge → Step 5]   [silent turn]
         [runner nudge → Step 5]   [silent turn]
[3 consecutive no-tool-call turns; runner gave up at turn 17]
[Salvage attempt: branch=goose/issue-51-hydration-daily → develop]
  ✓ Salvage PR opened: #72 (4 commits)
  ✓ Salvage comment posted on #51 (⚠️ partial)
```

The eval-21/22 failure pattern. Model committed everything, hit the
Step 5 boundary, fired one more file-write (the test) after the first
nudge, then went silent. The salvage path fired correctly:

- `_extract_branch` pulled `goose/issue-51-hydration-daily` from the
  `create_branch` tool_call args
- `_extract_issue_title` parsed the `issue_read` result for the title
- `salvage_pr` returned `status: opened` with PR #72 and 4 commit count
- `salvage_comment` posted the `⚠️ partial` status to #51

PR #72 has the same content the model would have opened itself — just
with the "Salvaged by `runner/salvage.py`" footer and a templated body
instead of the model's own summary. Reviewable, mergeable artifact.

This is what the salvage feature was built for. First time it fired in
a live eval (the smoke test and force-fire test were synthetic).

### eval-23c — model PASS (turn 12, 19 tool calls, 1 nudge)

```
Step 0:  get_file_contents AGENTS.md  ✓
Step 1:  issue_read + 8 × get_file_contents  ✓
Step 2:  create_branch  ✓
Step 3:  4 × create_or_update_file + get_file_contents +
         create_or_update_file
         [model emitted prose — 35 chars]
         [runner nudge → Step 5]
         → github__create_pull_request  ✓ PR #73
Step 6:  github__add_issue_comment  ✓
```

Cleanest attempt of the batch. 1 prose-emit turn, 1 nudge, model
recovered cleanly. Note: model self-typo'd `get_hyduction_daily` in the
PR body summary text (should be `get_hydration_daily`) but the actual
code is correct — this is a cosmetic defect in the PR description, not
the implementation.

## What worked

- **3-of-3 review-able artifacts.** Across model PRs and the one
  salvage PR, every attempt produced something reviewable. No dead
  branches.
- **Salvage validated in flight.** eval-23b is the smoking gun — the
  exact eval-21/22 failure mode (model commits, then stalls at Step 5)
  produced a mechanical PR instead of a dead branch. The integration
  path (extracting branch + title from message history, opening PR
  with templated body, posting comment) works end-to-end.
- **Step 6-specific nudge fired for the first time** (eval-23) and
  worked — model emitted prose after `create_pull_request`, runner
  identified that `add_issue_comment` hadn't fired, pushed for it
  specifically, model recovered.
- **All three step-aware nudge templates** (`pre_pr` for Step 5,
  `post_pr_pre_comment` for Step 6, generic continue) exercised in
  one batch.

## What didn't

- **The eval-22 3/3 didn't reproduce.** eval-23 went 2/3 model PASS,
  consistent with the wider variance band the runner has shown across
  batches (0/3 in eval-21, 1/3 in eval-20, 3/3 in eval-22). One batch
  cannot establish reliability when prior batches vary that widely.
- **Model self-typo in eval-23c PR body** (`get_hyduction_daily`).
  Cosmetic — the code is correct. But the PR description misnames the
  function the model just wrote, which is a small quality drift not
  caught by any harness mechanism.
- **eval-23 had 4 nudges** — more than any eval-22 attempt. The model
  needed extra redirection but completed. Not a failure, just a
  variance data point.

## What this means in context

Across all 12 runner attempts now (eval-20, 21, 22, 23):

| Eval | Runner | Salvage | Model PASS | Salvage PASS | Total review-able |
|---|---|---|---|---|---|
| eval-20 | v1 | no | 1/3 | n/a | 1/3 |
| eval-21 | v2 | no | 0/3 | n/a | 0/3 |
| eval-22 | v2 | yes | 3/3 | 0/3 (unused) | 3/3 |
| eval-23 | v2 + fixes | yes | 2/3 | 1/3 | **3/3** |
| **Combined** | | | **6/12** | **1/3** (where applicable) | **7/12** |

With salvage in place (eval-22 + eval-23), the runner has produced **6
review-able artifacts out of 6 attempts** (3 + 3). Salvage took 1
batch to actually fire (eval-22 didn't need it; eval-23 did) but when
it fired it delivered.

Compared to Goose on the same target (eval-17 + eval-19 series:
0-of-6 review-able artifacts), the runner is now reliable at the
"produces a PR to review" level even if the model-only success rate
remains variable.

## What this validates

The architectural thesis from eval-19's writeup:

> The Goose session-loop choice — exit 0 on "no tool call this turn" —
> is the structural ceiling. The direct-Ollama POC is now strongly
> motivated as the architectural fix.

And the eval-20 follow-up that motivated salvage:

> A second failure mode the runner v1 doesn't yet fix: the Step 5
> boundary.

Both are now validated end-to-end. eval-23b is the demonstration that
salvage closes the loop on the second failure mode.

## Action items

- [x] Run eval-23 k-of-3 against post-merge main
- [x] Write up this result
- [ ] Decide on follow-up issue #55 (recipe_done should verify the
  tool result, not just the name) — the model could theoretically
  produce a successful "Recipe complete" exit on a failed
  create_pull_request, hiding the failure. Hasn't happened yet but
  it's a real correctness gap.
- [ ] Decide on follow-up issue #57 (declarative step graph in YAML)
  — the step-aware nudge mechanism is working but the recipe-Python
  duplication is the right altitude question if the harness gains
  more recipes.

## Next time

- The architectural thesis is now thoroughly validated across 4
  batches and 12 attempts. Future runner evals should measure
  *task-specific* reliability (different issues, different recipes),
  not re-validate the runtime choice.
- The eval-22 3/3 was a high-variance reading, not a baseline.
  eval-23's 2/3 + 1 salvage is more representative. Future
  "did this change help?" comparisons should use a stable batch
  baseline — probably the running 6/12 model-PASS rate.
- Salvage's first live fire confirmed all the offline test coverage
  was right. Worth noting as evidence for the methodology: smoke
  test → force-fire integration test → live eval. Each layer caught
  something the next would have missed; nothing was wasted.
