#!/usr/bin/env bash
set -euo pipefail

version="${VLLM_VERSION:-}"
release_root="${VLLM_RELEASE_ROOT:-/opt/llm-platform/runtimes/vllm/envs}"
mode="${1:---dry-run}"
if [[ ! "$release_root" = /* || "$release_root" == "/" ]]; then
  echo "error: release root must be a non-root absolute path" >&2
  exit 2
fi
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([a-zA-Z0-9.-]+)?$ ]]; then
  echo "error: set VLLM_VERSION to a reviewed exact version" >&2
  exit 2
fi
echo "package=vllm==$version target=$release_root/$version"
echo "workflow=create isolated venv -> install pinned constraints -> smoke test -> manifest"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: no files changed"
  exit 0
fi
echo "error: reviewed site constraints and CUDA wheel source are required before --apply" >&2
exit 1
