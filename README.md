![Claude and Ollama](assets/cnl.png)
# claude_and_ollama

An evaluation harness for a two-agent code workflow:

- **Claude Code** is the planner. It reads context, decomposes work,
  and files structured GitHub Issues.
- **Goose** is the executor. It reads one issue at a time, executes
  its subtasks, comments with results, and opens a PR.

This repo holds the recipes, prompts, and eval results. It is *not*
the target project — it is the rig.

## Pieces

| Path                          | Purpose |
|-------------------------------|---------|
| `CLAUDE.md`                   | What Claude Code reads on every session |
| `goose.yaml`                  | Provider + extension config (Ollama on `bazzite.local`, `qwen3.6:latest`) |
| `recipes/execute-issue.yaml`  | Core recipe: read issue → execute subtasks → PR |
| `recipes/plan-epic.yaml`      | Stub for future Goose-driven issue authoring |
| `prompts/goose-system.md`     | System prompt Goose runs with |
| `prompts/issue-format.md`     | Canonical issue template |
| `evals/`                      | One folder per eval run |
| `scripts/new-eval.sh`         | Scaffold a new `evals/eval-NN/` directory |
| `scripts/check-ollama.sh`     | List installed models on the Ollama host |
| `scripts/post-run-check.sh`   | Verify a goose run produced real artifacts (tool calls + branch / PR) |
| `Dockerfile`                  | `claude-and-goose-runtime` image — goose + github-mcp-server + gh + git, non-root |
| `scripts/run-recipe-in-container.sh` | Wrapper that runs a recipe inside the sandbox image |
| `scripts/smoke-isolation.sh`  | Containment smoke test for the runtime image |

## Execution environment

Ollama host (`bazzite.local`):

- AMD Ryzen 9 9900X (12C/24T)
- 96 GB DDR5
- NVIDIA RTX 5090, 32 GB VRAM
- Running `qwen3.6:latest` (36B params, Q4_K_M, ~24 GB)

## Running an eval

Goose runs inside a sandboxed Docker container — see issue #4 for
motivation. The host-side dependency is Docker Desktop and a PAT.

1. A `goose-task` issue exists, is `ready-for-execution`, and has no
   open dependencies.
2. Build the runtime image once (or after upgrading goose /
   github-mcp-server):
   ```
   docker build -t claude-and-goose-runtime .
   ./scripts/smoke-isolation.sh   # optional, confirms containment
   ```
3. Export the PAT for the github MCP extension:
   ```
   export GITHUB_PERSONAL_ACCESS_TOKEN=...
   ```
4. Scaffold an eval directory and run the recipe via the container
   wrapper. The wrapper resolves `bazzite.local` on the host and
   exports `OLLAMA_HOST` into the container, so mDNS doesn't need to
   work from inside Docker.
   ```
   ./scripts/new-eval.sh 03
   ./scripts/run-recipe-in-container.sh \
     --recipe recipes/execute-issue.yaml \
     --params issue_number=N \
     | tee evals/eval-03/goose-session.log
   ```
5. Verify the run produced real artifacts (catches the "narration-without-execution" failure mode from eval-05):
   ```
   ./scripts/post-run-check.sh N
   ```
6. Write `evals/eval-NN/result.md` (template scaffolded by the script).

## Status

**Settled on `qwen3.6:latest`** as the executor model after six
evals (eval-01, -02, -04, -05, -06, -07; eval-03 was skipped). The
harness loop (Claude plans → Goose executes → human reviews → PR
merged) is operational end to end.

Eval log:

- **eval-01** — first containerised Goose run against a real issue.
- **eval-02** — sandbox containment smoke test.
- **eval-04-bakeoff** — three-model shootout
  (`qwen3.6:latest` vs `qwen2.5-coder:32b` vs `devstral:latest`).
  Only qwen3.6 reliably completed the recipe.
  [`evals/eval-04-bakeoff/result.md`](evals/eval-04-bakeoff/result.md).
- **eval-05** — five-run devstral re-bench under multiple config
  variants. All five failed with distinct failure modes; devstral
  written off as structurally unsuited.
  [`evals/eval-05/result.md`](evals/eval-05/result.md).
- **eval-06** — first real-target eval (`scripts/post-run-check.sh`).
  Partial pass; human review caught GNU-only portability bugs.
  [`evals/eval-06/result.md`](evals/eval-06/result.md).
- **eval-07** — same task after prompt hardening. Shell-call count
  dropped from 16 to 0; clone-into-host regression gone. New
  shell/jq quoting bugs caught in review and fixed before merge.
  [`evals/eval-07/result.md`](evals/eval-07/result.md).

Other models considered: `qwen2.5-coder:32b` (Modelfile/template
gap — emits tool calls as JSON text rather than structured
`tool_calls`) and `devstral:latest` (trained for the OpenHands
scaffold; conflicts with Goose's recipe and fails non-deterministically).

Open follow-up:

- #15 — `push_files` doesn't expose a `mode` field on the MCP tool
  schema, so executables can't be landed with the executable bit
  set. Blocked on upstream
  [github/github-mcp-server#2578](https://github.com/github/github-mcp-server/issues/2578).
  Workaround: `chmod +x` post-merge, documented as a `## Follow-ups`
  line in goose-authored PRs.
