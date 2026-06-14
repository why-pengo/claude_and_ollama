# eval-20 result

First eval of the direct-Ollama runner POC (commit f24befc). Tests
the hypothesis from the eval-19 series writeup: that Goose's
session-loop choice to exit-0 on "no tool call this turn" is the
structural reliability ceiling we hit in 6-of-6 prior attempts
(eval-17 series + eval-19 series). The POC owns the loop and prompts
the model to continue when it emits no tool call.

k-of-3 on `health_track#51` — the same target task that succeeded
once in eval-14, then failed 6-of-6 across the eval-17 and eval-19
series.

Result: **1-of-3 full PASS, 3-of-3 reach the write phase.**
Compared to Goose's 0-of-6 on the same target, this is a strong
validation of the architectural thesis. Reliability ceiling is not
yet "merge-able" but the direction is clearly right.

## Verdict

Verdict: PARTIAL

3-of-3 attempts reached Step 3 write phase and committed real code
(vs Goose's 0-of-6 reaching write phase). 1-of-3 fully completed
the recipe with a real PR + issue comment (eval-20 attempt 1 produced
PR #65 in `health_track`, since closed pending review). 2-of-3
stalled at the Step 5 boundary — model committed all the work but
didn't call `create_pull_request`.

The PASS-rate verdict is PARTIAL because we don't have 3-of-3 full
completion. The hypothesis-validation verdict, if we had one, would
be PASS.

## What ran

All three attempts (eval-20, eval-20b, eval-20c) used identical
configuration:

- Branch: `feature/tool-call-discipline` @ f24befc (direct-Ollama
  runner v1 + slimmed harness)
- Runner: `runner/run_recipe.py` calling Ollama
  `/v1/chat/completions` directly, with ~8 GitHub tools wrapped
  around `gh` CLI and a read-only `shell` tool
- Session loop: on no tool call → prompt the model to continue
  ("You emitted no tool call. The recipe is not complete. What is
  your next tool call?"). Hard cap at 3 consecutive no-tool-call
  turns. Hard cap at 60 turns total.
- Model: `qwen3.6:latest` (default)
- Recipe + system prompt: post-audit slimmed (6f1e55a + 9f6631d)
- Target: `health_track#51` — `GET /api/hydration/daily`
- Params: `issue_number=51`, `repo=why-pengo/health_track`;
  base_branch auto-resolved to `develop`
- State reset between attempts: each PR closed (without merge),
  branch deleted, before the next attempt — so each run starts from
  the same clean state.

Logs: `evals/eval-20/goose-session.log`,
`evals/eval-20b/goose-session.log`,
`evals/eval-20c/goose-session.log`.

## What happened — per attempt

### eval-20 — full PASS

| Phase | Tool | Result |
|---|---|---|
| Step 0 | `github__get_file_contents AGENTS.md` | Single root fetch ✓ |
| Step 1 | `github__issue_read` | ✓ |
| Step 1 context | 9 × `get_file_contents` | Context-gathering ✓ |
| Step 2 | `github__create_branch goose/issue-51-hydration-daily` | ✓ |
| Step 3 | 7 × `github__create_or_update_file` | One commit per subtask ✓ |
| Step 5 | `github__create_pull_request` | Returned PR #65 ✓ |
| Step 6 | `github__add_issue_comment` | Posted to #51 ✓ |
| **Outcome** | | **Recipe complete, turn 16, 21 tool calls** |

The "no tool call → prompt for next step" rescue logic *never
fired* — the model just kept making tool calls. PR #65 was opened at
`https://github.com/why-pengo/health_track/pull/65` (since closed
without merge to enable the 20b/20c retest).

The mere fact that the runtime was *willing* to continue may have
been enough to keep the model in tool-call mode. Goose would have
exited at any of the model's empty turns; the runner gives the
model permission to keep going, and (in this attempt) the model
just did.

### eval-20b — PARTIAL: 6 files committed, no PR

23 turns, 25 tool calls. Sequence:

```
Step 0:  get_file_contents AGENTS.md         ✓
Step 1:  issue_read #51 + 7 context reads    ✓
Step 0/1 extra: 3 shell calls (ls /work/...) [model still thinks
                                              /work is target repo —
                                              prompt-runner mismatch]
Step 1 extra: 4 more get_file_contents       ✓
Step 2:  create_branch                       ✓
Step 3:  3 × create_or_update_file           ✓ (commits land)
Step 3:  3 more get_file_contents (verifying?) ✓
Step 3:  create_or_update_file               ← model emitted prose
                                               here mid-flight;
                                               runner nudged; recovered
Step 3:  create_or_update_file               ← second prose+nudge
                                               recovery
Step 3:  create_or_update_file (main.py register)  ✓
[3 consecutive no-tool-call turns; runner gives up at turn 23]
```

The runner's "prompt for next step" logic recovered the model from
2 mid-flight no-tool-call turns. After the final main.py registration
commit, the model went silent for 3 turns straight and the runner
exited. **All 6 files of the implementation landed on the branch.**
Just no PR.

### eval-20c — PARTIAL: 6 files committed (with clobber retries), no PR

28 turns, 28 tool calls. Sequence similar to 20b but with a
discoverable bug:

```
Step 0/1/2: clean ✓
Step 3 commits in order:
  - create_or_update_file: HydrationDaily schema
  - create_or_update_file: get_hydration_daily in analytics.py
  - create_or_update_file: hydration.py router
  - create_or_update_file: main.py register router  ← clobbered
  - get_file_contents main.py (recovering)
  - create_or_update_file: main.py register router  ← again
  - create_or_update_file: main.py register router  ← again
  - create_or_update_file: main.py register router  ← again
  - create_or_update_file: "restore full main.py structure"  ← fixed
  - create_or_update_file: tests
[3 consecutive no-tool-call turns; runner gives up at turn 28]
```

This run exposed a sub-bug: the model didn't fetch main.py's
existing content before writing it, clobbered unrelated content,
then needed 3 retries to fix. The system prompt has a "fetch before
overwrite" rule but it wasn't followed under this specific load.

Net result: 6 files committed, including a hand-corrected main.py.
No PR.

## What worked (across the series)

- **3-of-3 reach Step 3 write phase.** Compare to Goose's 0-of-6
  across eval-17 and eval-19 series.
- **3-of-3 produce real code commits.** The runner's session-loop
  ownership keeps the model engaged through the recipe's body.
- **Step 0 single-fetch held.** All three attempts cleanly did one
  `github__get_file_contents AGENTS.md` (the slimmed recipe's
  contribution still works).
- **The "prompt for next step" rescue logic does its job.** eval-20b
  recovered from 2 such turns successfully.
- **eval-20's PR #65 is the smoking gun.** Same model, same recipe
  text, same task that succeeded once in eval-14 and then failed
  6-of-6 across two Goose-based eval series — runs to completion
  through the direct-Ollama runner.

## What didn't

- **2-of-3 stall at the Step 5 boundary.** Model finishes the last
  subtask commit, then emits 3+ empty turns → runner gives up. This
  is a **distinct second failure mode** from the eval-17/19 cliff.
  The runner caught it (Goose would also have exited) but the
  generic "prompt for next step" wasn't enough to redirect the
  model to `create_pull_request`.
- **Main.py clobber bug** (eval-20c only). The system prompt's
  "fetch before overwrite" rule isn't held under load. Three
  consecutive clobbering commits before self-correction.
- **Prompt-runner mismatch around `/work`.** Both system prompt and
  recipe still reference `/work` as the container mount. The runner
  has no `/work` — it runs on the host. eval-20b's model made 3
  `shell ls /work/...` calls that resolved to nothing. Non-blocking
  for completion but adds noise.

## What this validates

The hypothesis from `evals/eval-19/result.md`:

> The Goose session-loop choice — exit 0 on "no tool call this
> turn" — is the structural ceiling. The direct-Ollama POC is now
> strongly motivated as the architectural fix.

Validated. Direct evidence:

| Series | Runtime | Reach write phase | Full PASS |
|---|---|---|---|
| eval-17 (×3) | Goose + heavy harness | 0-of-3 | 0-of-3 |
| eval-19 (×3) | Goose + slim harness | 0-of-3 | 0-of-3 |
| **eval-20 (×3)** | **Direct-Ollama runner v1** | **3-of-3** | **1-of-3** |

Same model, same task. The runtime is the lever.

## What this exposes

A **second failure mode** the runner v1 doesn't yet fix: the Step 5
boundary. Once the model has finished all subtask commits, it
doesn't reliably transition to `create_pull_request`. The generic
"prompt for next step" rescue doesn't redirect — it just resumes
tool calls (which can be more file commits or context reads, not
the PR call).

This motivates the eval-21 series (runner v2, step-aware
escalation). Separate writeup in `evals/eval-21/result.md`.

## Why "1-of-3" is honest

The PR-creation gap means we can't claim "the runner reliably
completes the recipe." But 1-of-3 here is qualitatively different
from Goose's 0-of-6:

- Goose 0-of-6 means *no attempt ever finished the body*. Failures
  were at Step 0-2 or in the middle of Step 3.
- Runner 1-of-3 means *all three reached the end of Step 3, with
  full implementation code on a branch*. The only thing missing
  in the 2 partial attempts is the API call to open the PR.

The 2 partial attempts produce real artifacts (branches with
working code) that a human could PR with one command. Goose's
partial attempts in eval-17/19 produced nothing usable.

## Action items

- [x] Build the direct-Ollama runner POC (commit f24befc)
- [x] Run eval-20 k-of-3
- [x] Write up this result
- [ ] Clean up the prompt-runner mismatch around `/work` — the
  system prompt and recipe should not reference container-only
  paths
- [ ] Strengthen the "fetch before overwrite" rule (eval-20c
  clobber bug)
- [ ] Investigate the Step 5 boundary — eval-21 series tests
  one approach (step-aware nudges); other approaches worth
  considering include strengthening the recipe's Step 5 prose,
  or adopting a "auto-PR from accumulated commits" fallback

## Next time

- Single-shot evaluations of a probabilistic system are not
  conclusive evidence by themselves. The eval-14 success in
  isolation suggested the harness was fine; the 6-of-6 fails in
  eval-17/19 suggested it was broken; eval-20's 1-of-3 + 2 partials
  tells the most accurate story. Always k-of-3 or larger when
  evaluating reliability claims.
- The runner POC took ~1 day to build and validated the thesis
  cleanly. Future architectural hypotheses where there's strong
  motivation but uncertainty about whether the fix is at the
  layer-we're-blaming or elsewhere — build the simplest version
  that tests the hypothesis and run it. The build cost is small
  relative to the cost of arguing about it.
- The 2 partial attempts have all the work on branches. Worth
  considering a "post-run salvage" tool that takes an
  uncompleted-recipe state and opens the PR from the branch — if
  the commits are good, the PR-creation API call is mechanical.
  This is a different lever than fixing model variance.
