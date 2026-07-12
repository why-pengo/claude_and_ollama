# eval-42 result — first run under the #143 sizing rules

## What ran

- health_track#111 (re-cut from #51 per #143: 3 subtasks, 3 files,
  300-word body, tests ordered before the service so incompleteness
  stays gate-visible), `qwen2.5-coder:32b @ temperature=0.2`.
- Runner main `60f83d5`, target develop `e4e4012`.

## What worked

- Subtask 1 (schema): committed, isort red → mechanical remediation →
  **gate PASS**. Second consecutive run where formatting cost zero
  model turns.
- Remediation fired 8 times total across the session, every one
  correct: import-order fixed mechanically, flake8 semantics left for
  the model. No false commits, no laundering.
- Salvage: honest PR [health_track#113](https://github.com/why-pengo/health_track/pull/113)
  (16 commits: 8 model + 8 remediation), honest issue comment.
- The give-up path worked: 3 consecutive unparseable turns → clean
  abort at turn 15 (578s wall), workspace restored.

## What didn't

**1. The gate's `make test` never tested the runner's code — target
config blind spot (the big finding).** `make test` is
`docker compose exec backend pytest`, but `docker-compose.yml` mounts
only `./data:/data` — backend code is **baked into the image**, and
the stack on this host runs production mode (up 9h). Every
`[gate: make test] PASS (35s)` in eval-41 *and* 42 tested the image's
code snapshot, not the committed tree. Consequences:

- The #143 tests-first mechanism was **inert**: the model's tests
  (importing a nonexistent `get_hydration_daily`) should have turned
  `make test` red; instead it stayed green throughout.
- This is eval-38's false-green class at the Docker boundary. The #154
  detectors can't see it — the command exits honestly, the workspace
  is untouched; it just tests *something else*.
- Fix belongs in health_track: `make test` must run pytest against the
  checked-out tree (bind-mount the code, `docker compose run` with a
  volume, or host-venv pytest like `make check-only` already does).

**2. The model can't fix flake8 semantics — eval-40's boundary, lint
edition.** Its test file imported `db_session` from conftest (pytest
injects fixtures; the import is the classic anti-pattern) → F401 ×3,
F811 ×5, F841 ×2, with exact line numbers in every feedback message.
Seven commits titled "fix: Remove unused imports…" resent **the same
file** — the eval-39 blind-resend pattern. `make format` (isort+black)
can't remove imports, so remediation cleaned the ordering each time
and the semantic errors survived. Note: most of this class *does* have
a deterministic fixer — autoflake (`--remove-unused-imports`
would have killed the F401s and, with them, the F811s).

**3. Context-degradation endgame.** By turn 12 (32k prompt tokens) the
model's tool calls arrived as truncated JSON in the prose channel
(190–618 gen tokens for a ~1,500-token call) — unparseable, so
prose-rescue correctly refused them; 3 straight → give-up. Not a
rescue bug: rescue rate was 100% on well-formed turns. First run to
break the 100%-rescue streak, for a new reason (truncation, not
formatting).

Also noted: the model's test imports used `backend.app.services…` —
the documented "path slip" from AGENTS.md's conventions-agents-get-
wrong section (tests run with `cwd=backend`). Moot given finding 1,
but conventions-by-prose failed again.

## Verdict
Verdict: FAIL

The sizing-rules question (#143) is **unanswered, not refuted**: the
mechanism the sizing unit depends on — tests keeping the gate red —
never engaged because of finding 1. Re-run after health_track's
`make test` tests the tree.

## Next time

- File + fix health_track: `make test` must test the checked-out tree,
  not the image (finding 1) — then re-run this issue as the real #143
  acceptance (eval-43).
- Propose autoflake in health_track's `make format` (and as a gate
  `fix:`): the F401/F811 class that killed this run has a deterministic
  solver — ADR-0009 says use it.
- The truncation endgame suggests a max-useful-context ceiling for this
  model well below `num_ctx`: by 32k prompt tokens, tool-call JSON
  degraded. Worth a note in any future bake-off scoring; mitigations
  (message pruning, failure-message dedup) are a separate
  investigation.
