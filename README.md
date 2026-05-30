![Claude and Goose](assets/cng.png)
# claude_and_goose

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
5. Write `evals/eval-03/result.md` (template scaffolded by the script).

## Status

Pre-eval-01. Harness is freshly scaffolded — nothing has been run end
to end yet. See issue #1.
