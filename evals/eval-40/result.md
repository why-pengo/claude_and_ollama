# eval-40 result — acceptance run №4 (post --diff feedback fix)

## What ran

- Same task/params/model as eval-37..39; runner main `eec0e1a`, target
  develop `aa3ac01` (health_track#106's `--diff` flags live).

## What worked

- The `--diff` fix (health_track#106) delivered: the gate feedback now
  carries isort's full unified diff — session.log shows the model
  received the exact expected import block on every red gate.
- The model engaged correctly: commits changed from eval-39's blind
  identical resends to five "fix: Correct import order" attempts.
- Harness mechanics: six honest red gates, loop-detect at turn 9,
  salvage PR #107 with honest verification, workspace restored clean.

## What didn't — a model-capability boundary, now precisely isolated

With the diff in hand, the model applied it half-right (fix 1 moved
`typing` above `pydantic` — correct group order — but kept the unsorted
`Optional, List` names and omitted the group-separating blank line),
then regressed: later commits are byte-identical to commit 1
(pydantic-first). A → B → A oscillation until loop-detect.

qwen2.5-coder:32b@0.2 cannot reliably reproduce a formatter's exact
output even when shown the diff. Formatting is deterministic, mechanical
work — the wrong kind of work to ask a 32B model to do blind, and the
wrong failure to burn 4+ gate cycles on.

Note also: `make check-only`'s steps abort at the first failure (make
semantics), so the model only ever saw isort's failure — black/flake8
results for the same commit were never reported. Run-all at the make
level would mirror the gate's own run-all philosophy.

## Observations

- 100% prose-rescue, fourth consecutive run (#152).
- The model's schema also uses `Optional[float]` against the documented
  py3.12 `float | None` convention — conventions reach the model (Step
  0) but don't bind it; only gate commands bind.

## Verdict
Verdict: FAIL

The acceptance series has now peeled four distinct layers: wedged gate
(37, fixed #150), false green (38, fixed #154+#102), unactionable
feedback (39, fixed health_track#106), and now mechanical-formatting
capability (40). Layers 1–3 were harness/target defects — all fixed and
regression-tested. Layer 4 is a task-allocation question: deterministic
formatting belongs to a machine, not the model. Decision needed (see
follow-up): runner-side mechanical remediation (declared fix commands)
vs. relaxing format checks out of the gate.

## Next time
- Decide the formatting-remediation design; file and implement.
- #152: four consecutive 100% prose-rescue runs.
