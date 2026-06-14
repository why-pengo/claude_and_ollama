# eval-17b result

Second attempt of the eval-17 k-of-3 batch. See
[eval-17/result.md](../eval-17/result.md) for the consolidated writeup
across all three attempts.

## What ran

Goose + heavy harness on `health_track#51` (qwen3.6:latest, Goose
1.35.0, pre-runner-POC). Second retry of the reliability cliff
investigation.

## What happened

FAIL — model terminated early with zero code written, consistent with
the eval-17/17c pattern. Goose exited-0 after a no-tool-call turn.
Together the eval-17 series (3-of-3 FAIL) motivated the harness
complexity audit and ultimately the direct-Ollama runner POC.

## Verdict
Verdict: FAIL
