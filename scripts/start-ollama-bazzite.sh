#!/usr/bin/env bash
# Start Ollama on bazzite for the claude_and_ollama runner.
#
# Tracked in this repo so changes have audit history; copy to bazzite
# (~/workspace/Ollama-<version>/start-ollama.sh or similar) after edits.
#
# Settings here apply server-wide and are bound at model load — Ollama
# does not currently expose any of them as per-request /api/chat options,
# so a restart is required to change them.
#
# What's intentionally NOT here:
#   OLLAMA_KV_CACHE_TYPE=q8_0  — used during eval-25 for 70B+CPU-offload
#                                survivability; removed when offload was
#                                parked (see docs/offload-config.md).
#                                Quantizing KV across every loaded model
#                                adds a quality confound to the #47 bake-off,
#                                especially for code-tuned candidates where
#                                attention precision matters most. Default
#                                f16 KV is the no-thumb-on-the-scale stance.
#                                If a future model genuinely needs it back,
#                                consider whether per-model Modelfiles are
#                                the right way (vs server-wide) — and
#                                reckon with the all-API-driven direction
#                                first.
set -euo pipefail

OLLAMA_DIR="${OLLAMA_DIR:-$HOME/workspace/Ollama-0.30.7}"
OLLAMA_BIN="$OLLAMA_DIR/bin/ollama"
LOG="$OLLAMA_DIR/ollama-serve.log"

# Stop any existing instance — server-wide env vars are bound at process
# start; can't flip them under a running serve without a restart.
if pgrep -f 'ollama serve' >/dev/null; then
  echo "Stopping existing ollama serve..."
  pkill -f 'ollama serve' || true
  # Wait for socket to free up
  for _ in $(seq 1 10); do
    pgrep -f 'ollama serve' >/dev/null || break
    sleep 1
  done
fi

# OLLAMA_FLASH_ATTENTION=1  → faster attention + lower memory regardless
#                             of KV cache type. Free win on supported GPUs
#                             (CUDA 12+ on the 5090). Kept independent of
#                             KV quant.
# OLLAMA_HOST=0.0.0.0:11434 → listen on all interfaces (runner is on the Mac)
# OLLAMA_KEEP_ALIVE=-1      → never unload models. Reloads confound timing
#                             measurements and add 30-60s latency to the
#                             first turn of a bake-off run.
# OLLAMA_NUM_PARALLEL=1     → serial workload — avoids duplicate KV cache
#                             per parallel slot. The runner only ever has
#                             one in-flight chat call at a time.

export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_HOST=0.0.0.0:11434
export OLLAMA_KEEP_ALIVE=-1
export OLLAMA_NUM_PARALLEL=1

echo "Starting ollama serve with:"
env | grep -E '^OLLAMA_' | sort
echo
echo "Logging to: $LOG"

nohup "$OLLAMA_BIN" serve > "$LOG" 2>&1 &
sleep 2

if pgrep -f 'ollama serve' >/dev/null; then
  pid=$(pgrep -f 'ollama serve' | head -1)
  echo "ollama serve started (pid: $pid)"
  echo "Tail log:  tail -f $LOG"
  echo "Verify load: ollama ps after loading a model — check the size_vram_gb"
  echo "  field matches your VRAM budget for the candidate."
else
  echo "ERROR: ollama serve did not start; check $LOG" >&2
  exit 1
fi
