# feat: add scripts/check-mcp.sh helper

## Goal

Add a small bash helper that verifies the `github-mcp-server` binary is installed and prints its version. Companion to `scripts/check-ollama.sh`. Useful for quick harness-side sanity checks before running an eval.

## Context

- The harness uses `github-mcp-server` (Go binary from `github/github-mcp-server`) as Goose's primary tool for GitHub state changes.
- `scripts/check-ollama.sh` already exists as the equivalent helper for the Ollama side. This issue adds the matching MCP-side helper.
- File mode caveat: the MCP `push_files` tool schema does not currently expose a `mode` field (see `prompts/goose-system.md`), so you cannot land the script with the executable bit set. List that as a `## Follow-ups` item in the PR body so a human can `chmod +x` post-merge — do **not** invent a `permissions.sh` workaround or claim a mode you cannot verify.

## Subtasks

- [ ] Create `scripts/check-mcp.sh` with the following shape:
  - bash shebang, `set -euo pipefail`
  - 5-line header comment describing what it does + usage
  - check `command -v github-mcp-server` — if missing, print a clear error to stderr (`Error: github-mcp-server not found on PATH`) and exit non-zero
  - if present, run `github-mcp-server --version` and print the output
- [ ] Push the new file via `push_files` MCP (single-entry call).
- [ ] Open a PR with `Closes #<this-issue>` in the body. PR body must include:
  - `## Summary` — 2 bullets
  - `## Verification` — each acceptance criterion checked off
  - `## Follow-ups` — single line noting the executable bit was not set (MCP limitation), human needs to `chmod +x` post-merge.

## Acceptance criteria

- File `scripts/check-mcp.sh` exists on the branch.
- File contains a `set -euo pipefail` line.
- File uses `command -v github-mcp-server` to check for the binary (grep -q this pattern).
- File contains a `github-mcp-server --version` invocation.
- PR body lists the executable-bit limitation under `## Follow-ups` (do NOT claim mode 100755 was set).

## Out of scope

- Modifying `scripts/check-ollama.sh`.
- Updating `README.md` or any other file.
- Performing a real MCP handshake (e.g. starting the stdio server). A binary-presence check + `--version` is enough.
- Inventing a `permissions.sh` or `chmod` helper script to work around the mode limitation.
