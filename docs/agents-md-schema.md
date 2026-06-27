# AGENTS.md schema

This document specifies the structure a target-repo `AGENTS.md` must conform to
so the `claude_and_ollama` runner can mechanically parse code-quality rules and
verification commands out of it. Authors of a target-repo `AGENTS.md` should be
able to write a conforming file using this document alone — no need to read the
runner source.

The runner's verification gate (epic
[#111](https://github.com/why-pengo/claude_and_ollama/issues/111)) reads
verification commands out of the root `AGENTS.md` and runs them after every
commit. Conventions are surfaced to the executing model as system guidance. A
target repo with no `AGENTS.md` — or one whose `AGENTS.md` doesn't conform —
is rejected at session start.

This schema supersedes the soft AGENTS.md handling described in
`recipes/execute-issue.yaml` Step 0, and replaces the per-task `Q2` axis of
`docs/pr-quality-rubric.md` with an in-flow gate.

## Location and composition

- **Root `AGENTS.md`** lives at target-repo root. Required.
- **Nested `AGENTS.md`** files (e.g. `backend/AGENTS.md`, `frontend/AGENTS.md`)
  live one level deep in subdirectories. Optional. Used to scope area-specific
  conventions away from the root file when the project is large enough to
  warrant it.
- The runner parses **root only** for verification commands that get gated.
  Nested files are read by the executing model when the issue touches that
  area (per the recipe's existing Step 0 nudge), so their `## Conventions`
  blocks are still load-bearing — they're just not part of the gate's command
  list. Authors who want area-specific commands gated should expose them
  through a root `make` target.
- Nested files carry their own independent `## Verification commands` and
  `## Conventions` blocks. They are not merged with the root file at parse
  time; composition is the model's job during Step 0, not the runner's.

## Format: YAML fenced blocks under markdown headings

Both required sections (`## Verification commands`, `## Conventions`) carry
their structured content inside a YAML fenced code block immediately under
the heading. The markdown around the YAML is for humans; the runner parses
only the fenced YAML.

````markdown
## Verification commands

```yaml
- name: check
  command: make check
- name: test
  command: make test
```

Free-form prose around the block is fine — explain *why* a command is on the
list, link to relevant tickets, document edge cases. The runner ignores it.
````

### Why YAML, not freeform markdown bullets

The rejected alternative was a freeform markdown bullet list, e.g.:

```markdown
## Verification commands

- `make check` — format + lint
- `make test` — backend pytest, runs inside Docker
```

Pretty to read, but the parser has to decide which backtick group is the
command name vs. the human description, tolerate em-dashes vs. en-dashes
vs. colons, and silently fail when an author writes the list slightly off.
The YAML form trades a small amount of human friendliness for a parser
that's bulletproof and fails loudly on malformed input — which is the
behavior the runner gate needs.

## Required sections

### `## Verification commands`

A YAML list of objects. Each object has exactly two string keys:

| Key | Type | Description |
|---|---|---|
| `name` | string | Short identifier the runner uses to report results (e.g. `check`, `test`, `ci`). Required. Must be unique within the file. |
| `command` | string | The shell command to invoke from the repo root. Required. Must be non-empty. |

The runner executes each command in order in the user-provided workspace
after every commit. A non-zero exit on any command means the gate is red
and the failure feeds back to the model. See "Coverage horizon" below for
guidance on what to list.

### `## Conventions`

A YAML list of strings. Each string is one convention sentence the runner
surfaces verbatim to the executing model as system guidance.

```yaml
- Use SQLAlchemy 2.0 async style (Mapped[X], mapped_column, AsyncSession, select()).
- All timestamps are timezone-aware UTC ISO strings stored in TEXT columns.
- Backend line length is 88 (Black default), not the global 100.
```

Conventions should be terse and imperative — they're prompt-substrate, not
prose. Deeper explanations, code examples, and "what not to do" walkthroughs
belong in supplementary markdown sections below the YAML block; the model
reads the full file via the recipe's existing Step 0 fetch.

## Optional sections

Any other markdown the author wants to include is fine. The runner ignores
unknown top-level headings entirely; they exist for the model's benefit
during Step 0 and for human readers. Typical optional sections include
project overview, repo layout, "where to start when adding a feature,"
known pitfalls, and references to ADRs or design docs.

## Parser failure modes

The runner bails loudly — never silently — on each of the following:

| Failure | Runner behavior |
|---|---|
| Root `AGENTS.md` missing | Reject the session at start with a clear error pointing at this spec. |
| Required section heading missing (`## Verification commands` or `## Conventions`) | Reject the session with the missing heading named. |
| YAML fenced block missing under a required heading | Reject with the offending heading named. |
| YAML parse error | Reject with the YAML library's error message verbatim. |
| `## Verification commands` is not a list, or an entry is missing `name`/`command`, or `name` is non-unique within the file | Reject with the offending entry described. |
| `## Conventions` is not a list of strings | Reject with the offending entry described. |
| Unknown top-level YAML key inside a required section's block | Reject — guards against typos that would silently drop content. |

The bias is intentional: a malformed `AGENTS.md` is more dangerous than a
missing one, because the model can fabricate conventions to fill the void.
Failing loudly forces the author to fix the file before the runner does
anything that touches the repo.

## Coverage horizon

**The gate's reach equals the verification commands listed.** If your
`## Verification commands` block is just `make check` and `make test`,
the gate catches lint failures and runtime test failures — and nothing
else. It does not catch schema/models drift, contract-vs-implementation
drift, frontend type errors, build errors, or any failure mode whose
detection isn't wired into one of those commands.

This is a deliberate constraint. The runner is not in the business of
guessing what your project needs gated; the author of `AGENTS.md` owns
the gate's reach. By-shape guidance:

| Project shape | Verification commands typically include |
|---|---|
| Backend service (DB-backed) | `make check`, `make test`, migration drift check (e.g. `alembic check`), contract/schema check if the API has a typed contract |
| Frontend app | typecheck, lint, unit tests, build |
| CLI / library | lint, tests, build |
| Mixed-stack monorepo | The above, wrapped in a root `make ci` that aggregates them |

If the gate doesn't catch a failure mode you care about, the fix is to
add a target to the project's `Makefile` (or equivalent) and list it
here — not to change the runner.

The first conforming `AGENTS.md` is
[`why-pengo/health_track`'s root + backend + frontend
files](https://github.com/why-pengo/health_track/issues/94). Read that
PR when it lands as a worked example.

## Relationship to `.claude/` and `CLAUDE.md`

These three files coexist in many target repos and serve different
audiences:

| File | Audience | Owned by |
|---|---|---|
| `AGENTS.md` (this schema) | Any agent, including this harness's runner. Code-quality + verification spec. | Anyone authoring runner-executable issues |
| `CLAUDE.md` (often inside `.claude/`) | Claude Code specifically. Workflow rules, slash-command conventions, personal preferences. | The human dev driving Claude Code |
| `.claude/` (folder) | Claude Code config (hooks, settings, command files). | The human dev's local config |

The runner **only ever reads `AGENTS.md`**. It never reads `.claude/`
or `CLAUDE.md`. If a target repo has both `AGENTS.md` and `CLAUDE.md`,
the recommended pattern is: `CLAUDE.md` references `AGENTS.md` for
code-quality content rather than duplicating it (one-line pointer:
"See `AGENTS.md` for conventions"). That way the runner and Claude
Code see the same source of truth and the two files don't drift.

Authors writing a new `AGENTS.md` in a repo that already has a
`CLAUDE.md` should compress `CLAUDE.md` to its workflow-only content
and move conventions / verification rules into the new `AGENTS.md`.

## Reference example

A complete root-level `AGENTS.md` for a hypothetical backend service:

````markdown
# AGENTS.md — example-service

This file is the canonical agent-facing guide for working on this repo.
The `claude_and_ollama` runner parses the YAML blocks below; humans and
Claude Code read the full file.

## Verification commands

```yaml
- name: check
  command: make check
- name: test
  command: make test
- name: migrations-check
  command: make migrations-check
```

`make check` runs format + lint. `make test` runs the backend pytest
suite inside Docker. `make migrations-check` runs `alembic check` to
detect model/migration drift.

## Conventions

```yaml
- Use SQLAlchemy 2.0 async style (Mapped[X], mapped_column, AsyncSession, select()).
- Timestamps are timezone-aware UTC ISO strings stored in TEXT columns.
- Single-row config tables use the race-safe seed pattern (IntegrityError + rollback).
- Backend line length is 88 (Black default).
- Coverage gate is 85% — see backend/pyproject.toml.
```

## Repo layout

(…free-form markdown; runner ignores this section…)

## Where to start when adding a feature

(…free-form markdown…)
````

And a nested `backend/AGENTS.md` carrying area-specific overrides:

````markdown
# backend/AGENTS.md — example-service backend

## Verification commands

```yaml
- name: check
  command: make check
- name: test
  command: make test
- name: ci
  command: make ci
```

## Conventions

```yaml
- All async session work goes through the AsyncSession dependency in app/db.py.
- Pytest fixtures live in conftest.py; don't re-implement per-test.
- Top-level model imports go in conftest.py so Base.metadata.create_all sees them.
```

## SQLAlchemy 2.0 walkthrough

(…long-form prose + code examples; runner ignores…)
````
