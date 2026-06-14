# eval-17c result

Third attempt of the eval-17 k-of-3 batch. See
[eval-17/result.md](../eval-17/result.md) for the consolidated writeup
across all three attempts.

## What ran

Goose + heavy harness on `health_track#51` (qwen3.6:latest, Goose
1.35.0, pre-runner-POC). Third retry of the reliability cliff
investigation.

## What happened

FAIL — model terminated early with zero code written, third
consecutive failure shape on the same task. The 3-of-3 FAIL series
established that the regression wasn't variance but a structural
issue, motivating the eval-19 slim-harness test and eventually the
direct-Ollama runner POC that landed in PR #54.

## Verdict
Verdict: FAIL
