#!/usr/bin/env bash
set -euo pipefail

component="${1:-}"
version="${2:-}"
mode="${3:---dry-run}"
if [[ ! "$component" =~ ^(gateway|harness)$ || ! "$version" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "usage: $0 gateway|harness VERSION [--apply]" >&2
  exit 2
fi
release_root="/opt/llm-platform/$component/releases"
target="$release_root/$version"
current="/opt/llm-platform/$component/current"
echo "validate artifact and manifest at $target"
echo "run offline migrations check and smoke tests"
echo "atomically repoint $current only after health passes"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: no files changed and no service restarted"
  exit 0
fi
echo "error: this reviewed template intentionally requires site integration for --apply" >&2
exit 1
