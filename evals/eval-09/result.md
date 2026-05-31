# eval-09 result

Second cross-repo eval, run as a validation of the eval-08 prompt edits (path discipline + issue#/PR# disambiguation). **Both targeted regressions are resolved.** PR #62 lands all three files at their correct paths, the model self-corrected a PR-number hallucination, and the harness host stays clean.

This is the cleanest cross-repo run so far. The remaining issues are pre-existing follow-ups from eval-07, not new findings.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `--params issue_number=54 --params repo=why-pengo/health_track`
- Model: `qwen3.6:latest`
- Config: stock `goose.yaml` (post-PR-#27)
- System prompt: `prompts/goose-system.md` on branch `docs/prompt-path-discipline` — adds two sections (`Adding new files — match the neighbors`, `Issue numbers and PR numbers are different namespaces`). **This eval is the validation that pays for that branch becoming a PR.**
- Target repo: `why-pengo/health_track`, issue #54 (pure frontend helpers + vitest)
- Container: `claude-and-goose-runtime` (Goose 1.35.0 + github-mcp-server 1.0.5)
- 31 tool calls (vs eval-08's 34, on a smaller task)

## What worked — the targeted regressions

### 1. Path discipline (the eval-08 marquee bug) — fully resolved

PR #62 puts all three files where they should be:

| File | Path | Right? |
|---|---|---|
| Types | `frontend/src/types/hydration.ts` | ✓ |
| Module | `frontend/src/utils/hydration.ts` | ✓ |
| Tests | `frontend/src/utils/hydration.test.ts` | ✓ — co-located with module, mirroring `sleep.ts` / `sleep.test.ts` |

Compare to eval-08, where the test file landed at the repo-root `tests/...` instead of `backend/tests/...`. The pattern-matching rule held: the model read `frontend/src/utils/sleep.ts` early in the run (one of 11 `get_file_contents` calls) and used that exact directory for the new files. No host echo of the path bug either — `git status` after the run shows only the eval-NN dirs themselves, no stray `frontend/` in the harness.

### 2. Issue# vs PR# at the API level — fully resolved

No `update_pull_request` with the issue number. No `update_pull_request` at all, in fact — the model used the correct flow: `list_branches` → `create_branch` → `create_or_update_file` × N → ... → `create_pull_request` once. PR #62 was created cleanly, not patched into existence the wrong way.

### 3. Workflow: `add_issue_comment` × 3

eval-08 made zero comments on the issue thread. eval-09 made three: a status-style comment after the files were pushed but before PR creation, a misfired tool call to fix a mistake (see "soft regression" below), and a final comment with the actual PR link after creation. The system prompt rule "Comment on the issue with status" — present since day one — is now being followed reliably.

### 4. Honest verification — held over from eval-07

The PR body's `## Verification` section ends with:

> Static verification only — Node.js / `pnpm` not available in this environment; tests and typecheck did not execute.

That's verbatim "honest verification" framing from the eval-07 prompt edit. No invented blockers; no claim of running tests that weren't run.

### 5. No clone, no `create_repository`, no host pollution

All three structural failure modes from earlier evals stay absent. `find / -name health_track` doesn't even get called this run — the model went straight to MCP reads. PAT scope was never tested because the model didn't reach for the wrong tools.

### 6. Code quality

The helpers code is good. `frontend/src/utils/hydration.ts` (123 lines):

- Doc comments explain semantics (`under-bad` vs `upper-limit` for sodium, null handling)
- `classify` correctly handles `actual == null` for both semantics
- `waterGoalStreak` sorts by date and uses a Map lookup for gap detection
- `mlToFlOz` uses the exact conversion factor (29.5735) the issue specified

Matches the `sleep.ts` style without being told. Same observation as eval-08's router quality — given a clear pattern, qwen3.6 reproduces it faithfully.

## Soft regression — narrative PR#-guessing

The first `add_issue_comment` (posted *before* `create_pull_request`) contained:

> See **PR #57** for the diff.

PR #57 was never created. The model guessed the next PR number ahead of creating it and got it wrong (actual #62). The second issue comment (posted *after* `create_pull_request`) is correct. So the rule "issue # ≠ PR #" is holding at the **tool-call level** (no API calls with wrong numbers), but the model still narrates with guessed PR numbers in prose.

Between the wrong-comment and the corrected comment, the model fumbled with `add_comment_to_pending_review` (intending to "edit the prior issue comment" — there's no MCP tool for that) before recovering with a second `add_issue_comment`. The pending-review call had no underlying review to attach to, and the GitHub API for PR #62 confirms no dangling pending reviews. So nothing was left behind, but the recovery sequence chewed a couple of tool calls.

This is a milder version of the eval-08 bug — text confusion instead of tool-call confusion — and probably needs no prompt change. Worth noting that the model **detected** the mistake ("I see the initial comment didn't include the PR number. Let me fix that") and corrected itself. That's healthy.

## What didn't — pre-existing follow-ups, not new findings

### 1. PR body's verification table still ticks ✓ for things not executed

The body has a table of acceptance criteria, all marked ✓, immediately above the Notes section saying "tests did not execute." This is the **eval-07 follow-up about Subtasks honesty** showing up again in a different shape. The prompt currently says "If you couldn't verify [an acceptance criterion], say so in the PR body — don't tick the checkbox" but the model is interpreting "verify by reading the file" as ticking the box. The "Honest verification" prompt section needs to extend to the checkbox interpretation, not just `## Verification` prose.

Not new. Not worth a separate PR. Folds into a future prompt-iteration round.

### 2. Three issue comments where two would do

The first issue comment was wrong (PR #57), then got fully superseded by the third comment (PR #62). The middle pending-review call was wasted. Net: one wasted issue comment + one wasted tool call. Cosmetic.

### 3. Verification text in first comment is slightly contradictory

The first comment includes both `"Static verification: All files read back from the branch and reviewed ✓"` and `"did not execute; Node.js/pnpm not available"`. The first phrasing reads as "I verified" when really only file content was reviewed. The PR body's Notes section uses cleaner language ("Static verification only — tests and typecheck did not execute"). The issue-comment language is looser than the PR-body language; consistent honesty discipline would tighten both.

## Verdict

Verdict: PASS

First clean cross-repo run. Both eval-08 prompt edits validated. The remaining issues (Subtask checkboxes, PR# narration) are either pre-existing follow-ups or soft variants that don't justify their own prompt iteration yet.

## Action items

- **Open the prompt-edit PR** (`docs/prompt-path-discipline` branch). eval-09 is the validation; cite it in the PR body. Both new sections held under real-world test.
- **Recommend merging PR #62 as-is.** Code is solid; tests are well-specified even if not executed in this run. Run `npm run test -- --run src/utils/hydration.test.ts` locally to confirm pass before merge.
- **Close out the eval-08 PR (#61) workflow** — the fixup commit moving the test file is in place; ready for review/merge.

## Follow-ups for a future prompt iteration round

- Tighten "honest verification" to cover Subtask/AC **checkboxes**, not just the prose `## Verification` section. Concretely: "Don't tick a checkbox for a step you didn't fully execute. If you read the file and verified the logic by inspection, the checkbox stays empty — and you can note 'verified by inspection' in the body."
- Optional: a one-liner about not narrating PR numbers before `create_pull_request` returns. Probably not worth a prompt rule on its own — model self-corrects.
- After the prompt PR merges, consider whether `prompts/goose-system.md` should be split into "system" (immutable rules) and "playbook" (heuristics like match-the-neighbors). Same theme as harness #10 (goosehints layering). Maybe natural to roll into that work rather than fork it.

## Next time

- **Cross-repo loop is now genuinely operational.** Two real-target evals back-to-back; the second one had no structural failures. `docs/using-on-another-repo.md`'s "proven" column can absorb a new bullet: small-surface frontend additions with co-located tests.
- The prompt-validation pattern (commit edit on a branch, run eval against the branch, PR if validation lands) worked. Replicate for future prompt-iteration rounds. Cheap, structured, gives the PR body a real test to point at.
- Multi-file frontend feature (e.g. #55 or #56 from the #48 epic) would be the next interesting test. Different from #50 (multi-file backend that succeeded) and #54 (single-file frontend that succeeded). The remaining "untested" cells are the bigger frontend pages.
