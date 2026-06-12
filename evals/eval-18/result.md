# eval-18 result

First eval after today's harness changes (1491751 — "every turn is a
tool call" patch to `prompts/goose-system.md` and recipe preamble),
testing whether the prompt fix unlocks `devstral:latest` for our
recipe.

The curl-probes earlier in this session showed devstral *can* produce
structured `tool_calls` through both Ollama endpoints (OpenAI-compat
and native `/api/chat`) — *if* the system prompt explicitly tells it
to use tools. The hypothesis: with the patched system prompt's
"Every turn is a tool call" section, devstral would engage with the
recipe.

Result: it didn't.

## Verdict

Verdict: FAIL

The model emitted a fabricated `<info-msg>` tag containing the text
"Step 0 — Load target-repo guidance" and then terminated. Zero tool
calls. Identical shape to eval-05 run 3 ("Immediate stop after one
fabricated `<info-msg>` block. Zero tools.") — a devstral-specific
failure pattern we have prior evidence for.

## What ran

- Recipe + wrapper: `feature/tool-call-discipline` @ 1491751
  (today's prompt patch applied; complexity-reduction audit NOT yet
  applied — that came later as 6f1e55a)
- Model: `devstral:latest` (overriding goose.yaml default of
  qwen3.6:latest)
- Context limit: 65536 (overriding 131072; matches devstral's
  eval-05 zone and gives breathing room for the AGENTS.md fetches +
  recipe context without pushing devstral past tested territory)
- Wrapper-forwarded envs: `GOOSE_MODEL=devstral:latest`,
  `GOOSE_CONTEXT_LIMIT=65536`
- Params: `issue_number=51`, `repo=why-pengo/health_track`;
  wrapper auto-resolved `base_branch=develop`
- Target task: `health_track#51` — the same multi-file backend
  task targeted in eval-10 through eval-14 and the eval-17 series

## What happened

28 lines of log total. After Goose's banner:

```
<info-msg>

**Step 0 — Load target-repo guidance**

</info-msg>
```

Then silent termination, exit 0. No `get_file_contents`, no
`issue_read`, no shell calls, no anything. The model hallucinated a
structural wrapper tag, populated it with what looks like the
beginning of an XML-shaped Step 0 announcement, closed the tag, and
considered itself done.

## Diagnosis

This is **eval-05 run 3, exactly**:

> Run 3 | `num_ctx 32768` + SYSTEM `" "` | cold | Immediate stop
> after one fabricated `<info-msg>` block. Zero tools.

Cold-load on devstral has a specific pathology where the model emits
this `<info-msg>` envelope instead of engaging with the system
prompt. The patched "Every turn is a tool call" section did not
prevent it because the model never engaged enough to read past its
own fabricated turn.

The curl probe earlier today *worked* for devstral because it was a
simple ~50-word system prompt with one tool declared and a direct
user question. Under the harness load (~250-line system prompt + 7+
tools + ~150-line recipe + 4 AGENTS.md fetches scheduled), the
model's instruction-following collapses to this fabricated-tag
output mode.

This is consistent with the broader pattern: devstral has shallow
instruction-following capacity that the harness's prompt mass
overruns. eval-05's other failure modes (fabricated narratives,
hallucinated GitHub UI, malformed tool calls in content) were
different shapes of the same underlying issue.

## What this tells us

- The curl-probe-passes-but-harness-fails gap is real. A model
  passing the simple-tool-call probe is necessary but not
  sufficient for harness viability.
- The 1491751 prompt patch alone doesn't rescue devstral. Either
  (a) devstral isn't recoverable through prompt engineering, or
  (b) the harness needs to get *substantially* lighter — not just
  add another section telling the model to use tools.
- The (b) hypothesis is the more interesting one. eval-18 is the
  prompt for the complexity-reduction audit
  (`docs/harness-complexity-audit.md`) committed alongside this
  result. Whether the slimmed harness rescues devstral is now an
  empirical question for a follow-up eval (eval-20 in the audit's
  test plan).

## Decision: don't k-of-n this one

eval-18 is a 1-of-1 FAIL with strong prior evidence (eval-05's five
runs) that retrying devstral under the same load gives more of the
same. Spending two more bazzite slots on eval-18b/c retries would
just confirm what we already know. The retries instead get redirected
to:

- eval-19: qwen3.6 + slimmed harness (6f1e55a), k-of-3 — tests
  whether the complexity reduction fixes the eval-17 regression
- eval-20: devstral + slimmed harness, k-of-3 — tests the
  bigger hypothesis that the harness was too heavy

If either of those completes, the picture changes substantially.

## Action items

- [x] eval-18 writeup (this file)
- [x] Complexity-reduction audit and apply (6f1e55a)
- [ ] Run eval-19 (qwen3.6, slimmed harness) k-of-3
- [ ] Run eval-20 (devstral, slimmed harness) k-of-3
- [ ] If eval-19 passes 3-of-3 and eval-20 passes any-of-3: ship
  this branch as a PR with the audit + cuts + eval evidence

## Next time

- Skip the k-of-n discipline on models we have prior multi-run
  evidence against in the same harness — eval-05 already did the
  retries for devstral. Treat the prior evidence as one of the n.
- For any future model-swap experiment: curl-probe with a *minimal*
  system prompt first (one tool, one user message). If that passes,
  curl-probe with the harness's actual system prompt and tool count
  (still a single turn, no recipe). If that *also* passes, then
  invest in a real eval. The middle gate would have caught devstral
  before eval-18.
