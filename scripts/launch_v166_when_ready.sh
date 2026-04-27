#!/bin/zsh
# Watcher: launches v166_live as soon as v164_live process exits.
# v166_live = v161_live preset + live_signal_normalization=False (default).
# This gives macro signal observability without changing strategy behavior.
set -e
PY=/opt/homebrew/Cellar/python@3.14/3.14.3_1/bin/python3
V164_PID=89039
WORKTREE=/Users/benebsworth/projects/omega/.claude/worktrees/inspiring-edison-31c334

cd "$WORKTREE"

echo "[$(date)] watcher starting; v164_pid=$V164_PID"
while kill -0 $V164_PID 2>/dev/null; do
  sleep 60
done
echo "[$(date)] v164_live (pid $V164_PID) exited; launching v166_live"

# Build features JSON for v166: v161_live preset, normalization OFF
$PY -c "
import json
from omega.nodes.victoria.features import VictoriaFeatures
from dataclasses import asdict
base = asdict(VictoriaFeatures.preset('v161_live'))
base['live_signal_normalization'] = False
print(json.dumps(base))
" 2>/dev/null > /tmp/v166_live_features.json

mkdir -p data/runs
FEAT=$(cat /tmp/v166_live_features.json)

OMEGA_METRICS_DIR=data/runs nohup $PY scripts/run_training.py \
  --version v166_live \
  --cycles 24 \
  --sleep 3600 \
  --features "$FEAT" \
  > data/v166_live.log 2>&1 &
disown
PID=$!
echo "[$(date)] v166_live launched pid=$PID"
echo $PID > data/v166_live.pid
