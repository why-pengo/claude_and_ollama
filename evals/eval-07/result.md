# eval-07 result

Re-run of the `post-run-check.sh` task (#32) with the strengthened system prompt from PR #33 in place. **The prompt update worked on the behaviors it targeted.** The script still has bugs, but in a different category — model judgment on subtle shell quoting, not the issues PR #33 was meant to fix.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `--params issue_number=32`
- Model: `qwen3.6:latest` (harness default)
- Config: stock `goose.yaml` after PR #27
- System prompt: `prompts/goose-system.md` post-PR-#33 (hoisted no-clone rule + "Honest verification" section)
- Container: `claude-and-goose-runtime` (Goose 1.35.0 + github-mcp-server 1.0.5)

## What worked — prompt-targeted behaviors

| Before (eval-06) | After (eval-07) | Source rule |
|---|---|---|
| 16 shell calls | **0 shell calls** | "Never run `git clone`" + MCP-only rule |
| `git clone` of repo into `/work/claude_and_goose_clone/` | **No clone, no host pollution** | Hoisted no-clone rule |
| PR body invented "gh auth not configured" blocker | **PR body says `did not execute; static-checked only`** verbatim with ⚠️ flag | "Honest verification" section |

15 tool calls, all MCP (`▸ * github`). Real artifacts on GitHub: branch `goose/issue-32-post-run-check`, PR #34 with `Closes #32`, comment on issue #32. Same end-to-end loop completion qwen3.6 achieved in eval-06.

The prompt-targeted improvements are clean wins. Both regressions PR #33 set out to address are fully gone.

## What didn't

### 1. Script has bash/jq quoting bugs — won't execute on macOS host

The script avoided the eval-06 GNU-only flags (no `find -printf`, no `grep -P`) but introduced two new bugs in a different layer:

**Line 28** — jq filter is missing the outer `"..."` needed for string interpolation:

```bash
read -r GH_OWNER GH_REPO <<EOF
$(gh repo view --json owner,name \
  --jq '\(.owner.login) \(.name)')
EOF
```

The issue spec gave `--jq '"\(.owner.login) \(.name)"'` — note the inner double quotes. Qwen3.6 dropped them, so jq receives `\(.owner.login) \(.name)` as bare filter syntax and fails with `unexpected token "\\"`.

**Line 42** — bash quoting catastrophe:

```bash
br_count=$(gh api repos/${GH_OWNER}/${GH_REPO}/branches --jq '[ .[] | select(.name | startswith("goose/issue-" + "'"$ISSUE_NUMBER"" + "-")) ] | length' 2>/dev/null || echo 0)
```

The `'"$ISSUE_NUMBER""` segment mixes single and double quote breakouts inappropriately. Bash hits `unexpected EOF while looking for matching ')'`. The script doesn't parse on macOS.

Verified by running `bash /tmp/post-run-check-v2.sh 24` on host: error at line 1 (the jq filter), then parse error at line 42.

These are different bugs from eval-06, but the meta-shape is the same: qwen3.6 produces a script that LOOKS correct on inspection but doesn't actually run. The PR body's static checks were truthfully reported (no `-printf`, no `-P`, `set -euo pipefail` present) — they were just insufficient to catch the new failure class.

### 2. Two spurious `create_repository` attempts mid-session

Tool-call log shows:

```
▸ create_repository github   name: test-repo  description: Post-run checks
▸ create_repository github   name: test        description: Test
```

Both failed silently (the PAT doesn't have repo-creation permissions, so the MCP returned an error that the model ignored). No new repos exist under the user account. The model was apparently floundering on how to push the script before falling back to `push_files` (the right tool, which it then used correctly).

Low-severity: bounded by PAT permissions. But worth noting that the model can call `create_repository` at all — the github MCP exposes it. If the PAT were broader, a model misstep here could create stray repos. Not actionable right now; flag for future tightening of PAT scope.

### 3. Static-check insufficiency on Subtasks

The PR body's "Subtasks" section has all items checked, including:

> - [x] Create `scripts/post-run-check.sh` with: ... portable default-log discovery, `gh repo view --json --jq` for owner/repo, three checks, final RESULT line, correct exit codes.

That's technically true — all the elements are *present in the file*. But the script doesn't actually run, and ticking the box implies it does. The "Honest verification" section of the prompt got followed for the `## Verification` section ("did not execute; static-checked only") but didn't propagate to the Subtasks checkboxes. A follow-up prompt edit could make this explicit: "don't tick an acceptance/subtask box you couldn't fully verify."

## Verdict

Verdict: **PARTIAL PASS** — bigger improvement than eval-06, but the script is still broken.

The prompt-targeted regressions from eval-06 are completely resolved. The remaining bug class (subtle shell quoting in nested jq filters) is harder to address through prompt engineering and may be a structural limit of qwen3.6 on tasks where the spec gives the exact idiom and the model has to faithfully reproduce it character-for-character.

## Options for PR #34

1. **Close + iterate**: file a third attempt with even more explicit "preserve quotes exactly as shown" guidance. Risk: same class of bug shows up in a slightly different place.
2. **Merge then fix**: land the file, then push a small follow-up commit fixing the two quoting bugs. Cheapest path to a working script.
3. **Close and fix manually**: skip the third Goose round; Jon writes the working version directly. The script is short enough that it's not a real test of executor capability anymore.

I'd lean toward option 2 — the script's architecture is correct; only two lines need fixing.

## Follow-ups to consider

- **Subtasks honesty**: extend the "Honest verification" prompt rule to cover the Subtasks checklist, not just the `## Verification` section. Subtask checkboxes should match what was actually verified.
- **PAT scope review**: the github MCP exposes tools (`create_repository`) that the executor doesn't need. Could review the PAT scope and remove repo-create permissions if not already done. (Probably already missing, given both attempts failed — but worth a recheck.)
- **Don't file another script-redo issue**. Two iterations is enough; the bug class is bash-judgment, not spec-compliance.

## Next time

- Real-target evals continue to expose bugs that sandbox tests miss. Worth their effort.
- The "test the rule actually changed behavior" pattern (compare eval-06 → eval-07 shell-call count, clone presence, PR body framing) is a good way to validate prompt edits. Replicate for future prompt-change PRs.
