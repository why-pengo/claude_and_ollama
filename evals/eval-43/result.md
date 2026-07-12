# eval-43 result — sizing-rules run №2, gate fully armed

## What ran

- health_track#111 (same issue as eval-42), `qwen2.5-coder:32b @
  temperature=0.2`, runner main `60f83d5`.
- Target develop `402c38e` — both eval-42 fixes live: #116 (`make test`
  runs host pytest against the checked-out tree) and #117 (autoflake in
  `make format`).

## What worked — every harness layer, including both new ones

- **#116 proven live**: the model's test commit produced an honest
  `make test` red — `ModuleNotFoundError` at collection, fed back with
  the full traceback. In eval-42 this exact commit sailed through green.
- **The gate-visible-increment design (#143) held**: no premature PR.
  The eval-42 outcome (honest-but-partial PR on a green gate) is
  structurally impossible now, and indeed did not happen.
- **Issue structure was followed**: schema → tests → service, in order.
  The model moved from the held-open red to subtask 3 (committed
  `analytics.py`) instead of churning on its tests — the eval-42
  sizing/sequencing concern did not recur.
- **Remediation: 15 mechanical commits, all correct**, including
  multi-file fixes; the autoflake upgrade kept every F401-class error
  out of the model's turn budget. No laundering: flake8 errors autoflake
  can't fix (undefined names from the drift, below) stayed red.
- Give-up at turn 25 (3 unparseable turns), honest salvage PR
  [health_track#118](https://github.com/why-pengo/health_track/pull/118)
  (30 commits: 15 model + 15 remediation), workspace restored.

## What didn't — a new, precisely-isolated model boundary: error localization

The model's test file (commit 2) used `from backend.app.services…` —
the **documented path-slip anti-pattern** (AGENTS.md's
conventions-agents-get-wrong section names it; second consecutive run
it's been committed). The gate traceback pointed at the defect exactly:
`tests/test_hydration.py:1 … ModuleNotFoundError: No module named
'backend'`.

The model never touched `test_hydration.py` again. Instead it
re-diagnosed the import failure as a codebase-wide problem and spent
turns 8–24 "fixing" imports in files it had no business in:
`routers/bp.py`, `schemas/bp.py`, `database.py`, `utils.py` — chasing
hallucinated missing symbols (`get_current_user`, `get_session`,
`normalise_dt`), eventually creating an `app/utils/` package alongside
`app/utils.py` (a name collision breaking every `app.utils` import).
Context ballooned to ~32k prompt tokens/turn, tool-call JSON degraded
to unparseable (the eval-42 endgame), give-up at turn 25.

The gate contained all of it: every drift commit stayed red, nothing
reached a PR. But the boundary is clear — **given an exact
file:line traceback, the model cannot reliably localize the fix to its
own file**; it prefers inventing problems in unrelated code over
re-reading its own commit. That, not task sizing, is now the binding
constraint: the issue structure was executed correctly until the first
diagnosis was needed.

## Verdict
Verdict: FAIL

Model layer only. Both eval-42 harness fixes are verified live; the
#143 sizing rules did their job (ordered execution, no premature PR).

## Next time

- **Mechanize the path-slip convention** (prose has now failed twice at
  the same line): a health_track `check` entry that greps
  `backend/tests` for `from backend\.` / `import backend`, with a `fix:`
  sed rewrite to `app.` — the ADR-0009 move for the exact defect that
  triggered the drift.
- **Scope-drift guard investigation (GO/NOGO)**: the runner knows which
  files the issue names and which files the model committed. Feedback
  (or a block) when a commit touches paths outside the issue's scope
  would have cut turns 8–24 to one warning. Needs design care —
  legitimate adjacent-file edits exist.
- **Context ceiling recurred** (~32k prompt tokens/turn → truncated
  tool-call JSON; 486k total prompt tokens this session). Repeated
  gate-feedback blocks dominate the transcript; a dedupe/prune
  investigation is now blocking any longer-horizon task.
