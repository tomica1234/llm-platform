#!/usr/bin/env bash
set -euo pipefail

component="${1:-}"
version="${2:-}"
mode="${3:---dry-run}"
if [[ ! "$component" =~ ^(gateway|harness|llama.cpp|vllm)$ || ! "$version" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "usage: $0 COMPONENT VERSION [--apply]" >&2
  exit 2
fi
echo "verify target release exists and its manifest/checksum is valid"
echo "drain affected requests, repoint current symlink to $version, restart, verify health"
echo "preserve failed release and audit event for diagnosis"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: no files changed and no service restarted"
  exit 0
fi
echo "error: site-specific service-control hook required before --apply" >&2
exit 1
