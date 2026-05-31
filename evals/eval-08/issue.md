# feat: HydrationGoals model + targets API (sub-issue of #48)

Sub-issue of #48.

## Goal

Add a single-row `HydrationGoals` model + `/api/hydration-goals` GET/PUT endpoints with 5 target fields and sensible RDA defaults. End-to-end mirror of the existing `ActivityGoals` pattern.

## Context

- Parent: #48.
- Pattern to mirror exactly:
  - `backend/app/models/activity_goals.py` — single-row table, `id=1` sentinel.
  - `backend/app/routers/activity_goals.py` — `_get_or_seed` helper, GET + PUT, JWT via `Depends(get_current_user)`.
  - `backend/app/schemas/activity_goals.py` — Pydantic schemas.
  - `backend/alembic/versions/01f82f4a768d_add_activity_goals_table.py` — migration shape.
  - `backend/tests/test_activity_goals.py` — test structure.
- Router registration: `backend/app/main.py` already has `app.include_router(activity_goals_router.router)`; add the hydration goals router alongside.

## Default values (defined on `_get_or_seed`)

| Field | Default | Source |
|---|---|---|
| `water_target_oz` | 64 | CDC / common rec |
| `sodium_target_mg` | 2300 | CDC upper limit |
| `potassium_target_mg` | 3400 | NASEM adult male AI |
| `calcium_target_mg` | 1000 | NASEM adult RDA |
| `magnesium_target_mg` | 400 | NASEM adult male RDA |

## Subtasks

- [ ] Create `backend/app/models/hydration_goals.py` with 5 `int` fields (all `nullable=False`), `id=1` sentinel, `updated_at` ISO string.
- [ ] Create `backend/app/schemas/hydration_goals.py` with `HydrationGoalsRead` and `HydrationGoalsUpdate`.
- [ ] Create `backend/app/routers/hydration_goals.py` mirroring `activity_goals.py` (`_get_or_seed` with defaults above, GET + PUT under JWT, prefix `/api/hydration-goals`).
- [ ] Register the router in `backend/app/main.py`.
- [ ] Add alembic migration `backend/alembic/versions/{new_hash}_add_hydration_goals_table.py` creating the table with the 5 columns + `updated_at`.
- [ ] Add `backend/tests/test_hydration_goals.py` covering: GET seeds defaults on first read, PUT persists, JWT required (401 without), persistence across two GETs, validation rejects negative values.

## Acceptance criteria

- `GET /api/hydration-goals` on a fresh DB returns the 5 defaults.
- `PUT /api/hydration-goals` with the 5 fields persists; subsequent GET returns the new values.
- Both endpoints return 401 without JWT.
- New code has tests; `make check` clean; no drop in existing project coverage.

## Out of scope

- Settings UI to edit these values (separate sub-issue).
- Per-user goals — single-row, single-user app.
- Any frontend code.

