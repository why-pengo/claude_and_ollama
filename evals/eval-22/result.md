# eval-22 result

Third eval of the direct-Ollama runner, this time with `salvage.py`
added — a mechanical PR-from-branch fallback for when the model
commits all the work but exits without calling `create_pull_request`
(commit f3f725e). The hypothesis: eval-20 + eval-21 showed 5-of-6
attempts reached write phase but the model stalled at the Step 5
boundary 4 times; salvage converts those dead branches into review-
able PRs.

k-of-3 on the same `health_track#51` target, same model, same slimmed
harness, same step-aware nudges. Only addition: salvage at session exit.

Result: **3-of-3 full PASS.** Salvage never fired — the model called
`create_pull_request` on its own in every attempt. The data validates
that the runner+nudge combo *can* work end-to-end, but says nothing
about salvage's in-flight behavior because the safety net was never
needed.

## Verdict

Verdict: PASS

3-of-3 attempts opened a real PR and posted the status comment
without intervention from salvage. Compared to eval-21's 0-of-3 and
the combined eval-20+21 of 1-of-6, this is the strongest single-batch
result the runner has produced. The cautionary read: this is one
batch, and the three runner batches so far (eval-20 = 1/3, eval-21 =
0/3, eval-22 = 3/3) show enormous run-to-run variance. A single
3-of-3 doesn't establish reliability; it does establish that the
ceiling isn't pinned at 1-of-6.

## What ran

All three attempts (eval-22, eval-22b, eval-22c) used identical
configuration:

- Branch: `feature/tool-call-discipline` @ f3f725e (runner v2 +
  salvage)
- Runner: `runner/run_recipe.py` calling Ollama directly. Salvage
  wired in via `attempt_salvage()` at the two give-up paths (3
  consecutive empty turns; max_turns hit). Opt-out via `--no-salvage`
  (unused here).
- Model: `qwen3.6:latest`
- Recipe + system prompt: identical to eval-21 (no changes)
- Target: `health_track#51` — `GET /api/hydration/daily`
- State reset between attempts: PR closed, branch deleted, before
  each attempt.

Salvage was smoke-tested in isolation before this run by manually
creating a `goose/issue-51-salvage-smoke` branch on health_track with
one throwaway commit, invoking `salvage_pr` directly, verifying the
opened PR's body/title/footer, posting + reading the salvage comment,
and tearing it all down. The smoke test confirmed all five status
branches (`opened`, `pr_exists`, `no_branch`, `no_commits`, `error`)
behave correctly.

Logs: `evals/eval-22/goose-session.log`,
`evals/eval-22b/goose-session.log`,
`evals/eval-22c/goose-session.log`.

## What happened — per attempt

### eval-22 — full PASS (turn 13, 20 tool calls, 2 nudges)

```
Step 0:  get_file_contents AGENTS.md                    ✓
Step 1:  issue_read + 10 × get_file_contents + 1 shell  ✓
Step 2:  2 × get_file_contents (more context) + create_branch  ✓
Step 3:  2 × create_or_update_file + push_files  (3 file-write turns)
         [model emitted prose — 117 chars: "I noticed bugs in my
          pushed analytics.py (syntax errors from corruption)..."]
         [runner nudge → Step 5]
         [model emitted prose — 210 chars: "I notice my last
          analytics.py push contains syntax errors..."]
         [runner nudge → Step 5]
         → github__create_pull_request  ✓ PR #67
Step 6:  github__add_issue_comment  ✓
```

Two prose-emit turns, two nudges, model recovered into the PR call.
The model self-reported syntax-error corruption in the analytics.py
push and wrote a `⚠️ One warning` paragraph into its issue comment.
This is the same class of clobber bug as eval-20c — the model
overwrote a file without fetching its current content first. Caught
honestly by the model in its own comment, but still a defect.

### eval-22b — full PASS (turn 18, 22 tool calls, 1 nudge)

```
Step 0:  get_file_contents AGENTS.md  ✓
Step 1:  issue_read + 5 × get_file_contents + 3 × shell  ✓
Step 2:  create_branch + 3 more get_file_contents  ✓
Step 3:  push_files + 4 × create_or_update_file + get_file_contents
         [model emitted prose — 18 chars]
         [runner nudge → Step 5]
         → github__create_pull_request  ✓ PR #68
Step 6:  github__add_issue_comment  ✓
```

One short prose-emit turn (18 chars), one nudge, model recovered into
the PR call. Cleanest of the three attempts behaviorally — no
self-reported clobber, no path slips. The model interleaved 3 shell
calls early in Step 1 (`shell` reads of `/work/...` paths that don't
exist in the runner) but they returned empty and didn't affect the
flow.

### eval-22c — full PASS (turn 11, 19 tool calls, 1 nudge, 0 prose)

```
Step 0:  get_file_contents AGENTS.md  ✓
Step 1:  issue_read + 9 × get_file_contents  ✓
Step 2:  create_branch  ✓
Step 3:  4 × create_or_update_file
         [empty turn — model emitted nothing, no prose, no tool call]
         [runner nudge → Step 5]
         → github__create_pull_request  ✓ PR #69
Step 6:  github__add_issue_comment  ✓
```

Shortest attempt and the only one where the model went truly silent
(no prose either) before the nudge. The nudge recovered it cleanly.
Notable: the nudge mechanism caught both the "prose-emit then stop"
mode (22 and 22b) and the "empty turn" mode (22c) — the runner
treats them identically (any non-tool-call turn → strike + nudge),
which paid off here.

## What worked

- **The nudge mechanism actually redirected the model in every
  attempt.** In eval-21 the same nudge text fired and the model
  responded with the wrong tool (more `create_or_update_file`). In
  eval-22 the same nudge text fired and the model responded with
  `create_pull_request`. The difference is run-to-run variance, not
  a code change — the nudge text and runner code are identical to
  eval-21.
- **3-of-3 reach Step 3 write phase + 3-of-3 open PRs.** Best
  single-batch outcome of any runner eval so far.
- **Salvage is in place but unused.** The honest read: we built and
  tested salvage offline, but this run gave us no in-flight
  validation of it. If the next batch produces a partial, salvage
  will get its first real workout.

## What didn't

- **eval-22 analytics.py clobber.** Same class of bug as eval-20c —
  model overwrote a file without fetching it first. The system
  prompt's "fetch before overwrite" rule didn't hold under load.
  The model self-flagged it in the issue comment, which is honest
  but doesn't fix the bug. Open question: strengthen that rule's
  position in the system prompt vs. recipe, or accept it as a
  reviewer-catches-it failure mode.
- **No salvage validation.** The mechanical PR fallback never fired
  because the model didn't stall. We have isolation smoke-test
  evidence that it works (the manual PR #66 dry run), but no live
  eval evidence yet.

## What this means in context

The three runner batches so far paint a wide variance picture, not a
monotonic improvement curve:

| Eval | Runner version | Salvage | Full PASS | Reach write phase |
|---|---|---|---|---|
| eval-20 | v1 (generic nudges) | no | 1/3 | 3/3 |
| eval-21 | v2 (step-aware nudges) | no | 0/3 | 2/3 |
| eval-22 | v2 + salvage | yes (unused) | 3/3 | 3/3 |
| **Combined** | | | **4/9** | **8/9** |

The structural changes between eval-21 and eval-22 are minimal —
salvage was added but didn't fire, so its presence couldn't have
changed model behavior. The 0/3 → 3/3 jump is variance, not progress.
The honest claim from this run is: the runner harness *can* go 3-of-3
on this task; it can also go 0-of-3 on the same setup; we have no
mechanism yet to predict which.

Compared to Goose on the same target (eval-17 + eval-19 series:
0-of-6 PASS, 0-of-6 reach write phase), the runner is strictly better
on both metrics across all batches — but the within-runner variance
is the dominant story for any reliability claim.

## Why "3-of-3" is honest but not conclusive

This batch hit the high end of the runner's variance band. Three
adjacent observations:

- eval-21 had the same code (modulo salvage, which doesn't run during
  the body of the session) and went 0-of-3.
- We don't know what changed between Jun 12 (eval-20/21) and today
  (Jun 14) other than the calendar — same model, same Ollama host,
  same prompts, same recipe.
- The bazzite Ollama host's model state was confirmed unchanged
  between eval-17 and eval-19 (digest check). No reason to think
  today is different, but we didn't re-check.

A 5-of-5 or 6-of-6 batch would be stronger evidence. So would a batch
where salvage actually fires and converts a partial — that would
prove salvage works in the wild, not just in isolation.

## Action items

- [x] Build `runner/salvage.py` with `salvage_pr` + `salvage_comment`
- [x] Wire into `run_recipe.py` (commit f3f725e)
- [x] Smoke-test salvage against a manually-created branch on
  health_track (passed; PR #66 dry-run)
- [x] Run eval-22 k-of-3 (3-of-3 PASS; salvage unused)
- [x] Write up this result
- [ ] Run another k-of-3 batch (eval-23) without code changes — see if
  the 3-of-3 reproduces or if variance reasserts. If it reproduces,
  re-examine what's different between today and the Jun 12 baseline.
  If variance reasserts and salvage fires on a partial, we get the
  in-flight salvage validation.
- [ ] The analytics.py clobber pattern (eval-20c + eval-22) is a
  recurring defect across runs. Consider whether the system prompt's
  "fetch before overwrite" rule belongs in the recipe instead (Step 3
  positional context, like the push_files-vs-developer.write rule).
- [ ] Decide on the v2 vs v1 nudge revert question. eval-21 said v2
  ≤ v1; eval-22 says v2 worked fine. The data is too noisy to decide.
  Leave v2 in for now; revisit if eval-23 produces ambiguous nudge
  behavior.

## Next time

- One k-of-3 batch is not enough to make reliability claims when
  prior batches show 0/3 and 1/3 on the same setup. The k-of-3
  methodology guards against single-shot misreads but doesn't
  account for batch-to-batch variance. Future "did this change help?"
  evals should be 5+ shots or run the same batch twice.
- Salvage being present in the runner without firing is the kind of
  silent state that hides bugs. The smoke-test gave us PR-creation
  + comment-creation evidence, but the integration path
  (`attempt_salvage` extracting branch + title from messages) is
  not validated end-to-end yet. Worth running an attempt with
  `--max-turns 5` artificially low to force a salvage fire on
  partial state.
- The runner's session-loop ownership remains the architectural
  lever vs Goose's `0-of-6`. The variance within the runner is a
  smaller-bore problem than the structural ceiling we already
  defeated.
