# eval-34 result

Shakedown for #98 (GO Approach E from #97): runner-owned branch naming via templated `{{ branch }}`. Validates the back-to-back same-task collision is gone.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Target: `why-pengo/health_track#51` (the hydration-daily-endpoint task — the same canonical task that PARTIALed in eval-30b, eval-31c, eval-32c, and the discarded eval-33)
- Model: `qwen2.5-coder:32b` at `temperature=0.2` — the worst-case combo from the bake-off data, where eval-31c spammed five "branch already exists" comments
- Two back-to-back invocations, no manual `health_track` cleanup between them, leftover artefacts from prior evals deliberately left in place

## What worked

Both runs completed cleanly to PR-fired + comment-fired, without ever touching the failure mode #98 was scoped to eliminate.

| | Run 1 | Run 2 |
|---|---|---|
| Branch | `runner/issue-51-20260627-065919` | `runner/issue-51-20260627-070232` |
| PR | [#89](https://github.com/why-pengo/health_track/pull/89) | [#90](https://github.com/why-pengo/health_track/pull/90) |
| Turns | 10 | 12 |
| Wall | 152.4s | 104.0s |
| Status | ✅ done | ✅ done |
| Session-end marker | `Recipe complete: PR + issue comment both fired (turn 10)` | `Recipe complete: PR + issue comment both fired (turn 12)` |

Acceptance criteria from #98 / step 4 of the shakedown:

- [x] Different `branch=...` values in the two startup banners (3min 13s apart, distinct timestamps).
- [x] No `ERROR creating branch:` or `Reference already exists` in either log.
- [x] No `ERROR opening PR:` or `HTTP 422` in either log.
- [x] No `Loop detected:` in either log.
- [x] Two distinct PRs (#89, #90) opened against the same issue, each on its own timestamped branch, each with `Closes #51`.

## What didn't

Nothing. Both runs are clean PASS.

## Verdict

**Verdict: PASS**

The fix from #98 holds under the worst-case combo. The runner generates `runner/issue-51-<YYYYMMDD-HHMMSS>` at session start; the model uses the templated `{{ branch }}` value verbatim; back-to-back invocations get distinct branches; `create_branch` and `create_pull_request` both succeed cleanly. The collision failure mode that drove 5 PARTIALs across the bake-off and temperature evals is gone.

## Next time

- qwen2.5-coder:32b at `temperature=0.2` is now an actually-defensible alternative-default candidate — the within-batch collision was the only thing keeping it from 3/3. A clean 3-of-3 rerun at this config is worth doing if the production-default question gets revisited.
- Cleanup: PRs #89 and #90 on `health_track` can be closed (this was a shakedown, not real work). Their branches go with them via `gh pr close --delete-branch`.
- Approach A's 422-interception (deferred per #98) becomes defence-in-depth for unrelated 422s. Not urgent — there's no eval-data signal driving it. File when convenient.
