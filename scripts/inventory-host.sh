#!/usr/bin/env bash
set -euo pipefail

echo "Inventory is read-only; missing tools are reported as unavailable."
uname -a
echo "cpu_count=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo unknown)"
echo "memory:"
free -h 2>/dev/null || vm_stat 2>/dev/null || true
echo "filesystems:"
df -h
echo "cgroup:"
if [[ -f /sys/fs/cgroup/cgroup.controllers ]]; then
  echo "cgroup_v2=yes"
  sed -n '1p' /sys/fs/cgroup/cgroup.controllers
else
  echo "cgroup_v2=not-detected"
fi
echo "nvidia:"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=index,name,uuid,memory.total,driver_version --format=csv
else
  echo "nvidia-smi unavailable"
fi
echo "slurm:"
for command_name in scontrol sinfo squeue sbatch sacct; do
  if command -v "$command_name" >/dev/null 2>&1; then
    command -v "$command_name"
  else
    echo "$command_name unavailable"
  fi
done
