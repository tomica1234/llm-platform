#!/usr/bin/env bash
set -euo pipefail

destination="${1:-}"
if [[ -z "$destination" || "$destination" != /* || "$destination" == "/" ]]; then
  echo "usage: $0 ABSOLUTE_DESTINATION [--apply]" >&2
  exit 2
fi
mode="${2:---dry-run}"
echo "destination=$destination"
echo "include=config, database dump, manifests, benchmarks, policies, release manifests, runbooks"
echo "exclude=API keys, tokens, prompt bodies, public model weights unless explicitly selected"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: no backup created"
  exit 0
fi
echo "error: site-specific encrypted backup transport must be configured" >&2
exit 1
