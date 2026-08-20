#!/bin/bash
# V274 Phase 0 — G4 (harness sanity) + G-DET on the three sentinel windows,
# both arms. Pre-registration: omega/nodes/victoria/training_log/V274.md §2/§3.
#
# ARM_OFF is byte-for-byte the V240 `universe_selective` feature string — the arm
# that produced the standing baseline (confirmed by G0, scripts/v274_provenance_audit.py).
# ARM_ON adds ONLY `"ic_seed_weighting": true`; per_regime_ic_weighting is left at
# its features.py default (True) in both arms, which is doubly inert under ARM_OFF.
#
# No code is changed by this version. The only lever is the --features JSON.
#
# Usage: bash scripts/v274_smoke.sh            (both arms)
#        ARMS=off bash scripts/v274_smoke.sh   (G4 reproduction only)
set -u
cd "$(dirname "$0")/.."

export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

SLEEP="${SLEEP:-0}"     # the V240 grid's condition — determinism is sleep-sensitive (V213)
FLOOR="${FLOOR:-200}"
N="${N:-2}"
CYCLES_DEFAULT=60       # the V240 grid's cycles for these 91-min_bars windows

AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"
OUT="$AUDIT_DIR/v274"; mkdir -p "$OUT"
SUM="$OUT/smoke_progress.log"

ARM_OFF='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true}'
# ARM_ON is written out in full rather than derived by string surgery from
# ARM_OFF, so the one-key diff is auditable by eye: ic_seed_weighting false->true.
ARM_ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": true, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true}'

# window|gate|committed_pnl  (committed values read from the V240 artifacts)
SENTINELS=(
  "snap_wf_20240310|crisis|1149.76"
  "snap_wf_20230912|trend|4679.67"
  "snap_wf_20250305|recent|771.98"
)

ARMS="${ARMS:-off on}"

log() { echo "$@" | tee -a "$SUM"; }

log "=== V274 Phase 0 smoke start $(date -u +%FT%TZ) N=$N sleep=$SLEEP cycles=$CYCLES_DEFAULT ==="

for spec in "${SENTINELS[@]}"; do
  IFS='|' read -r wid gate committed <<< "$spec"
  snap="data/snapshots/walk_forward/${wid}.json"
  [ -f "$snap" ] || { log "FATAL: missing snapshot $snap"; exit 2; }
  for arm in $ARMS; do
    case "$arm" in
      off) feats="$ARM_OFF"; expect_ic="off" ;;
      on)  feats="$ARM_ON";  expect_ic="on"  ;;
      *)   log "FATAL: unknown arm $arm"; exit 2 ;;
    esac
    vprefix="v274_${arm}_${wid}"
    log "--- CELL $vprefix gate=$gate arm=IC-$arm committed=\$$committed start $(date -u +%FT%TZ) ---"
    SNAP_OVERRIDE="$snap" CYCLES="$CYCLES_DEFAULT" \
      bash scripts/check_determinism.sh "$gate" "$N" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
      >> "$SUM" 2>&1
    rc=$?
    log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  done
done

log "=== V274 Phase 0 smoke complete $(date -u +%FT%TZ) ==="
