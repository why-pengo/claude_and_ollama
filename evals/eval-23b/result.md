# eval-23b result

Second attempt of the eval-23 k-of-3 batch. See
[eval-23/result.md](../eval-23/result.md) for the consolidated writeup
across all three attempts.

## What ran

Same as eval-23 (runner v2 + salvage on `main` @ 82879a1 + ae87496 +
7ca2fa5 against `health_track#51`). State reset before this attempt:
PR closed, branch deleted.

## What happened

4 commits landed on the branch (Step 3 complete), model hit Step 5
boundary, fired one more `create_or_update_file` after the first nudge
instead of `create_pull_request`, then went silent for 3 turns. Runner
gave up at turn 17. **Salvage fired** and opened PR #72 mechanically
with the 4 commits + posted `⚠️ partial` comment on #51. First time
salvage fired in a live eval — validated the integration path that the
smoke test and force-fire test couldn't reach.

## Verdict
Verdict: PASS
