# eval-41 result — acceptance run №5 (post mechanical remediation)

## What ran

- Same task/params/model as eval-37..40: health_track#51,
  `qwen2.5-coder:32b @ temperature=0.2`.
- Runner main `c2d6d9d` (#161 — mechanical remediation, ADR-0009).
- Target develop `e4e4012` (health_track#109 — `fix: make format`
  declared on the `check` entry).

## What worked — the full acceptance flow, end to end

Recipe complete at turn 8, ~19s of model wall time, no salvage, no
loop-detect. PR [health_track#110](https://github.com/why-pengo/health_track/pull/110)
opened **by the model**, issue comment posted, workspace restored clean.

Mechanical remediation fired twice and drew its boundary precisely both
times:

1. Commit 1 (`b46f5649`) put `from typing import Optional, List` below
   the pydantic import — the exact isort failure that burned five commits
   and a loop-detect abort in eval-40. This time: red gate →
   `style: mechanical remediation by runner (make format)` (`8314470c`) →
   gate re-run. **Zero model turns on formatting.**
2. The re-run stayed red on flake8 `F401 'typing.List' imported but
   unused` — correctly **not** remediated (a formatter can't remove an
   unused import; that's judgment, not mechanics) and fed back to the
   model, which fixed it in one turn (`d7239c21`)… reintroducing the
   import-order error. Second remediation (`c75d03e6`) → gate
   **PASS (2/2)**.

The eval-40 oscillation class is structurally closed: the same model
made the same formatting mistake twice in one session and it cost
nothing.

Epic #111 acceptance criteria, as observable in this run:

- PR `## Verification` cites the gate verbatim
  (`make check-only: PASS (per runner gate)`), not freeform prose. ✔
- Red gate → failure output reached the model as a user-role message
  (twice). ✔
- Gate green == CI green: "Backend — lint & test" passed on PR #110 —
  the eval-38 false-green gap stayed closed under a true positive. ✔
- `make ci` clean across child PRs; rubric carries the superseded note;
  all children closed. ✔ (verified outside this run)

## What didn't

Nothing at the harness layer. Model-layer observations below — none of
them qualifies the verdict, all of them point at existing backlog items.

- **The next boundary is task completion, not harness reliability.**
  The model implemented 1 of 5 subtasks (the schema) and opened the PR —
  but reported it *honestly*: 4 unchecked boxes in the PR body, an
  accurate Summary. The harness did its whole job (honest gate, honest
  verification, reviewable PR); a human reviewer sees the unchecked
  boxes immediately. Partial-but-honest is the designed failure mode.
- **The model hallucinated a green-gate report.** After the final PASS
  (which the runner never tells it about — #151), it emitted
  "Verification passed after your last commit … [OK] make check-only
  (3.4s)" with a fabricated timing (real: 0.7s). Direct evidence for
  #151: green-gate visibility would replace confabulation with fact.
- **100% prose-rescue, fifth consecutive run** (#152). Every one of the
  8 tool calls was rescued from prose.

## Verdict
Verdict: PASS

## Next time

- Land #151 (green-gate visibility): the model plainly wants this signal
  — it invented one. A real message might also prompt "continue with the
  remaining subtasks" instead of victory-declaration.
- #152 is ripe: five consecutive 100%-prose-rescue runs; run the GO/NOGO
  investigation on making prose the primary protocol.
- Subtask completion: consider a recipe/nudge check keyed on unchecked
  `- [ ]` boxes before Step 5 — or explicitly bless partial-but-honest
  PRs as reviewable increments and size issues to match (#143's sizing
  rules pull the same direction).
