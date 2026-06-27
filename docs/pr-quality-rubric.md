# PR quality rubric — bake-off code review

> **Superseded by `docs/agents-md-schema.md` + runner gate (epic
> [#111](https://github.com/why-pengo/claude_and_ollama/issues/111)).**
> The `Q2` "project convention adherence" axis is now enforced in-flow
> by the runner against the target repo's `AGENTS.md`, not retro-scored
> per PR. This file is preserved as audit trail for the closed bake-off
> documented in `docs/bakeoff-summary.md`.

Methodology for evaluating runner-produced PRs against a canonical bake-off issue. Adapts Szych & Schwerk's multi-source approach (arXiv 2605.09059 — benchmark + automated checks + structured human review) to a per-PR scorecard usable in this project's single-developer reality.

> **Single-reviewer caveat (read this first).** This rubric is applied by one developer (the same person who set up the bake-off runs). That's a real limit on what the scoring can claim. The paper's developer-panel methodology averages out individual reviewer bias; ours can't. We compensate with mitigations described under each dimension, but the methodology here is **best-effort given solo constraints, not gold-standard**. Treat the quality dimensions — especially Q3 — as one signal among several, not the deciding signal.

## Sources (gated)

These are PASS/FAIL gates. If either fails, the PR doesn't reach the quality dimensions below.

### Source G1: Automated checks pass

Run on the target repo (e.g. `health_track`), against the PR's branch:

- `make check` passes (format, lint) — PASS / FAIL
- `make test` passes (full test suite) — PASS / FAIL
- Coverage ≥ project gate (85% for `health_track` per its `backend/AGENTS.md`) — PASS / FAIL

A G1 FAIL means the PR can't be merged as-is. Record what failed; don't bother with the quality axes until G1 is GREEN.

### Source G2: Issue acceptance criteria correctness

Each criterion is verifiable from the diff + the test suite. Score per criterion as **PASS / PARTIAL / FAIL**.

For `health_track#51` (the canonical bake-off issue), the criteria are:

1. `water_oz = water_ml / 29.5735` conversion is correct and rounded to 1dp
2. Electrolyte fields (mg) are passed through and rounded to integer
3. Missing metric on a date → field is `null`, not `0`
4. Dates without any of the 5 metrics → no row (not an empty row)
5. Endpoint requires JWT (401 without)
6. Response shape matches the issue's specified JSON contract

**G2 verdict**: PASS if ≥ 5/6 criteria PASS; PARTIAL if 3-4/6; FAIL if ≤ 2/6.

**For other issues, G2 must be re-specialized.** The rubric IS the methodology; the content of G2 is task-specific by design.

## Quality dimensions (only assessed if G1 and G2 are PASS or PARTIAL)

### Q1: Tests cover the acceptance criteria

For each criterion in G2, is there a named test case in the test file that exercises it specifically?

- PASS — every criterion has a dedicated, clearly-named test case
- PARTIAL — most criteria covered, 1-2 missing
- FAIL — tests exist but don't trace to the issue's acceptance criteria

### Q2: Project convention adherence

Verifiable from the diff against the target repo's `AGENTS.md`. For `health_track`, score each item as PASS / FAIL:

- SQLAlchemy 2.0 async style (`Mapped[X]`, `mapped_column`, `AsyncSession`, `select()` — no 1.x `Column` / `declarative_base` / `db.query`)
- Timezone-aware UTC ISO strings for timestamps (`datetime.now(UTC).isoformat()` — no naive datetimes)
- Router registered in `backend/app/main.py` following the existing sleep-router pattern
- Tests live in `backend/tests/<name>.py`, named matching existing patterns
- Schema in `backend/app/schemas/<name>.py` using Pydantic conventions matching peers

**Q2 verdict**: PASS if ≥ 80% of items PASS; PARTIAL if 50–79%; FAIL if < 50%.

### Q3: Production-readiness (human review)

This is the dimension Szych & Schwerk specifically argue catches things automated checks miss. Five short prompts, each scored on a 3-point scale: **agree** / **partially agree** / **disagree**.

1. Names of functions, schemas, and variables clearly reflect their purpose
2. The implementation is appropriately scoped — not over-engineered, not under-engineered
3. I could maintain or extend this code 3 months from now without reverse-engineering it
4. Tests would catch the kind of regression a careless future change would introduce
5. I would approve this PR with minor or no comments

**Q3 verdict**: PASS if ≥ 4 "agree"; PARTIAL if 2-3 "agree"; FAIL if ≤ 1 "agree".

**Solo-reviewer mitigations for Q3** (these are how we partially compensate for the absence of a developer panel):

1. **Score Q3 LAST**, after G1/G2/Q1/Q2 are recorded. Sequence reduces anchoring on the binary gate verdicts.
2. **Blind the model identity** while scoring. Don't look at which eval / which model produced the PR. The PR diff on `health_track` doesn't surface this; resist the urge to check.
3. **Time-space Q3 from the bake-off run.** Score Q3 on a different day from when the PR was generated. The "did it work end-to-end?" adrenaline distorts production-readiness judgment.
4. **Score in writing before adjusting.** Write the 5 prompt scores down before reading them back. If you find yourself wanting to "adjust" a score after reading the totals, that's anchoring — leave the first read.
5. **Accept the bias is real.** Solo Q3 is correlated with the reviewer's mood, sunk-cost in the bake-off, and prior favoring of one candidate. Don't pretend it isn't.

## Aggregation

| Verdict | Criteria |
|---|---|
| **PASS** | G1 PASS + G2 PASS + ≥ 2 of 3 quality dimensions PASS |
| **PARTIAL PASS** | G1 PASS + G2 PARTIAL/PASS + 1 of 3 quality dimensions PASS |
| **FAIL** | G1 FAIL, OR G2 FAIL, OR 0 of 3 quality dimensions PASS |

G1 and G2 are gates. A PR that breaks the test suite or misses most acceptance criteria fails outright — quality dimensions don't rescue it.

## Tiebreakers (head-to-head between two PRs)

Apply in order:

1. Higher G2 PASS count (more acceptance criteria met)
2. Higher Q1 PASS count (better test coverage of criteria)
3. Higher Q2 PASS count (more conventions followed)
4. Higher Q3 PASS count (better solo-reviewer assessment)
5. Smaller diff (less unnecessary churn)

## Per-PR scoring template

When applying to a bake-off run's PR, capture this block as part of the eval's `result.md` or as an appendix to the bake-off summary:

```
PR #N (eval-XX, <model>)

G1 automated checks: [PASS / FAIL]
  - make check: [PASS / FAIL]
  - make test:  [PASS / FAIL]
  - coverage:   NN%

G2 acceptance criteria: [N/6 PASS]
  - 1. mL→fl-oz conversion + 1dp:       [PASS / PARTIAL / FAIL]
  - 2. mg pass-through + integer round: [PASS / PARTIAL / FAIL]
  - 3. missing metric → null not 0:     [PASS / PARTIAL / FAIL]
  - 4. no row when all 5 missing:       [PASS / PARTIAL / FAIL]
  - 5. JWT required (401 without):      [PASS / PARTIAL / FAIL]
  - 6. response shape matches contract: [PASS / PARTIAL / FAIL]

Q1 test coverage of criteria: [PASS / PARTIAL / FAIL]
  - missing test cases: <list, or "none">

Q2 conventions: [N/5 PASS]
  - SQLAlchemy 2.0 async:         [PASS / FAIL]
  - timezone-aware UTC:           [PASS / FAIL]
  - router registered correctly:  [PASS / FAIL]
  - test file location/naming:    [PASS / FAIL]
  - schema location/naming:       [PASS / FAIL]
  - violations: <list, or "none">

Q3 production-readiness: [N/5 agree]
  - 1. names reflect purpose:                    [agree / partially agree / disagree]
  - 2. appropriately scoped:                     [agree / partially agree / disagree]
  - 3. maintainable 3 months out:                [agree / partially agree / disagree]
  - 4. tests catch regressions:                  [agree / partially agree / disagree]
  - 5. would approve with minor/no comments:     [agree / partially agree / disagree]
  - notes: <freeform>

Overall: [PASS / PARTIAL PASS / FAIL]
```

## How this differs from Szych & Schwerk

The paper's developer review uses a 5-point Likert scale across 14 criteria, evaluated by a panel of developers. We collapse this to:

- A 3-point scale (faster decisions, slightly less information density)
- 5 prompts in Q3 instead of 14 criteria (we shifted the structural/comment criteria into the rubric's other dimensions — Q1, Q2, and parts of G1 — because they're more directly verifiable than via Likert subjective judgment)
- A single reviewer (the project's solo developer, with the mitigations above)

Trade-off: faster to apply, less robust to individual reviewer bias. If a future bake-off has more than one reviewer available, revert Q3 to the paper's 5-point Likert × 14 criteria form.

## When to apply this rubric

- Closing the "code quality" axis of a bake-off (the axis that turn-count / verdict-tally doesn't speak to).
- Comparing two runs of the same model to detect intra-model variance in code quality.
- Comparing two models head-to-head on the same task.

Not for:

- Reviewing PRs the human wrote — overkill; use normal review.
- Reviewing PRs against non-canonical issues without first specializing G2 to that issue's acceptance criteria.

## See also

- Szych, J. & Schwerk, A. (2026). *Evaluating LLM-Generated Code: A Benchmark and Developer Study.* arXiv:2605.09059. EASE '26/EQUISA workshop.
- `docs/bakeoff-summary.md` — the bake-off this rubric is designed to retro-evaluate.
- The target repo's `AGENTS.md` files — define the conventions Q2 checks against.
