#!/usr/bin/env bash
set -euo pipefail

backup="${1:-}"
mode="${2:---dry-run}"
if [[ -z "$backup" || "$backup" != /* || "$backup" == "/" || ! -e "$backup" ]]; then
  echo "usage: $0 ABSOLUTE_BACKUP_PATH [--apply]" >&2
  exit 2
fi
echo "backup=$backup"
echo "workflow=verify backup/checksum -> maintenance -> restore config/DB/manifests"
echo "then validate migrations -> reconcile Slurm/backend IDs -> detect orphans -> smoke test"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: nothing restored"
  exit 0
fi
echo "error: site-specific encrypted backup and PostgreSQL restore hooks are required" >&2
exit 1
