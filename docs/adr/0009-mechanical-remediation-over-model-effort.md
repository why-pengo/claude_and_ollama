# ADR-0009: Deterministic gate failures are remediated mechanically, never delegated to the model

- **Status:** Accepted
- **Date:** 2026-07-11

## Context

The epic #111 acceptance series (evals 37–40, all against the canonical
`health_track#51` task with `qwen2.5-coder:32b @ temperature=0.2`) peeled
four failure layers off the runner's verification gate. The first three
were harness or target defects, each fixed and regression-tested:

| Eval | Layer | Fix |
|---|---|---|
| eval-37 | Mutating `make check` wedged the gate's checkout | #150 — reset before sync |
| eval-38 | Same mutation laundered a false green past the gate | #154 (mutation/HEAD-move detectors) + health_track#102 (`check-only`) |
| eval-39 | `isort --check-only`'s bare error line gave the model nothing to act on | health_track#106 (`--diff` flags) |

eval-40 exposed the fourth layer, and it is not a defect anywhere — it is
a capability boundary. With isort's full unified diff **in its context**
(the exact expected file content), the model applied the fix half-right,
then regressed to its original bytes: an A→B→A oscillation of five
"fix: Correct import order" commits until loop-detect aborted the
session. A 32B model cannot reliably reproduce a formatter's exact
output, at the bake-off's most disciplined temperature, even when shown
the answer. Each failed attempt costs a model turn plus a full gate cycle
(~37s of `make test` on this target).

Formatting is deterministic, zero-judgment work with a perfect mechanical
solver (`make format`, 0.5s). The epic's own founding lesson applies in
both directions: prose rules fail where mechanical enforcement succeeds —
and model effort fails where mechanical execution succeeds. The runner
already owns exactly this class of work (salvage PRs are mechanical
commits with clear attribution); remediation extends the same principle
to the gate.

The rejected alternatives:

- **Harder prompting** ("apply the diff byte-exactly") — eval-40 is
  direct evidence against it: the model had the byte-exact answer and
  still failed. Every formatter rule (black wrapping, blank-line counts)
  would re-trigger the failure, each retry burning a gate cycle, with no
  reliability floor.
- **Dropping format checks from the gate** — reopens the eval-38→#101
  gap: target CI still enforces formatting, so gate-green PRs would fail
  CI again. Weakening the gate to fit the model inverts the epic.
- **A bigger model** — an ADR-0008 question requiring a new bake-off, and
  economically wrong regardless: even a model that usually succeeds burns
  turns and gate cycles on work a formatter does deterministically.

## Decision

Deterministic gate failures will be remediated by the runner, not the
model. The AGENTS.md schema will gain an optional per-command `fix:` key
(e.g. `fix: make format` on the `check` command). When a command with a
declared fix fails at the gate, the runner will run the fix in the
workspace and, if tracked files changed, land the result as a
clearly-attributed mechanical commit (`style: mechanical remediation by
runner (<fix command>)`) via the existing GitHub-API path, then re-run
the gate exactly once. If the command is still red, the failure feeds
back to the model as today — the fix wasn't purely mechanical after all.
Fixes are declared by the target repo's AGENTS.md author; the runner
never guesses remediation commands. #157 implements; health_track#108
adopts.

## Consequences

Once #157 implements:

- Formatting failures cost zero model turns: red gate → mechanical
  commit → green gate, all runner-side. The eval-40 oscillation class is
  structurally closed, and the canonical task becomes completable by the
  default model again.
- The runner gains its first API-path commit authored by itself rather
  than the model. Attribution in the commit message keeps the audit
  trail honest — a reviewer can always tell mechanical commits from
  model commits.
- The #154 detectors and remediation compose: the fix's tree mutations
  are expected (they become the commit); HEAD moves remain forbidden.
- health_track#108 puts `fix: make format` on the `check` entries; other
  targets opt in per-command as their AGENTS.md authors see fit.

Independent of #157's merge:

- The principle binds future design: when a gate failure has a
  deterministic solver, the harness runs the solver — model effort is
  reserved for judgment. This is the criterion for evaluating any future
  "teach the model to X" proposal where X is mechanical.
- eval-40 stands as the capability-boundary reference for
  qwen2.5-coder:32b on byte-exact formatting tasks (relevant to any
  future bake-off's scoring).

## References

- eval-37..40 (`evals/eval-3*/result.md`) — the acceptance series
- #150, #154, health_track#102, health_track#106 — the first three layers' fixes
- #157 — implementation; health_track#108 — adoption
- [ADR-0007](0007-loop-detection-and-prose-rescue-are-load-bearing.md) — the runner's existing mechanical-safety-net posture
