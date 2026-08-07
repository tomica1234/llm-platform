#!/usr/bin/env bash
set -euo pipefail

deployment_id="${1:-}"
mode="${2:---dry-run}"
if [[ ! "$deployment_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "usage: $0 DEPLOYMENT_ID [--run]" >&2
  exit 2
fi
if [[ "$mode" != "--dry-run" && "$mode" != "--run" ]]; then
  echo "error: second argument must be --dry-run or --run" >&2
  exit 2
fi
echo "deployment=$deployment_id"
echo "workflow=validate manifest -> health -> warmup -> single/concurrent latency -> memory -> quality"
echo "output=reviewed benchmark manifest; deployment remains disabled until accepted"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: no request sent"
  exit 0
fi
echo "error: bind a site-specific benchmark client before --run; no benchmark was fabricated" >&2
exit 1
