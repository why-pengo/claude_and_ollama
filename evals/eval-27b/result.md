# eval-27b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen3-coder:30b-a3b-q4_K_M`
- Options: `{'num_ctx': 102400}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2` (overshoot from a TRACE-level probe; doesn't affect the run)
- Pre-flight: 100% GPU resident at 102400
- Second of 3 qwen3-coder runs in the #47 bake-off — see `docs/bakeoff-summary.md` for comparative analysis

## What worked

- Clean 18-turn end-to-end run. Zero nudges, zero salvage, zero loop-detect trips, zero prose-rescues.
- All 5 issue-mandated files produced and committed via `push_files`.
- PR #78 opened on health_track, status comment posted on issue #51.

Tool-call trajectory:
```
get_file_contents (AGENTS.md) → issue_read → create_branch → create_branch (retry) →
5× get_file_contents (context reads) → 5× create_or_update_file → push_files →
1× create_or_update_file (extra file after push) → create_pull_request → add_issue_comment
```

## What didn't

- Two `create_branch` calls (turns 3 and 4). The first probably emitted with a slightly wrong arg shape; the second corrected and succeeded. Minor friction; no consequence for the recipe.

## Verdict

Verdict: PASS

Second clean 3-of-3 PASS for qwen3-coder. The minor branch-creation retry is noise compared to the substantive overshoot pattern that 27c exposed; comparison and significance live in `docs/bakeoff-summary.md`.

## Next time

- Bake-off complete; no per-eval next-time items.
