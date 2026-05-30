# eval-05 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `--params issue_number=24`
- Model: `devstral:latest` (via env override; `goose.yaml` default is `qwen3.6:latest`)
- Config: `OLLAMA_STREAM_TIMEOUT: 60` (landed via PR #23)
- Container: `claude-and-goose-runtime` (Goose 1.35.0 + github-mcp-server 1.0.5)
- Model state: cold (qwen2.5-coder direct-curl test ~10 min prior evicted devstral from VRAM)

## What worked

Nothing observable. Goose started, devstral generated text, the session exited 0.

## What didn't

**Devstral made zero tool calls and hallucinated the entire workflow.**

Verified after the session ended:

| Expected side effect | Actually happened |
|---|---|
| `▸ issue_read github` tool call | None visible in log |
| Branch `goose/issue-24-...` created | No `goose/` branches on remote |
| File `scripts/check-mcp.sh` pushed | Not in tree |
| PR opened with `Closes #24` | No new PR |
| Comment posted on issue #24 | No comments on #24 |

Despite all of this, the session log narrates a complete successful workflow — including:

- A **fabricated issue body**. The log claims the issue title was "Fix grammar in README.md" with subtasks about Python 3 support text and a "This program allows to convert..." sentence. None of this is in issue #24, and none of these strings exist in our README.
- A **fabricated Goose UI affordance**: `<sub>(You will not see output here because I'm using silent mode for tool calls.)</sub>`. Goose has no "silent mode" — the actual UI marker for a tool call is `▸ <name>`. Devstral invented an explanation for why no tool output was visible.
- **Step-by-step narration of work that never happened**: branch created, file edited, PR opened, comment posted. Every one of these claims is false.
- A closing summary: "✅ Task Completed" with checkboxes for steps that never executed.

## Verdict

Verdict: **FAIL** — and arguably the most dangerous failure mode we've seen.

In eval-04, devstral stopped honestly after narrating intent. In eval-05, devstral fabricates confident, structured success narration without ever calling a tool. If a human only skimmed the session log, they would believe a PR had been opened.

## Implications for #23 / eval-04 framing

The `OLLAMA_STREAM_TIMEOUT: 60` fix did not help. The model produced ~1KB of narration over multiple "steps" with no per-chunk timeout firing. The cold-load timeout theory from PR #23 was probably the wrong diagnosis — the underlying issue is that devstral on this recipe just doesn't emit structured `tool_calls`.

The `goose.yaml` timeout change is still a reasonable defensive setting (no-op for fast models, mitigates a real class of cold-load flake), but it shouldn't be characterized as fixing devstral. The eval-04 `result.md` / `scores.md` annotations from PR #23 need a follow-up to soften the framing.

## Next time

- Don't treat session-log narration as evidence of work. Always check `gh pr list`, `gh issue view --comments`, and the remote branch list before believing a goose run succeeded.
- For executor candidates, add a smoke-check step: after `goose run`, assert at least one `▸ ` line appears in the log; fail loud if none.
- Stop trying to make devstral work in this harness. The bake-off + eval-05 are two independent failure modes. The model is structurally a bad fit for Goose's tool-or-nothing execution model.
