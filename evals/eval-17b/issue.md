# feat: GET /api/hydration/daily — combined per-day shape (sub-issue of #48)

Sub-issue of #48.

## Goal

Add `GET /api/hydration/daily?from&to` returning one row per date covering all 5 hydration metrics — water in fluid ounces, electrolytes in mg. Single round-trip for the page rather than 5 endpoints.

## Context

- Parent: #48.
- Reuse: `backend/app/services/analytics.py::get_daily_series(session, rec_type, date_from, date_to)` already returns avg/sum/min/max/n per day for any `health_records.type`. Call it 5 times in parallel for the 5 type keys.
- Type keys in `health_records.type`: `dietary_water`, `sodium`, `potassium`, `calcium`, `magnesium`. All confirmed present in production data (#48 lists row counts).
- Conversion: `water_oz = water_ml / 29.5735` (water is stored in mL in HAE imports). Electrolytes are stored in mg already — pass through.
- Router registration pattern: same as `backend/app/routers/sleep.py`'s `nightly` endpoint — registered in `backend/app/main.py`.
- Test pattern: `backend/tests/test_sleep.py` (sleep router test file).

## Response shape

```json
[
  { "date": "2026-05-10", "water_oz": 64.0, "sodium_mg": 2100, "potassium_mg": 3200, "calcium_mg": 950, "magnesium_mg": 380 },
  ...
]
```

- Missing metric on a date → field is `null`, not `0`. (A user might log water but skip electrolytes that day.)
- Dates without any of the 5 metrics → no row.
- Round to 1 decimal place for `water_oz`; round to nearest integer for mg fields.

## Subtasks

- [ ] Add `HydrationDaily` schema in `backend/app/schemas/hydration.py` with the 6 fields above (`date`, `water_oz: float | None`, 4 × `int | None`).
- [ ] Add `get_hydration_daily(session, date_from, date_to)` in `backend/app/services/analytics.py`. Calls `get_daily_series` for each of the 5 type keys, indexes results by date, merges into the combined per-day shape, converts mL→fl-oz for water.
- [ ] Add `backend/app/routers/hydration.py` exposing `GET /api/hydration/daily` with `from`/`to` query params (aliased like sleep's `nightly` route), JWT-protected, response model `list[HydrationDaily]`.
- [ ] Register the router in `backend/app/main.py`.
- [ ] Add `backend/tests/test_hydration.py` covering: empty result for an empty range, per-day aggregation across all 5 metrics, date filtering honoured, mL→fl-oz conversion correct to 1dp, missing-metric returns `null` not 0, JWT required (401).

## Acceptance criteria

- `GET /api/hydration/daily?from=2026-05-01&to=2026-05-10` returns one entry per date in range that has at least one of the 5 metrics, all five fields filled in (or `null`).
- Water values are in fluid ounces, rounded to 1dp.
- Electrolyte values are in mg, rounded to integer.
- Endpoint requires JWT (401 without).
- New code has tests; `make check` clean.

## Out of scope

- Hydration targets / goals (separate sub-issue, #50).
- Frontend consumption (separate sub-issue).
- Other unit conversions (cups, mL, mmol) — single units only.
