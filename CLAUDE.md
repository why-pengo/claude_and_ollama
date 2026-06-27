# claude_and_ollama — Claude Code Instructions

This repo is an evaluation harness for a two-agent code workflow:

- **Claude Code** is the planner. It reads context, decomposes work,
  and authors structured GitHub Issues.
- **The runner** (`runner/run_recipe.py`, calling a local Ollama model
  on `bazzite.local`) is the executor. It reads one issue at a time,
  executes its subtask checklist, comments with results, and opens
  a PR. If the model exits before the PR call, the salvage step opens
  a mechanical PR from the branch so work doesn't orphan.

This repo holds recipes, prompts, the runner, and eval results. It is
**not the target project** — it is the rig that drives the runner
against other repos (and against itself, for shakedown evals).

The project was originally Goose-based ("claude_and_goose"); the
runner replaced Goose's session loop after the eval-17/19 series
identified Goose's exit-0-on-prose-only-turn as the structural
reliability ceiling. Eval history under `evals/` references Goose
because that's what was running at the time.

---

## Your Role in This Repo (Claude Code)

Your default job here is to **author or refine GitHub Issues that the
runner can execute**, not to write the implementation yourself. The
runner owns execution; you own decomposition, sequencing, and review.

When the user asks for new work:
1. Decide whether it's one leaf issue or an epic with children.
2. Draft issues against the format in `prompts/issue-format.md`.
3. Apply labels (see below).
4. Only mark `ready-for-execution` once all dependencies are closed.

Exceptions: harness-level changes (recipes, prompts, the runner
itself, this file, scripts) are written by Claude Code directly —
the runner operates the harness, it doesn't edit it.

---

## GitHub Issue Format

Canonical spec lives in `prompts/issue-format.md`. Required sections:

1. **Title** — imperative, conventional-commit prefix
   (e.g. `feat: parse YAML front-matter in note files`)
2. **Goal** — one paragraph; what outcome counts as done
3. **Context** — links to related issues, prior decisions, files
   the runner must read first
4. **Subtasks** — GitHub checklist; each item one concrete,
   independently verifiable change, ordered so earlier items unblock
   later ones
5. **Acceptance criteria** — bulleted observable outcomes
6. **Out of scope** — explicit list of what NOT to do

If an issue can't be expressed this way, it's too big — split it.

---

## Labels

| Label                  | Meaning |
|------------------------|---------|
| `runner-task`          | Eligible for runner execution. Must conform to the issue format. |
| `ready-for-execution`  | All prereqs merged, context resolved, the runner can pick it up. |
| `blocked`              | Waiting on another issue, decision, or external input. Body must state what's blocking. |
| `done`                 | Closed by a merged PR. Applied by the closing PR, never manually. |
| `epic`                 | Parent issue tracking a body of work via a checklist of child issue links. |

---

## Branch Naming

- Runner-executed work: `runner/issue-<N>-<short-slug>`
  (e.g. `runner/issue-42-parse-frontmatter`)
- Human-authored harness changes: `feature/<slug>`, `fix/<slug>`,
  `docs/<slug>` (conventional)
- Branch from `main`. There is no `develop` branch in this harness.

---

## Branch Protection

`main` is protected by a GitHub ruleset (Settings → Rules →
Rulesets). Configuration tracked in #21. Enforced rules:

- **No force pushes.** `git push --force` to `main` is rejected.
- **No direct pushes.** All changes go through a PR.
- **No deletions.** `main` cannot be deleted.
- **Linear history.** Squash-merge only (matches existing habit).
- **Required approvals: 0.** Solo-dev mode — the PR gate exists for
  the workflow, not to require a second human reviewer.

Practical implications:

- Never `git push` directly to `main`. Always work on a
  `feature/`, `fix/`, `docs/`, or `runner/issue-<N>-...` branch and
  open a PR.
- The system prompt already forbids shell `git push` for repo state
  changes in favour of the `github__*` tools — branch protection
  enforces this server-side as a backstop.
- If a tool seems blocked by branch protection, surface that to
  Jon rather than working around it.

---

## Sequencing: Parents and Subtasks

Work too large for one issue becomes an **epic**:
- Epic issue has label `epic` and a checklist of child issue links
  (`- [ ] #43 — parse front-matter`).
- Each child is a self-contained `runner-task` issue.
- Children declare dependencies at the top of the body:
  `Depends on: #41`.
- Only mark a child `ready-for-execution` once its dependencies are
  closed.

The runner never works on epics directly — only on leaf issues.

---

## Workflow (end to end)

1. User describes work in chat.
2. Claude Code decomposes into an epic + child issues, or a single
   leaf issue, and files them.
3. Issues land with `runner-task`. The unblocked leaf gets
   `ready-for-execution`.
4. Human runs:
   ```
   runner/.venv/bin/python runner/run_recipe.py \
     --recipe recipes/execute-issue.yaml \
     --params issue_number=<N> \
     --params repo=<owner>/<target_repo> \
     | tee evals/eval-<NN>/session.log
   ```
5. The runner opens a PR via `create_pull_request` (or salvage opens
   one mechanically if the model exits early) and posts a status
   comment on the issue.
6. Human reviews + merges. The PR's `Closes #N` closes the issue.
7. Eval is captured under `evals/eval-NN/`.

---

## Eval Tracking

Each notable run is recorded as `evals/eval-NN/`:
- `issue.md` — verbatim copy of the issue the runner executed
- `result.md` — pass/fail verdict and observations
- `session.log` — raw runner stdout
  (older evals use `goose-session.log` — historical filename, leave
  alone for the audit trail)

Use `scripts/new-eval.sh <N>` to scaffold the directory.

---

## Architecture decisions

Significant architectural decisions live in `docs/adr/` as numbered
Markdown ADRs. The index at `docs/adr/README.md` lists them by number,
title, and status. Reach for the template (`docs/adr/0000-template.md`)
when a decision lands that a future maintainer would reasonably wonder
about — load-bearing choices, hard-to-reverse moves, anything that
shapes future work. Land new ADRs in their own PR or alongside the
work they describe. ADRs are immutable once Accepted: if a decision
changes, write a new ADR that supersedes the old one rather than
editing in place.

---

## Tests & dev workflow

Runner tests live in `tests/` (top-level), driven by pytest. Config in
`pyproject.toml` and `.flake8`.

Common targets — `make help` for the full list:
- `make install-dev` — create `runner/.venv` and install deps
- `make check` — format-check + lint + typecheck (read-only, safe for CI)
- `make format` — apply isort + black
- `make typecheck` — mypy alone (config in `pyproject.toml`'s `[tool.mypy]`)
- `make test` — run pytest
- `make test-cov` — run with coverage, HTML report under `htmlcov/`
- `make ci` — full pipeline: `check` + `test`

Run `make ci` before opening a PR.

---

## What This Repo Is Not

- Not a target project. The runner acts on *other* repos via the
  GitHub MCP-style `github__*` tools — or on this repo itself for
  harness-shakedown evals.
- Not a Goose wrapper. Goose-runtime artefacts were removed once the
  runner reached production-shape (see eval-22, eval-23).
- Not auto-merging. Humans review every PR.
