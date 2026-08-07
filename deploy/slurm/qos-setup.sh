#!/usr/bin/env bash
set -euo pipefail

mode="${1:---dry-run}"
commands=(
  "sacctmgr add qos agent-service Priority=100"
  "sacctmgr add qos user-interactive Priority=80 MaxTRESPU=gres/gpu=1"
  "sacctmgr add qos batch Priority=40"
  "sacctmgr add qos opportunistic Priority=10 PreemptMode=REQUEUE"
  "sacctmgr add qos maintenance Priority=200"
)
for command_text in "${commands[@]}"; do
  echo "$command_text"
done
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: no Slurm accounting changes applied"
  exit 0
fi
echo "error: review cluster accounting and execute commands individually as administrator" >&2
exit 1
