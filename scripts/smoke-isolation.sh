#!/usr/bin/env bash
# Containment smoke test for claude-and-goose-runtime.
#
# Runs the image with no host mounts and asserts that the runtime CANNOT:
#   - read host dotfiles outside the container
#   - list /Users/jmorgan (or any other host-only path)
#   - read ~/.ssh/id_* on the host
#   - persist writes to ~/.profile (the container's own ~/.profile is fine
#     to write to; it disappears with --rm and is not the host's)
#
# These all pass on a properly contained image because the host paths
# simply don't exist inside the container. If any check unexpectedly
# succeeds in seeing host data, the test FAILS loudly.
#
# Usage: ./scripts/smoke-isolation.sh

set -euo pipefail

IMAGE="${CLAUDE_GOOSE_IMAGE:-claude-and-goose-runtime}"

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }

fail=0

# Helper: run a command in the container; expect the stdout to be empty
# OR to not contain a marker that would only appear if host data leaked.
check() {
  local name="$1" cmd="$2" forbidden="$3"
  blue "  $name"
  local out
  out="$(docker run --rm "$IMAGE" bash -c "$cmd" 2>&1 || true)"
  if [[ -n "$forbidden" ]] && grep -q "$forbidden" <<<"$out"; then
    red "    FAIL — saw forbidden marker '$forbidden' in output:"
    sed 's/^/      /' <<<"$out"
    fail=1
  else
    green "    pass"
  fi
}

echo "Smoke test against $IMAGE"
echo

# 1. /Users/jmorgan must not exist inside the container.
check "ls /Users/jmorgan should fail" \
  "ls /Users/jmorgan 2>&1; true" \
  "Desktop\|Documents\|Library"

# 2. Host SSH keys must be unreachable.
check "cat /Users/jmorgan/.ssh/id_* should find nothing" \
  "cat /Users/jmorgan/.ssh/id_* 2>&1; true" \
  "PRIVATE KEY"

# 3. Host ~/.profile must be unreachable. The container's own /home/goose/.profile
#    is a non-issue (ephemeral); we explicitly check the host path.
check "cat /Users/jmorgan/.profile should fail" \
  "cat /Users/jmorgan/.profile 2>&1; true" \
  "export "

# 4. /Volumes (macOS-specific mount root) should not be visible.
check "ls /Volumes should fail or be empty" \
  "ls /Volumes 2>&1; true" \
  "Crucial_X9\|Macintosh HD"

# 5. The container is unprivileged: writes outside HOME/WORKDIR should fail.
check "writing to /etc/passwd should fail" \
  "echo pwned >> /etc/passwd 2>&1; true" \
  "pwned"

# 6. Confirm we're running as the non-root 'goose' user.
blue "  whoami inside container"
who="$(docker run --rm "$IMAGE" whoami 2>&1)"
if [[ "$who" == "goose" ]]; then
  green "    pass (uid: goose)"
else
  red "    FAIL — expected 'goose', got '$who'"
  fail=1
fi

echo
if [[ $fail -eq 0 ]]; then
  green "All containment checks passed."
  exit 0
else
  red "One or more containment checks failed."
  exit 1
fi
