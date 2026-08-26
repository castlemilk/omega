#!/usr/bin/env bash
# Hardened session preflight — run as the FIRST bash call of every code task.
#
# Why this exists: the V210→V220 arc repeatedly wedged on a small family of
# git-lock failures (stale .git/*.lock after a killed commit, an index held by
# a background nohup training/orchestrator process, macOS FSEvents fsmonitor
# hangs, two code-task sessions sharing one cwd+index). This script makes the
# repo healthy *deterministically* before any work starts, so no session has to
# hand-clean .git/ again.
#
# It is idempotent and safe to run repeatedly. It only kills *git* processes
# (never python training runs) and only removes *lock* files (never objects or
# refs). If it exits non-zero, the environment is genuinely unhealthy (kernel
# wedge / disk) — STOP and report to the user; do NOT loop on it.
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

# 1. Kill only stray *git* processes (e.g. a wedged `git commit` from a killed
#    session). Never matches python/training runs. The `[ ]` regex avoids
#    matching this script's own pgrep/grep line.
pkill -9 -f 'git[ ]' 2>/dev/null || true
sleep 0.5

# 2. Remove stale lock files unconditionally. By step 1 no live git holds them;
#    a foreground git op creating its own lock starts *after* this script exits.
#    We only ever touch *.lock — never objects, refs, or the index itself.
rm -f .git/index.lock .git/HEAD.lock .git/config.lock \
      .git/objects/maintenance.lock 2>/dev/null || true
rm -f .git/refs/heads/*.lock 2>/dev/null || true

# 3. Re-assert the Mac-specific hardening every session (cheap, idempotent) so a
#    fresh clone or a reset config can't reintroduce the fsmonitor/auto-gc hangs.
git config core.fsmonitor false 2>/dev/null || true
git config gc.auto 0 2>/dev/null || true

# 4. Verify git responds promptly. If this times out the wedge is below git
#    (kernel/FSEvents/disk) — surface it rather than retry.
#
#    Portability: GNU `timeout` is NOT present on a stock macOS (it ships with
#    coreutils as `gtimeout`, and only if brew-installed). Calling it directly
#    exits 127, which `!` inverts into a spurious "env is unhealthy" FAIL on a
#    perfectly healthy machine — a hard, misleading block on step 0 of the
#    training loop. Prefer timeout → gtimeout → perl's alarm (perl ships with
#    macOS); only if all three are missing, probe without a bound.
_probe_git() {
  if command -v timeout > /dev/null 2>&1; then
    timeout 5 git rev-parse HEAD > /dev/null 2>&1
  elif command -v gtimeout > /dev/null 2>&1; then
    gtimeout 5 git rev-parse HEAD > /dev/null 2>&1
  elif command -v perl > /dev/null 2>&1; then
    perl -e 'alarm 5; exec @ARGV or exit 127' git rev-parse HEAD > /dev/null 2>&1
  else
    echo "[prepare_session] WARN: no timeout/gtimeout/perl — probing git unbounded." >&2
    git rev-parse HEAD > /dev/null 2>&1
  fi
}

if ! _probe_git; then
  echo "[prepare_session] FAIL: git did not respond within 5s — env is unhealthy."
  echo "[prepare_session] Do NOT retry. Report to the user: manual cleanup needed."
  exit 1
fi

echo "[prepare_session] OK ($(git rev-parse --short HEAD), branch $(git rev-parse --abbrev-ref HEAD))"

# 5. V228 resiliency #3: surface the session-continuity manifest first thing, so a
#    task entering after a laptop restart sees "V### is at step N, next is X, last
#    commit is Y, grid alive/dead" without re-deriving it. Read-only; never fails.
python3 scripts/session_state.py show 2>/dev/null || true

# 6. V238: freeze-gap validator — opt-in (OMEGA_CHECK_FROZEN_SERIES=1) because it
#    only matters for frozen-series runs. Read-only; strict so a corrupted freeze
#    (md5 mismatch) stops the session before a grid consumes it.
if [ "${OMEGA_CHECK_FROZEN_SERIES:-0}" = "1" ]; then
  python3 scripts/check_frozen_series_coverage.py --strict || exit 1
fi
