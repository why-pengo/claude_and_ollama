# eval-05 result

Same sandbox task (#24), same recipe, same container — **five back-to-back runs**, each with a distinct failure mode. Devstral is unsuitable for this harness regardless of context size, SYSTEM prompt, or warmth.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `--params issue_number=24`
- Models exercised: `devstral:latest` (runs 1–2) and `devstral-goose:latest` — a custom Modelfile built over the same base blob with two variants (runs 3–4 used scrubbed SYSTEM, run 5 used the original OpenHands SYSTEM with `num_ctx 32768`)
- Config: `OLLAMA_STREAM_TIMEOUT: 60` (landed via PR #23)
- Container: `claude-and-goose-runtime` (Goose 1.35.0 + github-mcp-server 1.0.5)

## Summary table

| Run | Modelfile delta | Warm? | Failure mode |
|---|---|---|---|
| 1 | base `devstral:latest` | cold | Zero tools. Fabricated a fictitious issue ("Fix grammar in README.md") + fake Goose "silent mode" affordance + complete fake workflow narrative |
| 2 | base `devstral:latest` | warm | Real tool calls, but pushed file with `ex  t 1` (mangled `exit 1`) + stray reference line, wrong branch prefix (`feature/` vs `goose/`), PR body missing `Closes #24`, step 6 skipped |
| 3 | `num_ctx 32768` + SYSTEM `" "` | cold | Immediate stop after one fabricated `<info-msg>` block. Zero tools. |
| 4 | `num_ctx 32768` + SYSTEM `" "` | warm | Tool call emitted as raw XML inside `content`. Ollama parser didn't route it into structured `tool_calls`, so Goose saw nothing. Zero real tools. |
| 5 | `num_ctx 32768` + original OpenHands SYSTEM | cold | Hallucinated an entire fake GitHub UI rendering — fictitious `dependabot[bot]` assignee, fake "Remove dependency on langchain-openai" body, fabricated HTML with `<form>` tags and `authenticity_token` values. Zero tools. |

Side effects on GitHub: only run 2 produced real artifacts (broken branch `feature/issue-24-add-mcp-check-script` and PR #26 — closed without merge as eval detritus).

## What this rules out

- **Cold-load timing** (PR #23's hypothesis): runs 2 and 4 had a warm model and still failed. Warm-vs-cold changed *which* failure happened, not whether one happened.
- **Context size starvation**: runs 3–5 all had `num_ctx` explicitly raised to 32768. Failure persisted.
- **OpenHands SYSTEM conflict**: scrubbing the OpenHands SYSTEM (runs 3, 4) changed the failure mode (immediate stop or XML-text-call) but didn't make the model produce a clean recipe execution. Restoring the OpenHands SYSTEM (run 5) brought back the hallucination behavior.
- **`OLLAMA_STREAM_TIMEOUT`**: 60s was in effect for every run.

No single variable changes "failure" to "success." The model behavior is incoherent on this recipe across the tested config space.

## What's actually happening

Across the five runs the failures span three categories:

1. **Hallucinated workflows** (runs 1, 5) — the model doesn't call tools at all but produces confident structured narration as if it had. Includes fabricated issue bodies, fake UI affordances, and fake HTML.
2. **Format misalignment** (run 4) — the model emits a tool call, but in a shape (XML in `content`) that Ollama's parser doesn't route into `tool_calls`. Variant of qwen2.5-coder's bake-off failure.
3. **Real but broken execution** (run 2) — the model calls tools, but corrupts content (`ex  t 1`), ignores conventions (branch prefix), and skips required steps. The kind of output that would get caught by review but only after a human had to clean up the half-applied state.

Mode 1 is the most dangerous: a skim of the session log makes it look like work happened. Mode 3 is the most insidious: real GitHub artifacts get created in inconsistent states.

## Verdict

Verdict: **FAIL.** Devstral is unsuitable as a Goose executor in this harness. We've exercised five distinct config × warmth combinations and produced zero clean executions. Continued tuning is unlikely to be productive — the failure pattern is too diverse to point at one fixable variable.

## Implications for PR #23 / eval-04 framing

The PR #23 framing — "cold-load timeout flake, mitigation in goose.yaml fixes it" — is disproven. The `OLLAMA_STREAM_TIMEOUT: 60` setting is still reasonable defensive coding (it's a no-op for fast models and mitigates a real class of slow-first-chunk failure) but it's not the reason devstral fails. The eval-04 `result.md` / `scores.md` annotations need a follow-up rewrite that says: "devstral failed for reasons we couldn't isolate; the 6/15 score is meaningless because the model never reliably executes the recipe."

## Cleanup needed

- PR #26 (devstral run-2 detritus) — already closed.
- Branch `feature/issue-24-add-mcp-check-script` — broken artifact from run 2; safe to delete after merging this writeup.
- `devstral-goose:latest` model on `bazzite.local` — can be deleted; it served its purpose as a test variant.
- Issue #24 — task itself is valid; could be retired as "eval-05 sandbox" or re-run with `qwen3.6:latest` to confirm the task description works for an executor that can follow recipes.

## Next time

- Don't treat session-log narration as evidence of work. Always verify against `gh pr list`, `gh issue view --comments`, and remote branches.
- Add a post-run smoke check that requires at least one `▸ ` line AND at least one real side effect (branch / PR / comment) before claiming the executor "did something."
- Stop trying to make devstral work in this harness. Five independent failure modes is enough evidence.

## Run 1 — cold model

Session log: `goose-session.log`. Model state: cold (qwen2.5-coder curl ~10 min prior evicted devstral from VRAM).

**Devstral made zero tool calls and hallucinated the entire workflow.**

| Expected side effect | Actually happened |
|---|---|
| `▸ issue_read github` tool call | None in log |
| Branch `goose/issue-24-...` created | No `goose/` branches on remote |
| File `scripts/check-mcp.sh` pushed | Not in tree |
| PR opened with `Closes #24` | No new PR |
| Comment posted on issue #24 | No comments on #24 |

The session log narrates a complete successful workflow despite none of it happening:

- **Fabricated issue body** — log claims #24 was "Fix grammar in README.md" with subtasks about Python 3 text. Issue #24 is about adding `scripts/check-mcp.sh`; nothing matches.
- **Fabricated Goose UI affordance** — `<sub>(You will not see output here because I'm using silent mode for tool calls.)</sub>`. Goose has no "silent mode"; real tool markers are `▸ <name>`.
- **Fabricated workflow** — branch created, file edited, PR opened, comment posted. All false.
- **"✅ Task Completed"** sign-off.

## Run 2 — warm model

Session log: `goose-session-run2.log`. Model state: warm (run 1 had loaded devstral into VRAM ~30s prior).

**Devstral called tools this time** — `issue_read`, `list_branches`, `create_branch`, `get_file_contents`, `push_files`, `create_pull_request` — and produced real side effects on GitHub. But every artifact is broken in some way:

| Required behaviour | What devstral did |
|---|---|
| Branch named `goose/issue-24-<slug>` | Created `feature/issue-24-add-mcp-check-script` — wrong prefix (recipe + system prompt both require `goose/`) |
| Script per spec (`set -euo pipefail`, `command -v`, `--version`) | Pushed file with **broken syntax**: stray `OLLAMA_HOST=...` line carried over from reference script, `exit 1` mangled into `ex  t 1` (whitespace mid-keyword) |
| PR with `Closes #24` | PR #26 opened, body has no `Closes #24` line. Also typos ("the/github-mcp-server"). |
| Verification subtasks checked truthfully | Body claims "[x] Checked that the script uses set -euo pipefail" — that's true, but it doesn't check the broken `exit` line |
| Comment on #24 | Step 6 skipped — no comment posted |

If a human reviewer ran the script as merged, it would fail with `command not found: ex` (the mangled `exit`). The PR is unmergeable as-is.

## Verdict

Verdict: **FAIL (both runs).**

Two different failure modes on consecutive runs of the same input:

- Run 1: silent hallucination — looks successful in log, nothing actually happened.
- Run 2: real tool calls — but broken file content, wrong branch convention, missing required PR sections.

Neither produced a mergeable artifact. The model is unsuitable as a Goose executor in this harness regardless of timeout tuning.

## Implications for #23 / eval-04 framing

The `OLLAMA_STREAM_TIMEOUT: 60` mitigation from PR #23 was harmless but didn't fix anything for devstral. Run 1 ran a long narration without any timeout firing, and run 2's tool calls would have worked at any timeout because the model was warm. The "cold-load flake" diagnosis from PR #23 was wrong; the real failure mode is "devstral can't reliably execute structured multi-step recipes — sometimes it doesn't call tools at all, sometimes it does but mangles the content."

The eval-04 `result.md` / `scores.md` annotations should be revised to drop the "not a structural problem" claim.

## Cleanup needed

- PR #26 (devstral's broken submission) — close without merging.
- Branch `feature/issue-24-add-mcp-check-script` — delete after closing PR.
- Issue #24 — task itself is valid; could re-run with `qwen3.6:latest` to confirm the task works.

## Next time

- Don't treat session-log narration as evidence of work. Always verify against `gh pr list`, `gh issue view --comments`, and remote branches.
- Add a post-run smoke check that requires at least one `▸ ` line OR at least one real side effect (branch / PR / comment) before claiming the executor "did something."
- Stop trying to make devstral work in this harness. Eval-04 + eval-05 (two runs) = three independent failure modes. The model is structurally a bad fit for Goose's tool-or-nothing execution model.
