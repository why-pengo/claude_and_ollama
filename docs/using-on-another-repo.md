# Using this harness on another repo

The harness is *not* tied to `claude_and_goose`. The recipe and Goose extensions talk to GitHub via the MCP server, so they work against any GitHub repo as long as you point at it. This doc covers what to set up before pointing it at another repo and what to expect on the first few runs.

## What works well (proven)

- Single-file additions with explicit specs (a bash script, a small docs file, a config snippet).
- The full loop: read issue → branch → push file via MCP → PR with `Closes #N` → comment on issue.
- Prompt-enforced behaviours: no shell `git`, no host clones, honest `did not execute; static-checked only` verification framing.

## What hasn't been tested (proceed carefully)

- Multi-file changes. The executor has only ever produced one file per PR in our evals.
- Bug fixes where the model has to find the bug first. Every successful eval was "write this from a clear spec."
- Anything touching build, CI, or dependencies. Untested.
- Refactors that span more than ~50 lines.

For first runs on a new repo, stick to the proven class of task.

## Prerequisites

1. **Bazzite + Ollama + qwen3.6 reachable.** No change from the existing setup. `./scripts/check-ollama.sh` shows what's loaded on the host — confirm `qwen3.6:latest` is in the list.
2. **A PAT scoped to the target repo.** Fine-grained PAT, with these permissions:
   - Contents: Read and write
   - Issues: Read and write
   - Pull requests: Read and write
   - Metadata: Read
   - **Not** Administration. **Not** repository-creation. (eval-07 showed the model will attempt `create_repository` when stuck; bounded only by PAT scope.)
3. **Runtime image built.** Same `claude-and-goose-runtime` image — no per-target rebuild needed.

## Authoring the issue

The recipe expects the canonical structure in `prompts/issue-format.md`:

- Title with conventional-commit prefix (`feat:`, `fix:`, `docs:`)
- **Goal** — one paragraph
- **Context** — files / prior issues / links the executor must read first
- **Subtasks** — ordered, independently verifiable checklist items
- **Acceptance criteria** — observable outcomes
- **Out of scope** — explicit list of what NOT to do

Random GitHub issues won't follow this. Either:

- Author the issue from a Claude Code session in this repo using the format-aware planner role, OR
- Hand-edit an issue in the target repo to add the canonical sections.

Apply `goose-task` and `ready-for-execution` labels. If the target repo doesn't have those labels yet, create them once (or skip — they're for organising your own queue, not required by the recipe).

## Running the recipe against the target repo

The recipe accepts a `repo` parameter (`owner/name`). The wrapper always bind-mounts **the harness repo itself** at `/work` (it resolves the git root containing the wrapper script, not your current directory), so you can invoke it from anywhere — but `/work` will be this repo. That's fine, because Goose talks to the target repo through MCP, not the local filesystem. The recipe and prompts only need to be reachable at `/work`, which they always are.

Pass both params on the same invocation — the wrapper supports repeating `--params`:

```
ISSUE=42  # the target-repo issue number you want executed
export GITHUB_PERSONAL_ACCESS_TOKEN=<PAT for target>
./scripts/run-recipe-in-container.sh \
  --recipe recipes/execute-issue.yaml \
  --params issue_number=$ISSUE \
  --params repo=owner/target-repo \
  | tee /tmp/goose-target-$ISSUE.log
```

## Reviewing the PR

Plan on a real review every time. Things to actually verify, not assume:

- **Did the executor produce real artifacts?** Run `./scripts/post-run-check.sh N` to confirm tool calls happened and a branch / PR exists. Catches the "narrated success but did nothing" failure mode from eval-05.
- **Does the code actually run?** Goose often produces code that looks right but has subtle bugs (shell quoting, non-portable commands, etc.). Run it before approving.
- **Does the PR body's `## Verification` claim things it can verify?** If the executor wrote `[x] Verified by running …`, did it actually run anything? Check the session log for a `▸ shell` line that matches. If the executor wrote `did not execute; static-checked only`, that's the honest framing — believe it.
- **Did the executor stay in scope?** Compare changed files to the issue's subtasks. Goose can be tempted into "follow-up" work that wasn't asked for.
- **Did anything leak onto the host?** Check `git status` from the target repo's directory for untracked `*_clone/`, `practice*/`, or stray temp files. The prompt forbids these but verify.

## Cleanup after each run

- Delete any temporary branches the executor created if you decide not to merge.
- `rm -rf` any host pollution (shouldn't happen post-PR-#33, but verify).
- If you ran in the target repo's working directory, `git status` to confirm nothing landed locally that wasn't intended.

## Known pitfalls

- **Executable bit on shell scripts.** MCP `push_files` doesn't expose a `mode` field (#15, blocked on `github/github-mcp-server#2578`). The executor will note this under `## Follow-ups`; you `chmod +x` post-merge.
- **The model dropping quote characters.** qwen3.6 has consistently missed required `"..."` and `'...'` inside jq filters or bash interpolations. When writing the issue, spell out the exact shell idiom you want, character for character — and review for transcription errors.
- **Stalled sessions.** If the executor stops after narrating intent with zero tool calls in the log, restart. We've seen this with cold models on large prompts; usually resolves on a warm second attempt.
- **`create_repository` attempts.** The model will sometimes try this when stuck. The PAT scope above blocks it server-side, but it's a signal the recipe or issue is confusing the model.

## When something goes wrong

Treat the session log as evidence, not summary. The PR body is the model's *claim*; the session log shows what the model actually did. Compare them. If they disagree, trust the log.

Capture the run as a new `evals/eval-NN/` directory if it's instructive — the eval folder pattern is useful for harness-shakedown work even when run on other repos. Use `scripts/new-eval.sh`.
