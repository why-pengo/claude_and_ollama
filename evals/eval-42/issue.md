# feat: hydration daily aggregation — HydrationDaily schema + service + tests

Part of #51 (re-cut per claude_and_ollama#143 sizing rules).

## Goal

The service layer can produce the combined per-day hydration shape: one entry per date covering all 5 hydration metrics — water in fluid ounces (1dp), electrolytes in mg (integer) — with `None` (not `0`) for metrics missing on a date, and no row for dates with none of the 5. No router yet (#112).

## Context

- Reuse `backend/app/services/analytics.py::get_daily_series(session, rec_type, date_from, date_to)` — returns avg/sum/min/max/n per day for any `health_records.type`.
- Type keys in `health_records.type`: `dietary_water`, `sodium`, `potassium`, `calcium`, `magnesium`.
- Water is stored in mL (HAE imports): `water_oz = water_ml / 29.5735`, rounded to 1dp. Electrolytes are mg already — round to nearest integer.
- Test fixtures: `backend/tests/conftest.py` (`db_session`); pattern reference: `backend/tests/test_sleep.py`.
- Conventions: `backend/AGENTS.md` — py3.12 unions (`float | None`, never `Optional[float]`).

## Subtasks

- [ ] Add `backend/app/schemas/hydration.py`: pydantic `HydrationDaily` with exactly `date: str`, `water_oz: float | None`, `sodium_mg: int | None`, `potassium_mg: int | None`, `calcium_mg: int | None`, `magnesium_mg: int | None`.
- [ ] Add `backend/tests/test_hydration.py` with service-level tests of `get_hydration_daily` (import from `app.services.analytics`): empty result for an empty range; per-day merge across all 5 metrics; date filtering honoured; mL→fl-oz correct to 1dp; missing metric → `None` not `0`. These tests fail until the next subtask lands — commit them anyway; the gate stays red until the issue is complete.
- [ ] Add `get_hydration_daily(session, date_from, date_to)` in `backend/app/services/analytics.py`: call `get_daily_series` once per type key, index results by date, merge into the per-day shape, convert water mL→fl-oz.

## Acceptance criteria

- `make test` passes (the new `backend/tests/test_hydration.py` tests are green).
- `make check-only` passes.

## Out of scope

- The router/endpoint and its registration — #112 (depends on this issue).
- Hydration targets/goals (#50), frontend consumption, other unit conversions (cups, mL, mmol).

