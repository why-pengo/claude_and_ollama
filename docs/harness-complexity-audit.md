# Harness complexity audit

Reference artifact for the discussion that emerged from eval-17 (qwen3.6
reliability regression) and eval-18 (devstral failing under harness load
despite curl-probe success). The cuts proposed here landed in commit
6f1e55a; the eval-19 series tested them; the Step 3 callout was restored
in 9f6631d after over-cut evidence. Keep this doc as the record of *why*
those edits happened.

## TL;DR

Two prompt surfaces are loaded into every executor turn:

- `prompts/goose-system.md` — 198 lines
- `recipes/execute-issue.yaml` (the `prompt:` block) — ~106 lines of templated
  instructions inside the 153-line YAML

Total ~304 lines of layered guidance, plus tool declarations from the
github + developer + shell extensions, plus AGENTS.md fetches in Step 0
(now ~770 lines of content for `health_track`). Every section has a
defensible origin story, mostly anchored to a past eval failure. But the
accumulated text has substantial duplication, several stale rationales,
and a few sections whose only justification is "we added this last week to
address a symptom."

**Proposed targets**: ~120 lines for `goose-system.md`, ~70 for the recipe
prompt body. ~40% reduction in total prompt mass. No load-bearing rule
removed — every cut is either duplication or pre-existing bloat.

---

## The duplication map

Things said in *both* the system prompt and the recipe:

| Rule | system prompt | recipe |
|---|---|---|
| No force-push | §What you don't do | `# Rules` |
| No `--no-verify` | §What you don't do | `# Rules` |
| Never close issue directly | §What you don't do | `# Rules` |
| Don't edit base branch directly | implied (§Working dir, §What you don't do) | `# Rules` |
| One issue, one PR | §Operating principles | `# Rules` |
| Conventional-commit prefix on commits | §Operating principles | Step 3 |
| Verify acceptance criteria before PR | §Operating principles | Step 4 |
| Don't fold scope into PR | §What you don't do | (implicit in `Out of scope`) |
| `push_files` vs `developer.write` | §Every turn is a tool call (added today) | Step 3 callout (PR #51) |
| Create PR after last push (Step 5 mandate) | §Every turn is a tool call (added today) | Step 5 ("don't ask, don't defer") |

Each row is **the same rule said twice** in different words, in two
places the model has to reconcile. For an instruction-following weak
model (devstral, qwen2.5-coder, even qwen3.6 on a bad day), duplicate
statements with slightly different framings *increase* cognitive load
rather than reinforce the rule.

**Principle**: each rule lives in exactly one place. Either system
prompt or recipe, not both. The recipe is per-task; the system prompt is
per-session. Load-bearing operating rules go in the system prompt and
the recipe doesn't restate them.

---

## Per-section assessment of `goose-system.md`

### §What you do (lines 6-12) — 7 lines
Status: keep, slightly tighten.
Notes: This is the role description. The 4 bullets duplicate the recipe's
Steps 1-6 at a high level. Could collapse to 3 lines: "Read the issue,
execute its subtask checklist in order, open a PR with `Closes #N` if
files changed."

### §Every turn is a tool call (lines 14-51) — 38 lines
Status: keep, but tighten by 30%.
Notes: Added today (1491751). The "Failure modes to avoid" subsection
lists 4 named anti-patterns with 2-3 lines each. Most of the value comes
from the named pattern, not the explanation. Can tighten the patterns to
one-line tag descriptions. The "tools available" subsection duplicates
the tool descriptions Goose injects automatically — could drop entirely.

**Target**: ~22 lines, focused on the named anti-patterns.

### §What you don't do (lines 53-87) — 35 lines
Status: keep, **tighten substantially**.
Notes: Load-bearing rules (no clone, no push to base, no force-push, no
skipping hooks, no persisting secrets, no editing dotfiles) buried in
verbose explanations. Each rule averages 4-5 lines including rationale.
For a system prompt, a 1-line rule is enough — rationale is dispensable
once the rule is established.

Examples of tightening:
- "Don't persist secrets to disk" currently 6 lines (with examples).
  Can be: "Don't write secrets (tokens, API keys, SSH keys) to any file.
  They live in env or keyring only."
- "Don't touch shell dotfiles" currently 5 lines with 7 enumerated
  paths. Can be: "Don't write to shell dotfiles or `~/.config/` or
  `~/.ssh/`. If a tool seems to need it, stop and comment."
- "Never run `git clone`" currently 5 lines with anti-pattern example.
  Can be: "Never `git clone`. The repo is mounted at `/work`. Scratch
  space goes under `/tmp`."

Also drop "Don't expand the PR to include follow-up work" — this is
covered by recipe Step 5's mandated PR shape (which has a Follow-ups
section explicitly).

**Target**: ~16 lines.

### §Repo changes go through MCP (lines 89-109) — 21 lines
Status: keep, tighten.
Notes: This is load-bearing (eval-13 path-discipline failure). But the
3 sub-bullets (Files / Branches / PRs) average 6 lines each with prose
about anti-patterns. Each can be 3 lines.

Also: the §Every turn is a tool call I added today partly overlaps
("Land every change via the github extension"). Pick one home. I'd
move the push_files vs developer.write callout *out* of §Every turn
and *into* §Repo changes through MCP. Then drop the duplication in
recipe Step 3.

**Target**: ~12 lines.

### §Adding new files — match the neighbors (lines 111-131) — 21 lines
Status: keep, tighten.
Notes: Load-bearing (eval-08, eval-11 path slips). The current prose
has 3 specific check examples then a 4-line summary paragraph. The
examples are useful; the summary paragraph can go.

**Target**: ~14 lines.

### §Issue numbers and PR numbers are different namespaces (lines 133-147) — 15 lines
Status: keep, tighten by 30%.
Notes: Real MCP gotcha. But the 4-line "issue_read takes issue,
update_pull_request takes PR" preamble can collapse to one line.

**Target**: ~10 lines.

### §The working directory (lines 149-156) — 8 lines
Status: **drop**, merge essential bit into §What you don't do's "no
clone" rule.
Notes: The 8 lines say "/work is your repo, don't make a parallel one,
scratch goes to /tmp." All three sub-points are already implied by the
"no clone" rule. The 8 lines exist to explicitly re-state what "no
clone" implies. Cut.

**Target**: 0 lines (merged into §What you don't do).

### §Operating principles (lines 158-170) — 13 lines
Status: **mostly drop**.
Notes: 5 bullets, all duplicated elsewhere:
- "Verify as you go" — recipe Step 4
- "Stop on failure" — §When you're stuck
- "Small, labelled commits" — recipe Step 3
- "One issue, one PR" — §What you don't do (don't expand scope)
- "No silent skips" — §Honest verification

Drop the entire section. None of these are load-bearing here that aren't
load-bearing elsewhere.

**Target**: 0 lines.

### §Honest verification (lines 172-188) — 17 lines
Status: keep, tighten.
Notes: Load-bearing (eval-08 had fabricated verification). But the
prose is verbose — repeats the "don't invent" rule twice. Can be 8
lines covering: "If a verification step couldn't run, say so plainly
in the PR's `## Verification` section. Don't invent reasons. The same
applies to acceptance criteria — don't tick a box you didn't verify."

**Target**: ~8 lines.

### §When you're stuck (lines 190-198) — 9 lines
Status: keep as-is.
Notes: Tight and clear. No changes.

**Target**: 9 lines.

---

## Per-section assessment of recipe prompt body

### Preamble (lines 43-55) — 13 lines
Status: keep, slight tighten.
Notes: Issue number + repo + base_branch reminder. Today's patch added
"Your first tool call is Step 0" which is load-bearing. The
"integration branch" paragraph is 4 lines for one fact — could be 2.

**Target**: ~10 lines.

### # Step 0 — Load target-repo guidance (lines 57-67) — 11 lines
Status: **revisit substantively**.
Notes: Currently fetches 4 AGENTS.md paths unconditionally — `AGENTS.md`,
`backend/AGENTS.md`, `frontend/AGENTS.md`, `docs/AGENTS.md`. For
`health_track` that's now ~770 lines of content injected before the
model has even read the issue. Eval-17 series strongly suggests this
front-loaded context burden contributes to the regression.

Options:
- A: Drop frontend + docs probes by default. Most current targets are
  backend tasks; the unconditional 4-fetch was speculative.
- B: Fetch only the root `AGENTS.md` always; let it point to area-
  specific files. This requires the root file to have a "for backend
  work, read backend/AGENTS.md" instruction, which the current root
  AGENTS.md already does.
- C: Read the issue first (Step 1), parse for keywords (`backend`,
  `frontend`, `docs`), then conditionally fetch matching AGENTS.md.

**I recommend B** — smallest behaviour change, lets the executor
decide what's relevant. The current root AGENTS.md already has the
pointer structure.

**Target**: ~6 lines, one fetch instead of four.

### # Step 1 — Read the issue (lines 71-78) — 8 lines
Status: keep, tighten.
Notes: Standard. The "STOP if missing required section" rule could move
to issue-format.md and be cited rather than restated.

**Target**: ~5 lines.

### # Step 2 — Branch (lines 80-83) — 4 lines
Status: keep as-is.
**Target**: 4 lines.

### # Step 3 — Execute subtasks in order (lines 85-112) — 28 lines
Status: keep, drop callout.
Notes: The 9-line `push_files` vs `developer.write` callout (PR #51) is
the system prompt's §Repo changes through MCP rule, restated. Drop it
from the recipe — keep the rule in the one canonical place. The "for
each checklist item" walk is 6 lines and could be 4.

**Target**: ~14 lines.

### # Step 4 — Verify acceptance criteria (lines 114-116) — 3 lines
Status: keep as-is.
**Target**: 3 lines.

### # Step 5 — Open the PR (lines 118-135) — 18 lines
Status: keep, tighten.
Notes: The "don't ask, don't defer, don't decide whether" sentence is
covered by the system prompt's §Every turn is a tool call (added today).
Body shape (title / Closes / Summary / Verification / Subtasks /
Follow-ups) is load-bearing per eval-10/13 findings.

**Target**: ~12 lines.

### # Step 6 — Comment on the issue (lines 137-142) — 6 lines
Status: keep, tighten.
Notes: 6 lines for one action. Could be 4.

**Target**: ~4 lines.

### # Rules (lines 148-153) — 6 lines
Status: **drop entirely**.
Notes: All 4 bullets duplicate system prompt rules. Cut.

**Target**: 0 lines.

---

## The reckoning

| Surface | Current | Proposed | Cut |
|---|---|---|---|
| goose-system.md | 198 | ~91 | -107 (54%) |
| recipe prompt body | 106 | ~58 | -48 (45%) |
| Step 0 AGENTS.md fetches | 4 paths, ~770 lines of content | 1 path, ~180 lines of content | -77% |
| **Total prompt burden** | ~304 + ~770 = ~1074 lines fetched before Step 1 | ~149 + ~180 = ~329 lines | **-70%** |

## What stays load-bearing

- "Every turn is a tool call" (consolidated with anti-patterns)
- "No clone, no force-push, no skip hooks, no secrets to disk, no
  dotfiles" (consolidated into one tight What-You-Don't-Do)
- "Repo changes through MCP" with `push_files` callout (one home, not
  two)
- "Match neighbors" path discipline
- "Issue vs PR number namespaces" (the MCP gotcha)
- "Honest verification" (eval-08 fabrication prevention)
- "When you're stuck" protocol
- Recipe Steps 0-6 (with tightened bodies)
- The 4 named anti-patterns from today's §Every turn is a tool call
  ("delegate to sub-agent", "ready to...", "I don't have capability",
  "summary-then-stop")

## What I'm not sure about

- Should the §Adding new files (path discipline) section live in the
  system prompt or in AGENTS.md per target repo? Argument for moving
  to AGENTS.md: it's target-repo-specific. Argument for keeping in
  system prompt: target repos without AGENTS.md still need the rule.
  Probably keep in system prompt for now; move when every target has
  AGENTS.md.

- Step 0 — the B option (one root AGENTS.md fetch) assumes the root
  AGENTS.md does the pointing. `health_track`'s root AGENTS.md already
  does; future targets might not. We'd need to document that
  convention in `prompts/issue-format.md` or wherever AGENTS.md
  authoring guidance lives.

- Whether the "Every turn is a tool call" section I added today
  should survive complexity reduction. Arguments both ways: (a) it's
  fresh and untested in evals, may be premature; (b) it's the
  prescription for the eval-17 failure mode and removing it would
  retest the same regression. I'd keep it, but in a tightened form.

## Testing plan

If we agree on this audit:

1. Apply the cuts in a single commit on the `feature/tool-call-discipline`
   branch (which already has today's prompt patch).
2. Run eval-19 with **qwen3.6** (the model we know works at-its-best)
   against `health_track#51` with the slimmed harness, k-of-3. If it
   completes 3-of-3, the complexity-reduction hypothesis is validated.
3. Run eval-20 with **devstral** against the same, k-of-3. If it
   completes any of them, we've broken the qwen3.6-uniqueness barrier
   for #47 by harness simplification alone — no runtime work needed.
4. Bundle the prompt patch + audit cuts + eval-19/20 evidence into one
   PR. The reframing is "we made the harness too heavy; here's the
   cut + the data showing it helped."

If eval-19 *doesn't* complete 3-of-3 even with the slimmed harness, the
hypothesis is partially refuted and we revisit. The data wouldn't be
wasted — failure with a 70% lighter harness rules out "context-pressure
in the system prompt is the cause" cleanly. Then the search moves on
to (a) Goose session-loop bugs, (b) per-recipe-step input/output limits,
or (c) genuine model capability cliffs.
