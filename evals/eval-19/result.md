# eval-19 result

k-of-3 test of the harness-complexity-reduction hypothesis. After
eval-17 (3-of-3 FAIL with the heavy harness), the audit in
`docs/harness-complexity-audit.md` proposed that prompt accretion was
the regressor — goose-system.md grown to 198 lines, recipe to 153,
plus four Step 0 AGENTS.md fetches now returning ~770 lines on
`health_track`. The audit cuts in 6f1e55a slimmed all three surfaces
(net ~70% reduction in prompt mass before Step 1). eval-19 series tests
whether the slim harness restores eval-14-class reliability for
qwen3.6 on the canonical `health_track#51` task.

Three attempts. Three distinct failure shapes. **0-of-3 PASS.**

## Verdict

Verdict: FAIL

Slimming helped at Step 0 (single AGENTS.md fetch, as intended) and
let attempts progress further on average than the eval-17 series. But
the underlying termination class is unchanged: goose still exits 0
silently when qwen3.6 emits text-without-tool-call or an empty turn.
No attempt called `create_pull_request`, none called `add_issue_comment`,
none pushed any files to GitHub.

The hypothesis "harness mass is the eval-17 regressor" is partially
refuted at k=3. Mass-reduction is *necessary but not sufficient* —
something deeper (most likely a Goose session-loop interaction with
qwen3.6's stop-token / no-tool-call emissions) is the actual
reliability ceiling.

## What ran

All three attempts (eval-19, eval-19b, eval-19c) used identical
configuration:

- Branch: `feature/tool-call-discipline` — see commit timeline below
- Model: `qwen3.6:latest` (goose.yaml default)
- Context: 131072 (goose.yaml default)
- Recipe: post-audit slimmed `recipes/execute-issue.yaml`
- System prompt: post-audit slimmed `prompts/goose-system.md`
- Target: `health_track#51` (`GET /api/hydration/daily`)
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Logs: `evals/eval-19/goose-session.log`,
  `evals/eval-19b/goose-session.log`,
  `evals/eval-19c/goose-session.log`

Commit timeline on the branch during the series:
- 1491751 — "Every turn is a tool call" prompt patch
- 6f1e55a — audit cuts (system 198→124, recipe 153→111, Step 0
  4-fetches→1, dropped recipe Step 3 push_files callout)
- **eval-19 ran here (attempt 1)**
- 9f6631d — restored recipe Step 3 push_files callout after eval-19
  exposed it as load-bearing in position
- **eval-19b and eval-19c ran here (attempts 2 and 3)**

## What worked (across the series)

- **Step 0 single-fetch behaviour.** All three attempts cleanly did
  one `get_file_contents AGENTS.md` instead of four. The recipe
  change from four unconditional probes to one root-with-pointer
  fetch holds.
- **Attempts reached further on average.** eval-19 reached Step 3
  write phase (further than any eval-17 series attempt). eval-19c
  reached `create_branch` at the end of Step 2. eval-17 series never
  reached Step 3 write phase at all.
- **No `<info-msg>` fabrications or "delegate to sub-agent"
  loss-of-frame.** The named anti-patterns from §Every turn is a
  tool call held. The four termination modes that section explicitly
  forbids did not appear in any of the three attempts.
- **No path slips** (when files were attempted). eval-19 used the
  correct conceptual path (`backend/app/schemas/hydration.py`) but
  the wrong *tool* (developer.write instead of push_files).

## What didn't (per attempt)

### eval-19 — Step 3 push_files vs developer.write regression

274 lines, 16 tool calls. Sequence:

```
Step 0:  get_file_contents AGENTS.md         (line 26) ✓
Step 1:  issue_read #51                       (line 33) ✓
Step 0→1 context: 5 more get_file_contents   (lines 41-69) ✓
Step 2:  create_branch goose/issue-51-...    (line 76) ✓
Step 3 context: 5 more get_file_contents     (lines 84-112) ✓
Step 3 write: developer.write hydration.py   (line 119) ✗ wrong tool
Step 3 edit: developer.edit analytics.py     (line 143) ✗ fails — /work
                                                         is harness mount,
                                                         not target repo
Recovery: developer.tree /work               (line 155)
[session ends]
```

This is the *exact* eval-13 failure mode that PR #51 was added to
fix. The audit (6f1e55a) had moved PR #51's Step 3 callout into the
system prompt's MCP section and dropped it from the recipe — which
turned out to be the wrong call.

The rule is load-bearing **in recipe Step 3 position**, not just in
system-prompt presence. The model is at the decision-point between
"push_files" and "developer.write" at Step 3 specifically; that's
the moment the rule needs to be visible. A general "use MCP for repo
changes" in setup-time context isn't sufficient at that decision
point.

Fixed in 9f6631d (restored a tightened 8-line callout at Step 3,
dropped duplicate explanation from system prompt). All subsequent
attempts ran with the fix.

### eval-19b — terminated after Step 1

39 lines, 2 tool calls. Sequence:

```
Step 0:  get_file_contents AGENTS.md         (line 26) ✓
Step 1:  issue_read #51                       (line 33) ✓
[issue body returned; session ends]
```

The model read the issue, the issue body came back as a tool result,
and the model emitted nothing further. Goose exit-0. Identical
termination class to eval-17b: model produces no tool call → goose
treats turn as terminal.

This is the "structural reliability cliff" failure mode. The 9f6631d
fix to Step 3 didn't matter because the model never reached Step 3.

### eval-19c — terminated after Step 2 create_branch

139 lines, 16 tool calls. Sequence:

```
Step 0:  get_file_contents AGENTS.md         (line 26) ✓
Step 1:  issue_read #51                       (line 33) ✓
Step 0→2 context: 12 get_file_contents       (lines 41-126) ✓
Step 2:  create_branch goose/issue-51-...    (line 133) ✓
[branch created; session ends]
```

Same termination class as eval-19b but at a different point. The
model gathered context, created the branch, and emitted nothing
further. Branch left orphaned (no commits).

## The reliability-class pattern

Across eval-17 series (3 attempts with heavy harness) and eval-19
series (3 attempts with slimmed harness), six consecutive attempts
on the same task failed in six different shapes. The shapes vary;
the root cause is consistent: **at some point in the recipe, qwen3.6
emits a response that goose interprets as terminal — either text
without a tool call, an empty turn, or a non-`tool_calls`-shaped
JSON in the content field — and goose exits 0 with no error
markers.**

The structural pattern:

| Attempt | Halt point | Halt shape |
|---|---|---|
| eval-17 | After shell-cat | Tool result interpreted as completion |
| eval-17b | Mid-exploration | Empty turn after context-gathering |
| eval-17c | After read 2 ref files | "Let me delegate to a sub-agent" prose |
| eval-19 | Wrong tool used, failure recovery | tree → empty turn |
| eval-19b | After issue_read | Empty turn |
| eval-19c | After create_branch | Empty turn |

The "Every turn is a tool call" prompt patch (1491751) named four
anti-pattern shapes; only eval-17c hit one of those (the
sub-agent-delegation). The other five attempts exited through shapes
not named in the prompt — including just emitting nothing. Prompt
engineering can name patterns; it can't catch unnamed ones.

## What this means

- **The hypothesis "complexity reduction fixes reliability" is
  partially refuted.** Reduction helped at the edges (Step 0
  efficiency, attempts reach further) but did not eliminate the
  underlying termination class.
- **The session-loop hypothesis is back on the table.** If goose
  terminates exit-0 on certain qwen3.6 emissions that aren't
  actual completions, our reliability ceiling is bounded by that
  choice — independent of model or prompt mass. Even a perfectly-
  tuned prompt can't prevent the model from occasionally emitting
  a shape goose treats as terminal.
- **The audit cuts should still merge.** The slimmed harness is
  strictly better than the heavy one — same failure rate but
  attempts get further on average, evidence is cleaner, and
  scope-creep is reduced. The cuts are a real win even if they
  don't single-handedly fix the reliability cliff.
- **The direct-Ollama POC is now strongly motivated.** A custom
  session loop that detects "model emitted no tool call → prompt
  for next step" or "model emitted no tool call → retry the turn"
  is the architectural fix for the termination class we keep
  hitting. The earlier argument I made and walked back ("Goose's
  OpenAI-compat path is the bottleneck") was wrong; the *real*
  argument is "Goose's session-loop choice on empty/non-tool-call
  turns is what's killing every run."

## Action items

- [x] Write up eval-19 series (this file)
- [x] Commit the 9f6631d revert that restored Step 3 callout
- [ ] Build a direct-Ollama POC runner that owns the session loop:
  - Calls Ollama `/v1/chat/completions` directly (both endpoints
    work equivalently per today's curl probes)
  - Uses `gh` CLI for github operations (not MCP)
  - Loads the same `prompts/goose-system.md` and parses the same
    recipe YAML as Goose does
  - On "model emits empty content + no tool_calls": prompt for next
    step instead of terminating
  - On "model emits content but no tool_calls" (e.g. prose hand-off
    or fabricated XML): retry the turn with an explicit "you must
    call a tool" reminder
  - Spend cap: ~1-2 days. Reproduce eval-14 with this runner against
    `health_track#51`. If it succeeds reliably (3-of-3), the
    session-loop hypothesis is validated and we have a path forward.
- [ ] Update #53 with the eval-19 series evidence and the revised
  diagnosis (session loop, not just prompt mass)
- [ ] Clean up the orphan `goose/issue-51-hydration-daily-endpoint`
  branch on health_track left by eval-19c

## Next time

- For models with high session-level variance like qwen3.6 in this
  harness, single-shot evaluations are insufficient even at k=3.
  Either the runtime must mitigate the variance (auto-retry on
  empty turn) or methodology must (k=5+ with majority-PASS gate).
- The Step 3 callout revert (9f6631d) is a methodology lesson: when
  removing a duplicate rule, check whether each location has its
  own load-bearing reason. Some duplications encode positional
  context, not just redundancy. The audit doc should be updated
  with this finding.
- Don't run 19b/19c immediately after a known-bad attempt (19's
  Step 3 callout regression). Better discipline would have been:
  patch first, then start the k-of-3 series fresh. eval-19's data
  is still useful (it caught the over-cut) but it's a different
  experiment than 19b/19c and shouldn't have been counted in the
  same k-of-3.
