# eval-38 result — epic #111 acceptance run №2 (post-fix)

## What ran

- Recipe: `recipes/execute-issue.yaml` (gate-aligned, #110)
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen2.5-coder:32b @ temperature=0.2` (ADR-0008 defaults)
- Runner at main `ce8dcbe` — includes #150's gate-reset fix (the eval-37 wedge)
- Same task as eval-35/eval-37 (the canonical health_track#51)

## What worked — the full #111 loop, end to end

Turn-by-turn: AGENTS.md pre-flight → issue read → branch → commit №1 →
**gate red** (`make check` FAIL exit 2, `make test` PASS 35.2s) →
failure fed back → commit №2 → **gate green (2/2)** — the #150 fix held:
the second gate run survived `make format`'s workspace mutation that
wedged eval-37 → PR opened → issue comment → clean completion at
**turn 9** (inside eval-35's 8–10 turn band; the gate added ~72s of
wall time across two runs).

- **PR health_track#101's `## Verification` block is gate-cited in the
  #110 template shape** — `- \`make check\`: FAIL (per runner gate)` /
  `- \`make test\`: PASS (per runner gate)`. No freeform fabricated
  prose. The eval-35 failure mode is dead.
- **The red→green fix loop worked in one cycle**: the model received the
  flake8 output and its next commit fixed it.
- **Workspace restored** to a clean `develop` at session end (the
  restore-side half of #150, also exercised by the eval-37 dirt).

## Gap found (refinement, not regression)

The PR body cites `make check: FAIL` — the **first** gate's result — even
though the final gate on HEAD was green (which is why the PR-open block
let the call through). Root cause: the runner only messages the model on
**red** gates; a green gate is silent, so the model's last knowledge of
gate state is the failure report it fixed. The body is *stale, traceable
to a real gate report* — not fabricated — but citing the current green
results needs the runner to surface them. Filed as a follow-up issue
(green-gate visibility).

## Observations

- **100% prose-rescue rate again** (8/8 tool calls) — consistent with
  eval-37. The prose-rescue mechanism is carrying every run now; worth
  its own investigation.
- The model called `create_pull_request` twice back-to-back; only #101
  exists, so the second call presumably errored (already exists) and the
  model recovered by moving to the comment. Tool results aren't logged
  to session.log — a log-surface gap worth noting for future forensics.

## Verdict
Verdict: PASS

Epic #111's acceptance criteria are met: gate-cited PR verification (no
fabricated prose), no-AGENTS.md rejection (verified in #107's e2e and
eval-37's pre-flight), red-gate feedback as user-role message (observed
in both acceptance runs), `make ci` clean across all child PRs, and the
rubric carries its superseded note.

## Next time
- Surface green-gate results to the model (follow-up issue) so the PR
  body can cite the *current* gate state, closing the staleness gap.
- Investigate the 100% prose-rescue rate (two consecutive all-prose runs).
- Consider logging tool results (capped) to session.log for forensics.
