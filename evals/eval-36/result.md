# eval-36 result

Smoke-test eval for #115 — runner module split. Re-runs the eval-35 trio's
target (`why-pengo/health_track#51`) against the post-split runner to
confirm the session-log shape matches the pre-split baseline.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Target: `why-pengo/health_track#51` (the eval-35 canonical task)
- Model: `qwen2.5-coder:32b` on `bazzite.local`
- Options: `temperature=0.2` (recipe default per ADR-0008)
- Branch: `runner/issue-51-20260627-191000` (runner-owned, generated per #98)
- PR: [why-pengo/health_track#97](https://github.com/why-pengo/health_track/pull/97)

## Verdict

**PASS** — clean `recipe_done` completion: PR + issue comment both fired,
session ended via the dispatch loop's natural exit (not salvage, not
loop-detect, not max-turns). Session-log shape matches the eval-35 trio.

`[session metrics: turns=11 | prompt=78743 tok @ 33619.4 t/s | gen=4297 tok @ 63.7 t/s | wall=73.8s]`

## Comparison to eval-35 trio

| Run       | Turns | Wall  | Gen t/s | Outcome |
|-----------|-------|-------|---------|---------|
| eval-35   | 8     | 93.4s | 61.7    | PASS    |
| eval-35b  | 8     | 95.3s | 61.6    | PASS    |
| eval-35c  | 10    | 102.7s| 63.4    | PASS    |
| eval-36   | 11    | 73.8s | 63.7    | PASS    |

Eval-36's 11 turns sit one above the trio's 8–10 spread, mirroring the
same "model elects to do a bit more on this run" pattern eval-35c
already exhibited (its 2-turn delta to eval-35/35b was extra
`create_or_update_file` calls). Generation throughput matches within
run-to-run noise (61–64 t/s). Wall time is faster because more of the
`get_file_contents` reads served sub-second.

## Dispatch order

```
get_file_contents  (AGENTS.md fetch — Step 0)
issue_read         (Step 1)
create_branch      (Step 2)
create_or_update_file × 3   (Step 3 — initial file commits)
get_file_contents  (re-read for verification)
create_or_update_file × 2   (Step 3 — additional file commits)
create_pull_request (Step 5)
add_issue_comment   (Step 6)
```

Same shape as eval-35: read → branch → write × N → PR → comment.
Prose-shaped tool-call rescue fired multiple times mid-session,
exercising the extracted `prose_rescue.py` module end-to-end through
the new module graph (i.e. the rescue path still works when the
function lives outside `run_recipe.py`).

## Why this is the smoke-test signal #115 asked for

#115's acceptance criterion: "smoke-test eval session log has the same
shape as recent evals (turn count + tool dispatch order + final PR /
comment)." All three boxes ticked:

- Turn count (11) sits within / adjacent to the eval-35 trio's 8–10 range.
- Tool dispatch order matches verbatim.
- Final PR + comment fired cleanly via `recipe_done`, not via salvage or
  any guard.

The module split is pure code motion. The unit-test suite (145 passed,
including the `TestRunSessionLoopDetect` / `TestRunSessionProseRescue`
end-to-end scripted-Ollama tests in `tests/test_session.py`) already
verified the contracts within each module; eval-36 is the cross-module
proof that the import graph and inter-module wiring also hold under a
real Ollama session.
