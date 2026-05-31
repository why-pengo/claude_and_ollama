# eval-08 result

First **cross-repo** eval. Goose, running the harness against `why-pengo/health_track`, executed issue #50 (HydrationGoals model + targets API — five-file backend feature). **PR #61 opened with all the right code in mostly the right places.** This is the most ambitious task qwen3.6 has completed end-to-end so far, and the first multi-file backend PR the harness has produced.

But: one path bug breaks the new test file, the harness host got polluted with a stray `tests/` directory, and Goose forgot to comment on the issue.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `--params issue_number=50 --params repo=why-pengo/health_track`
- Model: `qwen3.6:latest`
- Config: stock `goose.yaml` (post-PR-#27)
- System prompt: `prompts/goose-system.md` post-PR-#33
- Target repo: `why-pengo/health_track` (cross-repo — first time)
- Container: `claude-and-goose-runtime` (Goose 1.35.0 + github-mcp-server 1.0.5)
- 34 tool calls total over the run (~12 reads, 7 push_files, 4 shell, 3 write, 1 each of edit / update_pull_request / create_pull_request / create_or_update_file / create_branch / list_branches / issue_read / create_repository)

## What worked

### Multi-file backend feature, first time

PR #61 has **6 files, +359/-2**:

| File | Status | Notes |
|---|---|---|
| `backend/app/models/hydration_goals.py` | ADDED (+18) | Single-row pattern, `id=1`, all 5 electrolyte fields, comment explains why |
| `backend/app/routers/hydration_goals.py` | ADDED (+76) | GET/PUT, `_get_or_seed` with `IntegrityError` race handling, defaults baked in |
| `backend/app/schemas/hydration_goals.py` | ADDED (+20) | Read/Update Pydantic schemas |
| `backend/alembic/versions/c7d9e1a2b4f3_add_hydration_goals_table.py` | ADDED (+35) | Migration |
| `backend/app/main.py` | MODIFIED (+8) | Router registration |
| `backend/tests/conftest.py` | MODIFIED (+10/-2) | Fixture import |
| `tests/test_hydration_goals.py` | ADDED (+192) | **WRONG PATH** — see below |

The router faithfully reproduces the `activity_goals.py` pattern I'd flagged in the #48 investigation, including the `IntegrityError` race-safe insert with a comment explaining the race condition the rollback handles. SQLAlchemy 2.0 `Mapped[int]` syntax, timezone-aware `datetime.now(UTC).isoformat()` — all matching house style without being told.

### Honest self-correction on `/work` confusion

Cross-repo runs surface a structural confusion: `/work` is the **harness** repo, not the target. Goose hit this immediately — early shell call `ls /work/backend/app/` returned "No such file or directory", followed by `ls /work/` (sees the harness), then `find / -name health_track` (empty, confirms the repo isn't cloned). Then the model narrated:

> *"The repo isn't cloned locally, but the `github__push_files` calls worked to push directly. I need to read main.py from GitHub to edit it."*

Correct recovery: switched to `get_file_contents` + `push_files` / `create_or_update_file` for the rest of the run. No clone attempt. No host-as-target writes after that point — except the test file (see below).

### No clone, PAT scope holds

- `git clone`: never invoked. Rule from PR #33 still holding.
- `create_repository`: attempted **once** (line 207 of the log). PAT scope blocked it — `gh api user/repos` shows no new repos today. The eval-07 follow-up note ("the github MCP exposes tools the executor doesn't need") still applies; behavior is exactly what the prompt + PAT design predicted.

## What didn't

### 1. Test file landed at repo root, not `backend/tests/`

The push for the new test file went to `tests/test_hydration_goals.py` — i.e. the **repo root**, not under `backend/`. Every other path in the PR is correctly prefixed `backend/`, including the `conftest.py` it modified. The PR body's own "Changes" table lists it as `backend/tests/test_hydration_goals.py` — so the PR body **contradicts** what was actually pushed.

The test imports use `from app.models.hydration_goals import ...`, which only resolves with `cwd=backend/`. Pytest can be configured to run from root with rootdir hacks, but health_track's existing `backend/tests/` layout strongly implies pytest runs from `backend/`. As shipped, the new tests likely won't be discovered or won't import. **Same meta-shape as eval-06/07 quote bugs**: code structurally produced, surface-correct on review, broken by one character/path slip.

### 2. Host pollution in the harness repo

Same path bug had a host echo. Goose ran `▸ write path=/work/tests/test_hydration_goals.py` (line 719 of the session log), so a stray `tests/` directory appeared in the **claude_and_goose harness repo's** working tree. Confirmed via `git status --short` showing `?? tests/` after the run. Cleaned up manually (`rm -rf tests/`) — fully reversible, but it's host pollution of the same class as eval-06's clone leak. Different mechanism (local `write` tool instead of `git clone`), same end state.

The system prompt says "If you need scratch space, write under `/tmp` — it disappears when the container exits." Goose **did** use `/tmp` correctly for two earlier scratch writes (`/tmp/hydration_goals_model.py`, `/tmp/subtask1.py`) — so the rule got partial uptake. The third write was supposed to be the canonical test file pushed to the target, and got the path wrong on both surfaces (push and local).

### 3. `update_pull_request pullNumber: 50` — issue#/PR# confusion

Around line 473, the model called:

```
▸ update_pull_request github
    base: main
    owner: why-pengo
    pullNumber: 50
    repo: health_track
```

PR #50 does not exist in health_track (PR numbers there jump from #47 to #61). The model passed the **issue number** as `pullNumber`. The MCP returned an error, the model ignored it (no Traceback in the log), and ~750 lines later called `create_pull_request` correctly, getting PR #61. Wasted ~750 log lines and several tool calls reading content into a branch it couldn't update.

This is a category we haven't seen before: not a hallucination, not a quoting bug — a **parameter-confusion bug**. The issue is named `#50`, the model called `issue_read` on `50`, and then conflated that number with a PR number in a different namespace. Both number-spaces share the visual `#N` form; the prompt doesn't currently disambiguate.

### 4. No comment on issue #50

The system prompt says:

> Comment on the issue with status; open a PR with `Closes #N` if files changed.

Tool-call summary shows zero `add_issue_comment` calls. `issue_read` was called once (to fetch the issue body), but the model never wrote back to #50. The PR body has `Resolves #50` (will close on merge), but there's no in-progress status comment on the issue.

This is a workflow miss, not a code miss. We've had it in past evals as well, just not called out — worth adding to the follow-ups list.

### 5. PR body's "Changes" table contradicts the actual diff

The PR body lists `backend/tests/test_hydration_goals.py` as a file changed — but the actual file in the diff is at `tests/test_hydration_goals.py`. The model wrote the body **describing what it intended** rather than what it actually pushed. Same honesty class as the "Subtasks checkbox" issue from eval-07: the model believes it did the right thing even when the artifact disagrees.

## Verdict

Verdict: **PARTIAL PASS — meaningful progress**

The "what hasn't been tested" line in `docs/using-on-another-repo.md` — multi-file changes — has been tested for the first time and the answer is *yes, partially*. qwen3.6 can produce a structurally correct 6-file backend feature whose router + model + schema + migration + main.py registration + conftest fixture all interlock and faithfully copy the established pattern in the codebase. That's a real capability we didn't have evidence for yesterday.

The remaining failures are recoverable: the path bug is one `git mv`, the PR body needs one edit, the issue needs a comment. The harness pollution is `rm -rf tests/`. None of these are structural — the model was 95% right and got the last 5% wrong in characteristic qwen3.6 ways (subtle path slip + workflow gap).

## Options for PR #61

1. **Merge with fixups** — push a follow-up commit moving `tests/test_hydration_goals.py` to `backend/tests/test_hydration_goals.py`, run the tests locally to confirm they actually run, fix the PR body's table. Two minutes of human work; preserves the model's actual progress.
2. **Close + redo** — file a new attempt with explicit path discipline in the issue body. High risk of same class of bug in a different place; not learning anything new.
3. **Pause and prompt-edit first** — the path bug is the eval-08 equivalent of eval-06's GNU-flags bug: the kind of thing a prompt rule could catch. Add "before each `push_files` call, double-check the path against the directory structure shown by `get_file_contents` reads" or similar. Then re-run #50 fresh.

I'd lean toward **option 1** — the substance of the work is there. eval-09 would be a better test of the prompt-improvement hypothesis on a **different** task (e.g. #54 — pure helpers + vitest, frontend, much smaller surface).

## Follow-ups to consider

- **Path discipline in the prompt**: add a rule like "when pushing a new file, the path must match the existing pattern observed in `get_file_contents` reads. If unsure, read a sibling file first to confirm the directory." Targets the eval-08 path bug class directly.
- **PR# vs issue# disambiguation**: the prompt doesn't currently say anything about PR numbers being separate from issue numbers. Add a one-liner: "the issue number is **not** the PR number — never pass the issue number to `update_pull_request`". Cheap to add, would have saved ~750 log lines on this run.
- **Mandatory issue comment**: enforce in the prompt that an `add_issue_comment` call happens at the start of the run (status: starting) and on completion (status: PR opened / blocked / done). Currently the prompt says it but the model treats it as optional.
- **Cross-repo `post-run-check.sh`**: ran with `./scripts/post-run-check.sh 50 evals/eval-08/goose-session.log` and got Check 1 PASS, Check 2/3 FAIL. The script hardcodes `gh repo view` (cwd's repo) for branch/PR lookup, so it can't validate cross-repo runs. Needs a `--repo owner/name` flag. File as a goose-task issue — small, scoped, perfect Goose work.
- **PR-body honesty rule**: extend the eval-07 "Honest verification" prompt section to cover *all* PR body claims, not just `## Verification`. Specifically: if the body lists a file path, it must match the actual push path. (Hard to enforce in prompt alone; might need post-run-check to diff body claims vs reality.)
- **No `create_repository` for executor**: the github MCP exposes `create_repository` and the model attempts it under pressure. Probably worth filing an upstream issue or local config to remove tools the executor never needs. PAT scope is the current backstop and is working, but defense in depth is cheap.

## Next time

- Cross-repo works. The container `/work` confusion is real but the model navigated it within ~5 tool calls. Doc update: `docs/using-on-another-repo.md` should mention this — "expect 1-3 wasted shell calls early on as the model figures out /work is the harness, not the target."
- Multi-file backend features are now in the "proven" column with caveats. Promote in `docs/using-on-another-repo.md` once option 1 fixups merge cleanly.
- The "test the rule actually changed behavior" pattern from eval-07 should be repeated for the path-discipline prompt edit, if we make it. Compare eval-08 → eval-09 on path-correctness specifically.
- Issue #54 (pure helpers + vitest, frontend) is a good next eval — different language, different surface, much smaller. Tests the prompt edits on something orthogonal before risking another multi-file backend run.
