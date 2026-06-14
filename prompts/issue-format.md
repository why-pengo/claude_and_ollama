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

### 4. Subtasks

A GitHub checklist. Each item must be:

- **One concrete change** — one file, one command, one verification
- **Independently verifiable**
- **Ordered** — earlier items unblock later ones

If you have more than ~8 subtasks, the issue is probably too big.
Split it into an epic + children.

### 5. Acceptance criteria

Bulleted list of **observable outcomes**:

- `pytest tests/test_frontmatter.py` passes
- `note.py` exposes `parse_frontmatter(text) -> dict`
- README has a usage example under "Front-matter"

The runner runs every check before opening a PR.

### 6. Out of scope

Explicit list of things the runner should NOT do. Closes the loop on
scope creep. Items that surface during execution go in the PR's
`## Follow-ups` section, not into the current PR.
