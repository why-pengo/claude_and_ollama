# Issue Format for Runner-Executable Tasks

Every issue tagged `runner-task` must follow this template. Issues
that don't conform should be rejected by the runner with a request
for the missing pieces.

---

## Title

Imperative, scoped, conventional-commit prefix.

- ✅ `feat: parse YAML front-matter in note files`
- ✅ `fix: handle empty config gracefully`
- ❌ `Add parsing for the new format please`
- ❌ `[BUG] something broken with notes`

---

## Body sections (in order)

### 1. Depends on (optional, top of body)

If this issue depends on others, the very first line of the body is:

```
Depends on: #41, #42
```

Don't apply `ready-for-execution` until every dependency is closed.

### 2. Goal

One paragraph. State the **outcome** that counts as done. No
implementation details — those belong in subtasks.

### 3. Context

Anything the runner can't infer from the codebase:

- Links to related issues / prior PRs
- File paths to read before starting
- Decisions already made (and why)
- External docs

Keep human-facing rationale out of runner-task bodies. "Decisions
(locked)" style sections belong in the epic or an issue comment; the
body stays Goal / Context / Subtasks / Acceptance criteria /
Out of scope. Every word of body is prompt-token cost the model pays
on every turn.

### 4. Subtasks

A GitHub checklist. Each item must be:

- **One concrete change** — one file, one command, one verification
- **Independently verifiable**
- **Ordered** — earlier items unblock later ones
- **Named by exact file path(s)** — the runner's model cannot
  search; it fetches only the paths it is given.
  `backend/app/routers/hydration.py`, not "the hydration router".

**Sizing — hard ceilings** (calibrated on eval-35..41; above any
one of them, split into an epic + children):

- **≤ 5 subtasks**
- **≤ 5 files touched**
- **body ≤ 500 words**

The unit of a runner-task issue is **one gate-visible increment**:
while the issue is incomplete, at least one AGENTS.md verification
command must fail. Concretely, **tests land in the same issue as the
behavior they verify** — an implementation issue without its tests
lets the model open an honest-but-partial PR on a green gate
(eval-41, health_track#110).

**Ordering:** the model drops trailing subtasks (eval-35: all three
PASS runs silently omitted the final wiring step). Where dependency
order allows, order by importance — registration/wiring before
polish; the subtask that would hurt most if dropped goes as early as
dependencies permit.

### 5. Acceptance criteria

Bulleted list of **observable outcomes**, each checkable by a
command the verification gate runs (the target repo's `AGENTS.md`
`## Verification commands` — see `docs/agents-md-schema.md`):

- `pytest tests/test_frontmatter.py` passes
- `make check` stays clean

The gate runs the AGENTS.md commands after every commit the runner
makes and blocks PR-open while any of them fails. Criteria beyond
the gate's reach (README wording, an exposed function signature) are
reviewed by the human on the PR — keep them few and observable.

### 6. Out of scope

Explicit list of things the runner should NOT do. Closes the loop on
scope creep. Items that surface during execution go in the PR's
`## Follow-ups` section, not into the current PR.
