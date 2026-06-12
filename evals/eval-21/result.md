# eval-21 result

Second eval of the direct-Ollama runner, this time with the
step-aware no-tool-call escalation patch (commit 1dabd93). eval-20
exposed that the runner's generic "what's your next tool call?"
rescue prompt wasn't enough at the Step 5 boundary — 2-of-3
attempts committed all the work but stalled before
`create_pull_request`. The hypothesis for v2: a more specific
nudge that tells the model *which* tool comes next (rather than
asking it to identify the step) would close that gap.

k-of-3 on the same `health_track#51` target, same model, same
slimmed harness — only the runner code changed.

Result: **0-of-3 full PASS, 2-of-3 reach write phase.** The
step-aware nudge didn't help. It may have hurt — relative to
eval-20 (1-of-3 PASS, 3-of-3 reach write phase), v2 regressed on
both metrics.

## Verdict

Verdict: FAIL

The iteration didn't move the needle. The step-aware nudge fires
correctly (recovers the model from silence into making a tool call
in 2 of its activations) but the model fires the *wrong* tool —
another `create_or_update_file` or a `get_file_contents`, never
the prescribed `create_pull_request`. After 3 consecutive no-tool-call
turns the runner gives up, just like eval-20b/c.

The 0-of-3 PASS is a real refutation of the "more specific nudge"
theory. The Step 5 boundary failure isn't about nudge specificity.

## What ran

All three attempts (eval-21, eval-21b, eval-21c) used identical
configuration:

- Branch: `feature/tool-call-discipline` @ 1dabd93 (runner v2 with
  `step_aware_continue_prompt`)
- Model: `qwen3.6:latest`
- Recipe + system prompt: same slimmed state as eval-20 (6f1e55a +
  9f6631d)
- Target: `health_track#51`
- State reset between attempts: branch deleted before each.

The step-aware nudge logic (in `runner/run_recipe.py:tools_called`
and `step_aware_continue_prompt`):

- If `create_pull_request` fired but `add_issue_comment` didn't →
  nudge specifically for the comment with PR link + status emoji
- If any file-write fired but `create_pull_request` didn't → nudge
  specifically for `create_pull_request` with required body shape
- If `create_branch` fired but no file-writes → nudge for Step 3
  start
- If `issue_read` fired but no branch → nudge for Step 2
- Otherwise: generic "call the next tool"

Logs: `evals/eval-21/goose-session.log`,
`evals/eval-21b/goose-session.log`,
`evals/eval-21c/goose-session.log`.

## What happened — per attempt

### eval-21 — PARTIAL: 6 commits, 4 nudges ignored, no PR

```
Step 0-2: clean (issue + AGENTS.md + 10 context reads + branch)
Step 3: 6 × create_or_update_file
        [model emits 39-char prose; no tool call]
        [runner: nudge — "Step 5 mandatory. NEXT TOOL CALL: create_pull_request"]
        → model fires create_or_update_file (NOT the requested PR)
        [model emits 210-char prose; no tool call]
        [runner: nudge — same]
        → model fires get_file_contents (still not PR)
        [runner: nudge — same]
        [runner: nudge — same]
[3 consecutive no-tool-call turns; runner gives up at turn 17]
```

The key observation: the step-aware nudge **recovered the model
from silence to tool-calling twice**, but the model chose tools
other than what the nudge prescribed. The runner's strike counter
resets on any tool call (correct behavior), so the model could
loop indefinitely making wrong tool calls without triggering
give-up. Only when the model went truly silent for 3 turns did
the strike count exit.

### eval-21b — PARTIAL: stopped at end of Step 2

```
Step 0-1: clean
Step 2: create_branch  ✓
Step 2 extra: 2 more get_file_contents (reading reference patterns)
        [model emits 80-char prose; no tool call]
        [runner: nudge — "Branch created. Continue with Step 3 — push_files"]
        → no response
        [runner: nudge — same]
        → no response
[3 consecutive no-tool-call turns; runner gives up at turn 9]
```

The earliest stall of any runner-based attempt. Model never started
Step 3 file writes. The Step-3-specific nudge fired (twice) but the
model just didn't engage. Empty branch left on `health_track`.

This is qualitatively different from eval-21/21c — those reached
Step 3 and committed code; 21b never crossed into the write phase
at all.

### eval-21c — PARTIAL: 6 commits, 3 nudges ignored, no PR

```
Step 0-2: clean (one extra context-read interleaving)
Step 3: 5 × create_or_update_file
Step 3 extra: 1 get_file_contents
        [model emits 25-char prose; no tool call]
        [runner: nudge — "Step 5 mandatory. NEXT TOOL CALL: create_pull_request"]
        → model fires create_or_update_file (still ignoring)
        [runner: nudge — same]
        [runner: nudge — same]
[3 consecutive no-tool-call turns; runner gives up at turn 16]
```

Same pattern as eval-21. The model recovered from one prose-emit
turn but with the wrong tool, then went silent.

## What worked

- **The step-aware logic correctly identifies the phase.** All
  nudges fired with the right step-specific instruction (Step 3 for
  21b, Step 5 for 21 and 21c).
- **Nudges still work for recovery from silence to tool-calling.**
  In eval-21, model recovered from 2 prose-emit turns into making
  tool calls (just wrong ones).
- **Logging is better.** The `[runner: nudging — "..."]` markers
  in eval-21 logs make the recovery attempts visible, which the v1
  runner lacked.

## What didn't

- **Nudges don't redirect the model.** Telling qwen3.6 "your NEXT
  TOOL CALL must be `github__create_pull_request`" 4 times in a row
  did not produce `github__create_pull_request`. The model has
  internal state ("not done yet with subtasks" or "still verifying")
  that overrides the user-role nudge text.
- **eval-21b stalled earlier than any v1 attempt** — at the end of
  Step 2 instead of the Step 5 boundary. Possible explanations:
  (a) the new specific nudge for Step 3 was less recognizable than
  the v1 generic nudge, (b) sampling variance with k=3.
- **0-of-3 full PASS vs v1's 1-of-3** — the iteration ate the one
  passing attempt eval-20 had. Could be variance; could be the
  step-aware nudge is somehow worse than the generic one.

## What this tells us

- **The Step 5 boundary is not solvable by nudge text.** The model
  has its own sense of "done" that user-role prompts can't override.
  The architectural ceiling for redirecting the model is at the
  prompt-strength layer, not the runner-loop layer.
- **The runner's core thesis still holds.** Even in v2, 2-of-3
  attempts reach write phase, committing real code. The
  session-loop ownership is still the major lever vs Goose's 0-of-6.
  The v2 changes are an attempted second-order improvement that
  didn't land.
- **Nudges are good for recovery, not redirection.** When the model
  emits prose and stops, a nudge revives it. When the model is
  *actively making the wrong tool calls*, no amount of nudging
  changes its choice.
- **The fix for Step 5 boundary likely lives in the recipe text,
  not the runner.** If "you must call create_pull_request as the
  next tool after the last file commit" is in the *recipe* (loaded
  with the system context, before any work happens), the model
  treats it as primary instruction. If it's in a user-role nudge
  mid-flight, the model treats it as suggestion.

## Why eval-21 is a useful failure

The v2 iteration was specifically designed to test the "nudge
specificity is the fix" hypothesis. 0-of-3 PASS is a clean
refutation — we don't have to wonder if more nudge engineering
would have helped. The hypothesis is rejected at k=3, and the next
iteration moves elsewhere (probably to the recipe text, possibly
to a post-run salvage tool).

This is the difference between "we tried X and Y, both kind of
worked" and "we tried X and it worked; we tried Y on top, it
didn't help, here's where to look next." The latter narrows the
search space.

## Across both runner versions (eval-20 + eval-21)

| | v1 (eval-20) | v2 (eval-21) |
|---|---|---|
| Full PASS | 1-of-3 | 0-of-3 |
| Reach write phase | 3-of-3 | 2-of-3 |
| Code commits land | 3-of-3 | 2-of-3 |
| PR opened | 1-of-3 | 0-of-3 |
| Tool calls per attempt | 21–28 | 14–21 |
| Nudges fired | 0 (v1 didn't track) | 9 total across 3 attempts |

Combined runner total: **1-of-6 full PASS, 5-of-6 reach write phase.**

Goose total on the same target (eval-17 + eval-19 series):
**0-of-6 full PASS, 0-of-6 reach write phase.**

The architectural thesis is validated. The reliability ceiling
remains.

## Action items

- [x] Build runner v2 with step-aware escalation (commit 1dabd93)
- [x] Run eval-21 k-of-3
- [x] Write up this result
- [ ] Consider strengthening the recipe's Step 5 prose directly
  (rather than via runner nudges). Hypothesis: the model takes
  recipe text more seriously than user-role mid-flight messages.
- [ ] Consider a "post-run salvage" approach — a separate script
  that, given a branch with commits but no PR, opens the PR with
  a templated body. Would convert 2-of-3 partials into "1 model
  PR + 2 mechanical PRs". Sidesteps the model's variance.
- [ ] Decide whether to revert 1dabd93 (v2 step-aware logic) before
  shipping the POC. The data suggests v2 is no better than v1; v1's
  simpler logic might be preferable for the eventual PR. Or keep
  v2 + add the recipe-text fix and re-run.

## Next time

- "More specific is better" is an intuition, not a law. The v2
  iteration assumed a more directive nudge would land harder than
  a generic one. The data says it doesn't — at least not in user-
  role messages.
- The runner's strike counter being tool-call-shaped (resets on
  any tool call) is correct for the original "model goes silent"
  failure mode but doesn't catch the "model makes wrong tool
  calls" mode. A future iteration could track "nudges given for
  tool X without tool X actually being called" and exit when that
  count exceeds N. But the underlying problem — model variance —
  isn't solved by tracking; it's solved by reducing variance
  (better model, stronger prompt at load-time, or a different
  recipe shape).
- The 6 total runner attempts across eval-20 + eval-21 give us a
  good baseline. Future runner iterations should beat 1-of-6 PASS
  + 5-of-6 reach-write-phase to count as progress. v2 didn't.
