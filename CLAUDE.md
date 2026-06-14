# claude_and_goose — Claude Code Instructions

This repo is an evaluation harness for a two-agent code workflow:

- **Claude Code** is the planner. It reads context, decomposes work,
  and authors structured GitHub Issues.
- **Goose** (open-source agent, running a local Ollama model on
  `bazzite.local`) is the executor. It reads one issue at a time,
  executes its subtask checklist, comments with results, and opens
  a PR.

This repo holds recipes, prompts, and eval results. It is **not the
target project** — it is the rig that drives Goose against other repos
(and against itself, for shakedown evals).

---

## Your Role in This Repo (Claude Code)

Your default job here is to **author or refine GitHub Issues that
Goose can execute**, not to write the implementation yourself. Goose
owns execution; you own decomposition, sequencing, and review.

When the user asks for new work:
1. Decide whether it's one leaf issue or an epic with children.
2. Draft issues against the format in `prompts/issue-format.md`.
3. Apply labels (see below).
4. Only mark `ready-for-execution` once all dependencies are closed.

Exceptions: harness-level changes (recipes, prompts, `goose.yaml`,
this file, scripts) are written by Claude Code directly — Goose
operates the harness, it doesn't edit it.

---

## GitHub Issue Format

Canonical spec lives in `prompts/issue-format.md`. Required sections:

1. **Title** — imperative, conventional-commit prefix
   (e.g. `feat: parse YAML front-matter in note files`)
2. **Goal** — one paragraph; what outcome counts as done
3. **Context** — links to related issues, prior decisions, files
   Goose must read first
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
| `goose-task`           | Eligible for Goose execution. Must conform to the issue format. |
| `ready-for-execution`  | All prereqs merged, context resolved, Goose can pick it up. |
| `blocked`              | Waiting on another issue, decision, or external input. Body must state what's blocking. |
| `done`                 | Closed by a merged PR. Applied by the closing PR, never manually. |
| `epic`                 | Parent issue tracking a body of work via a checklist of child issue links. |

---

## Branch Naming

- Goose-executed work: `goose/issue-<N>-<short-slug>`
  (e.g. `goose/issue-42-parse-frontmatter`)
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
  `feature/`, `fix/`, `docs/`, or `goose/issue-<N>-...` branch and
  open a PR.
- The Goose system prompt already forbids shell `git push` for
  repo state changes in favour of MCP tools — branch protection
  enforces this server-side as a backstop.
- If a tool seems blocked by branch protection, surface that to
  Jon rather than working around it.

---

## Sequencing: Parents and Subtasks

Work too large for one issue becomes an **epic**:
- Epic issue has label `epic` and a checklist of child issue links
  (`- [ ] #43 — parse front-matter`).
- Each child is a self-contained `goose-task` issue.
- Children declare dependencies at the top of the body:
  `Depends on: #41`.
- Only mark a child `ready-for-execution` once its dependencies are
  closed.

Goose never works on epics directly — only on leaf issues.

---

## Workflow (end to end)

1. User describes work in chat.
2. Claude Code decomposes into an epic + child issues, or a single
   leaf issue, and files them.
3. Issues land with `goose-task`. The unblocked leaf gets
   `ready-for-execution`.
4. Human runs:
   ```
   goose run --recipe recipes/execute-issue.yaml \
     --params issue_number=<N> \
     | tee evals/eval-<NN>/goose-session.log
   ```
5. Goose comments on the issue and opens a PR (if files changed).
6. Human reviews + merges. The PR's `Closes #N` closes the issue.
7. Eval is captured under `evals/eval-NN/`.

---

## Eval Tracking

Each notable run is recorded as `evals/eval-NN/`:
- `issue.md` — verbatim copy of the issue Goose executed
- `result.md` — pass/fail verdict and observations
- `goose-session.log` — raw Goose stdout

Use `scripts/new-eval.sh <N>` to scaffold the directory.

---

## Tests & dev workflow

Runner tests live in `tests/` (top-level), driven by pytest. Config in
`pyproject.toml` and `.flake8`.

Common targets — `make help` for the full list:
- `make install-dev` — create `runner/.venv` and install deps
- `make check` — format-check + lint (read-only, safe for CI)
- `make format` — apply isort + black
- `make test` — run pytest
- `make test-cov` — run with coverage, HTML report under `htmlcov/`
- `make ci` — full pipeline: `check` + `test`

Run `make ci` before opening a PR.

---

## What This Repo Is Not

- Not a target project. Goose recipes act on *other* repos (cloned
  via the GitHub MCP extension) — or on this repo itself for
  harness-shakedown evals.
- Not a Goose fork or wrapper. Just config + recipes + tracking.
- Not auto-merging. Humans review every PR.
