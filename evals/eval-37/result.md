# eval-37 result — epic #111 acceptance run №1

## What ran

- Recipe: `recipes/execute-issue.yaml` (post-#110, gate-aligned)
- Params: `issue_number=51`, `repo=why-pengo/health_track`, resolved `base_branch=develop`
- Model: `qwen2.5-coder:32b @ temperature=0.2` (ADR-0008 defaults)
- Workspace: local health_track checkout, pre-flighted clean at develop tip
- First run with the full #111 pipeline live: AGENTS.md pre-flight (#107),
  post-commit gate (#108), failure feedback + PR block + salvage
  verification (#109), gate-aligned recipe (#110). Target repo carried its
  first conforming AGENTS.md (health_track#94).

## What worked — every #111 mechanism fired correctly

1. **AGENTS.md pre-flight**: parsed health_track's root file —
   `AGENTS: verification=[check, test], 7 conventions` in the banner.
2. **Gate ran after the first commit** and caught a real defect:
   `make check` FAIL exit 2 (`F401 'typing.List' imported but unused` —
   the model violated the documented py3.12 convention), `make test`
   PASS (35.3s). Honest per-command block in the session log.
3. **Failure feedback**: `[runner: gate red — feeding failure back to the
   model]` — the model received the flake8 output and kept working.
4. **PR-open block**: every `create_pull_request` attempt (5+) was refused
   with `blocked — last gate red`. **No red PR was shipped.** The eval-35
   fabrication pattern is structurally impossible now.
5. **Loop-detect**: aborted at turn 30 after 4 identical no-progress
   signatures — bounded the stuck session exactly as designed.
6. **Salvage**: opened health_track#100 mechanically (13 commits) with a
   `## Verification` block reporting the last gate honestly — `make check:
   FAIL (exit 2)` plus the real flake8/isort output, `make test: PASS`.
   Issue comment posted. A reviewer sees the truth, not prose.

## What didn't — one harness bug, found by this run

**The gate wedged itself after its first run.** `make check` runs
`make format` (isort + black) before flake8 — a *mutating* command. It
reformatted the model's unformatted `hydration.py` in the workspace,
leaving the tree dirty. Every subsequent gate run then failed at
`git checkout -B` with "local changes would be overwritten" → `GateError`
→ gate skipped for all 12 later commits. Consequences:

- `gate_state` stayed frozen on the first (red) result, so the PR block
  refused forever — even after the model had actually fixed the F401.
- `restore_workspace` failed on the same dirt at session end (workspace
  left on the runner branch; restored manually after).

The failure is contained to workspace hygiene in `run_gate`: it must
`git reset --hard` before syncing so mutating verification commands can't
wedge it. `restore_workspace` needs the same hardening for the
runner-branch case.

## Observations

- **100% prose-rescue rate**: every single tool call this session came
  through the prose channel and was rescued (#84's mechanism carried the
  entire run). Worth watching; eval-35 had a mix.
- The model *did* respond to gate feedback correctly — its second commit
  addressed the formatting failure. With a working gate it plausibly goes
  green within a few commits.
- 13 commits on the salvage branch is thrash from the wedged gate
  (blocked PR → re-commit → blocked → …), not model pathology.

## Verdict
Verdict: FAIL

Structural PASS for every #111 mechanism individually; run-level FAIL on
the gate-wedge bug. The bug is exactly what an acceptance run exists to
find.

## Next time
- `run_gate`: `git reset --hard` before fetch/checkout (fix in follow-up
  PR; re-run recorded as eval-38).
- `restore_workspace`: reset before checkout when the session left the
  workspace on a runner branch — mutations there are gate artifacts by
  construction (pre-flight guaranteed clean at session start).
- Watch the prose-rescue rate across runs; if 100% persists, the
  tool-call channel regression deserves its own investigation.
