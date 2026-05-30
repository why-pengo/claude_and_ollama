# eval-04 bake-off — verdict

**Winner: `qwen3.6:latest` — kept as the harness default.**

Won by being the only model in the lineup that produced a PR. The
other two failed at the tool-call protocol layer before doing any
work.

> **Update (#16 investigation):** the devstral failure documented
> below did **not** reproduce on re-test — devstral now makes the
> same `issue_read` call cleanly in the same recipe + container.
> Likely cause was a cold-load + long-prompt timing flake against
> Goose's default `OLLAMA_STREAM_TIMEOUT`. Mitigation landed in
> `goose.yaml` (raised the timeout to 60s). qwen2.5-coder's failure
> is a real Ollama Modelfile / chat-template issue and remains in
> #16. Section below preserved as the original record.

## Summary

| Model               | Total  | Outcome |
|---------------------|--------|---------|
| `qwen3.6:latest`    | 5/15   | Opened PR #12. Real work, real mistakes. |
| `qwen2.5-coder:32b` | 6/15*  | Zero tool calls. Emitted a malformed tool call as text and stopped. |
| `devstral:latest`   | 6/15*  | Zero tool calls. Narrated intent, never invoked a tool. |

\* The 6/15 scores for the non-functional models come from
points-for-doing-nothing on Hallucination (no claims to be false)
and Side effects (touched nothing). They are not real wins.

## Why qwen3.6 wins

It's the only one that can complete the loop. The eval-04 sandbox
task (`scripts/check-ollama.sh` — a 25-line bash file) is at the
low-complexity end of what we ask the executor to do, and only
qwen3.6 produced a mergeable artifact, even if it took a messy
shell-clone path instead of the MCP one.

## What qwen3.6 still gets wrong (open issues to file)

1. **Tool-selection drift to shell `git`** — Goose used 20 shell
   calls (mostly `git clone`/`git push`/`git checkout`) vs 16 MCP
   calls. The clone went into the host-mounted `/work` and leaked a
   `practice-01/` directory into Jon's working copy. Worth tightening
   the system prompt to forbid `git clone` in favor of MCP file ops.
2. **Executable-bit blind spot** — qwen3.6 falsely claimed in the PR
   body that the file landed with mode 100755 when the tree shows
   100644. The underlying Git Data API *does* support per-entry
   modes, but the `github-mcp-server` tool schema for `push_files`
   doesn't expose a `mode` field, so MCP callers can't set the
   executable bit today. qwen3.6's framing of this as an MCP
   limitation was directionally right; the PR-body claim about the
   actual landed mode was not. Filed upstream as
   [github/github-mcp-server#2578](https://github.com/github/github-mcp-server/issues/2578),
   tracked locally as #15.
3. **Practice-clone sandbox pattern** — qwen3.6 seems to want a
   `git clone` workspace separate from `/work`. The container
   already _is_ a sandbox, so this is wasted work. Could be cleared
   up in the prompt.

## Why the other two failed

Both failed at the same layer: emitting tool calls in a format
Goose recognizes. This is independent of model quality on coding.

- **qwen2.5-coder:32b** — emitted a single JSON tool call as raw
  stdout text (`{"name": "github__issue_read", "arguments": {...}}`),
  Goose did not parse it as a function call, session ended.
- **devstral:latest** — narrated its intent in prose and stopped
  without ever attempting a tool call.

Both behaviours suggest the Goose ↔ Ollama tool-calling pipeline is
configured for one specific tool-call schema that qwen3.6's chat
template happens to produce and the others don't. This is a Goose
config issue, not a model-capability statement — qwen2.5-coder and
devstral are both demonstrably tool-capable in other harnesses.

**Follow-up worth filing:** Investigate Goose's
`native_tool_call` / `tool_format` flags for Ollama and whether any
toggle would let these models participate. If so, re-run them and
score the bake-off properly.

## Tiebreaker check

Per the rubric, tiebreakers are: side effects → tool selection →
wall-clock. qwen3.6 scored 5; the others 6. But the 6s are inflated
by zero-work points and the Completion 0 means no usable output, so
they sit below qwen3.6 in practical terms regardless of the numeric
total. Recommendation: amend the rubric in a future eval to
penalise "no tool calls at all" — or treat Completion 0 as a hard
elimination.

## Decision

- Keep `GOOSE_MODEL: qwen3.6:latest` in `goose.yaml`.
- Follow-ups filed:
  - #14 — forbid shell `git clone`/`push` in Goose system prompt
  - #15 — teach prompt that `push_files` supports file modes
  - #16 — investigate Goose tool-call format for non-qwen3.6 Ollama models
- Close issue #7 (bake-off) once #14–#16 land — link them in the
  close comment.
