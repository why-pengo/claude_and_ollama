# eval-29 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen2.5-coder:32b` (Q4_K_M)
- Options: `{'num_ctx': 98304}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=1`
- Pre-flight: 100% GPU resident at 98304
- **First qwen2.5-coder run, BEFORE PR #87 (#84 prose-shaped-tool-call rescue) landed.** Kept as historical record — this is the run that motivated #84.

## What worked

- Nothing on the runner side. Salvage opted out (no branch, no issue context populated).

## What didn't

- **Model never used the structured `tool_calls` field.** Every turn emitted well-formed tool-call JSON in the content channel:
  ```
  [model emitted prose — 119 chars; no tool call]
  {"name": "github__get_file_contents", "arguments": {"owner": "why-pengo", "repo": "health_track", "path": "AGENTS.md"}}

  [runner: nudging — "You have not read the issue yet. ..."]
  ```
- Three consecutive prose-only turns → 3-empty-turn guard fired at turn 3.
- Salvage skipped: no branch was ever created, no issue title captured.

## Verdict

Verdict: **FAIL** (re-classified: this is a harness-coverage gap, not a model competence gap)

The model knew the correct tool name. The model knew the correct argument shape. The model produced clean JSON. The runner couldn't see any of it because it lived in the wrong channel.

## Next time / what this triggered

- **#84 filed and merged** — `parse_prose_tool_call()` rescues this exact failure mode. eval-30 / 30b / 30c are the re-runs with rescue active.
- Kept as historical record per CLAUDE.md's eval-tracking convention — provides the proof that #84 was needed.
- Not counted in the #47 bake-off scoreline (the post-#84 trio at 30 / 30b / 30c is what the recommendation reads).
