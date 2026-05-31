# feat: hydration helpers — oz conversion, classification, streak (sub-issue of #48)

Sub-issue of #48.

## Goal

Add pure-function helpers with vitest coverage: unit conversion, target-vs-actual classification (including sodium's upper-limit semantics), and the goal-hit streak helper. No Vue; no store; no API calls.

## Context

- Parent: #48.
- Pattern: `frontend/src/utils/sleep.ts` + `frontend/src/utils/sleep.test.ts` (co-located vitest spec). Read both before writing.

## Subtasks

- [ ] Create `frontend/src/utils/hydration.ts` exporting these pure functions (TypeScript, no imports beyond `@/types/hydration`):

  - `mlToFlOz(ml: number): number` — `ml / 29.5735`, rounded to 1dp.
  - `classify(actual: number | null, target: number, semantics: "under-bad" | "upper-limit"): "under" | "on" | "over"`
    - `under-bad` (water, K, Ca, Mg): `actual < target * 0.9` → `"under"`; `actual > target * 1.1` → `"over"`; else `"on"`.
    - `upper-limit` (sodium): `actual <= target` → `"on"`; `actual > target` → `"over"`. Never returns `"under"` — there's no such thing as not enough sodium for this purpose.
    - `actual === null` → `"under"` for `under-bad`, `"on"` for `upper-limit` (treat absence as compliant with an upper limit).
  - `waterGoalStreak(daily: HydrationDaily[], targetOz: number): number` — consecutive calendar-adjacent days where `water_oz !== null && water_oz >= targetOz`, ending at the latest date in the array. Returns 0 if the last day doesn't hit target.
  - `rollingAverage(values: (number | null)[], window: number): (number | null)[]` — for each index, average of the previous `window` non-null values (centred or trailing — use trailing to match the 7d-rolling-avg convention on the sleep page); returns `null` if fewer than `window/2` values available.

- [ ] Create `frontend/src/utils/hydration.test.ts` with vitest cases covering:
  - `mlToFlOz`: 29.5735 → 1.0, 591.47 → 20.0, 0 → 0.
  - `classify` under-bad: tests at boundaries (0.89×, 0.91×, 1.09×, 1.11×, exactly target).
  - `classify` upper-limit: tests at, just below, and just above target.
  - `classify` with null input under both semantics.
  - `waterGoalStreak`: 3 consecutive hits ending today, 3 hits ending yesterday (returns 0), gap day breaks streak, single-day input.
  - `rollingAverage`: simple 7-day window, nulls in window, edges of array.

## Acceptance criteria

- All exports are pure functions (no side effects, no imports of Pinia / fetch / vue).
- vitest passes for every case above.
- `make check` / `npm run typecheck` clean.

## Out of scope

- UI components consuming these helpers (separate sub-issues).
- Date arithmetic beyond what `waterGoalStreak` needs.

