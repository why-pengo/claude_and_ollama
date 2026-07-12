# eval-39 result — epic #111 acceptance run №3 (post #154/#102)

## What ran

- Recipe: `recipes/execute-issue.yaml`; params `issue_number=51`,
  `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen2.5-coder:32b @ temperature=0.2`
- Runner at main `eec0e1a` (#154 mutation/HEAD-move detectors); target at
  develop `fef2fd9` (#103's non-mutating `make check-only` in AGENTS.md)

## What worked

- The false-green class is confirmed dead: `make check-only` honestly
  failed all four gate runs on the committed isort violation — the exact
  defect eval-38's mutating command laundered. No mutation or head-moved
  detector fired (check-only really is non-mutating).
- Feedback, loop-detect (turn 11), and salvage (PR #104, honest FAIL
  verification block, 4 commits) all behaved to spec.
- Workspace restored clean to develop at session end.

## What didn't — feedback quality, not harness behaviour

The model re-committed the **same mis-sorted file four times**. The
feedback it received was isort's entire check-only output:
`ERROR: ...hydration.py Imports are incorrectly sorted and/or formatted.`
— the file is named but no diff is shown, so a blind model has nothing to
act on. eval-38 masked this: mutating `make check` silently fixed the
imports for the model. With strict checking, qwen2.5-coder cannot infer
isort's expected ordering from a bare error line.

Fix: `--diff` on the check-mode tools (`isort --check-only --diff`,
`black --check --diff`) so the failure output *shows the expected form* —
filed as health_track#105, implemented by health_track PR #106.
eval-40 re-runs after it lands.

## Observations

- 100% prose-rescue again (three runs in a row now — #152's case grows).
- The model's fetch-then-recommit cycle shows it engaging with the
  feedback loop correctly; it failed on information, not process.

## Verdict
Verdict: FAIL

Run-level FAIL (loop-detect + salvage). Harness-level: every mechanism
including the new #154 detectors behaved to spec; the failure isolates to
feedback quality — the gate must relay *actionable* failure output, which
is a target-repo command-flag concern (issue health_track#105, fixed by
PR health_track#106).

## Next time
- health_track#105 (fixed by PR #106): --diff flags on check-only, then eval-40.
- #152 (prose-rescue investigation) now has three consecutive 100% runs.
- Consider a runner-side guard for identical-recommit cycles that burns
  fewer turns (loop-detect took 4 cycles × ~37s of gate time) — only if
  eval-40 still shows thrash.
