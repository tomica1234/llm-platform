#!/usr/bin/env bash
set -euo pipefail

manifest="${1:-}"
mode="${2:---dry-run}"
if [[ -z "$manifest" || ! -f "$manifest" ]]; then
  echo "usage: $0 MANIFEST [--apply]" >&2
  exit 2
fi
manifest_abs="$(cd -- "$(dirname -- "$manifest")" && pwd)/$(basename -- "$manifest")"
echo "manifest=$manifest_abs"
echo "workflow=license -> checksum -> malware review -> disabled registration -> benchmark -> enable"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: model remains unregistered"
  exit 0
fi
echo "error: registry admin API credentials must be supplied via protected environment" >&2
exit 1
