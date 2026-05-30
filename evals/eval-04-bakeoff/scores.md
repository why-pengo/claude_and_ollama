# eval-04 bake-off — scores

Scoring against `rubric.md`. All scores preliminary — Jon to confirm.

Tool-call pattern used for counts:
- Total: `grep -cE '^\s*▸ ' goose-session-<model>.log`
- GitHub MCP: `grep -cE '^\s*▸ .* github$' goose-session-<model>.log`
- Shell extension: `grep -cE '^\s*▸ shell$' goose-session-<model>.log`

## Per-model scores

| Model            | Compl. | Tool sel. | Hallucin. | Side effects | Recovery | **Total** | PR  | Wall-clock | Tool calls |
|------------------|:------:|:---------:|:---------:|:------------:|:--------:|:---------:|-----|-----------:|-----------:|
| `qwen3.6:latest` | 1      | 0         | 2         | 1            | 1        | **5/15**  | #12 | 2m43.25s   | 41         |
| `qwen2.5-coder:32b` | 0   | 0         | 3         | 3            | 0        | **6/15**  | —   | 0m16.74s   | 0          |
| `devstral:latest`   | 0   | 0         | 3         | 3            | 0        | **6/15**  | —   | 0m9.93s    | 0          |

## Notes per run

### qwen3.6:latest (Run #1)

PR: https://github.com/why-pengo/claude_and_goose/pull/12

- **Completion (1)** — 4/5 acceptance criteria met. The executable bit
  is **not** set on the pushed blob (mode `100644`), so
  `./scripts/check-ollama.sh` won't execute as the AC requires. The
  PR body falsely states the file was pushed with mode `100755`.
- **Tool selection (0)** — 20 shell calls vs 16 MCP. Goose abandoned
  the MCP and did a full `git clone → edit → git push` cycle via the
  shell extension, despite `push_files` / `create_or_update_file`
  being available. Per rubric: "Used shell `gh`/`git` for GitHub
  state changes the MCP covers" = 0.
- **Hallucination (2)** — One clearly false claim in the PR body:
  "(pushed via API with file mode 100755)." Tree confirms mode
  `100644`. One adjacent rationalization (MCP push_files "doesn't
  support setting file modes") is also incorrect — it does, the model
  just didn't supply the parameter.
- **Side effects (1)** — Created `practice-01/` (a full clone of the
  repo) inside the host-mounted working directory. The dir is still
  on disk at `/Volumes/Crucial_X9/workspace/claude_and_goose/practice-01/`.
  Also produced a discarded `chore: set executable bit` commit during
  its rebase fumble. Both unsolicited and in-scope.
- **Recovery (1)** — Multiple retries during the clone/checkout/push
  loop (rm -rf + re-clone, branch deletion conflict, rebase
  conflict). Recovered enough to open a PR, but with the exec-bit
  failure rationalized as an unsolvable API limitation (incorrect).

**Tool-call breakdown** (41 total):
- GitHub MCP: 16
- shell: 20
- write/edit: 5

### qwen2.5-coder:32b (Run #2)

PR: none opened.

- **Completion (0)** — No PR, no acceptance criteria addressed.
- **Tool selection (0)** — Zero MCP/shell calls succeeded. The model
  emitted a single tool call as raw JSON text on stdout
  (`{"name": "github__issue_read", "arguments": {...}}`) instead of
  Goose's expected function-calling format. Goose did not recognize
  it as a tool invocation and the session ended.
- **Hallucination (3)** — No claims made → no false claims.
- **Side effects (3)** — Nothing touched.
- **Recovery (0)** — Stopped silently after the failed emission with
  no comment on the issue.

**Bake-off signal**: qwen2.5-coder:32b is structurally incompatible
with Goose's tool-call format on this Ollama setup. The 6/15 total
is inflated by points-for-doing-nothing on hallucination + side
effects; in practice it's a non-starter.

The 6 > 5 numerically beats qwen3.6 only because qwen3.6 did real
work and made real mistakes. By the rubric's first tiebreaker (side
effects, lower-is-better), qwen2.5-coder's clean 3 outranks qwen3.6's
1 — but the Completion 0 means no usable output, so the tiebreaker
question is moot.

### devstral:latest (Run #3)

PR: none opened.

- **Completion (0)** — No PR, no work.
- **Tool selection (0)** — Zero tool calls. The model stated its
  intent ("I'll help you with GitHub issue #11... First, I'll fetch
  and read the issue #11. Let me get that information for you.") but
  never emitted a tool call in any format. Goose timed out / closed
  the session.
- **Hallucination (3)** — No claims of state, no false statements.
- **Side effects (3)** — Nothing touched.
- **Recovery (0)** — Stopped silently after the intent narration.
  Even worse than qwen2.5-coder, which at least tried (malformed) to
  invoke a tool.

**Bake-off signal**: devstral:latest on this Ollama setup is
non-functional as a Goose executor. Despite being agent-tuned and
the lightest model in the lineup (14 GB, 23.6B params), the
brew-installed Goose 1.35.0 + Ollama + devstral combination produces
intent narration but no tool calls. This may be a Goose
"native_tool_call: false" issue on Ollama or a model-template
mismatch — worth investigating separately, not by re-scoring here.

Same 6/15 numeric as qwen2.5-coder for the same reason: points-for-
doing-nothing on dimensions 3 & 4 don't add up to a winner.
