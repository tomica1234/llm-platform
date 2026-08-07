#!/usr/bin/env bash
set -euo pipefail

revision="${LLAMA_CPP_REVISION:-}"
release_root="${LLAMA_CPP_RELEASE_ROOT:-/opt/llm-platform/runtimes/llama.cpp/releases}"
mode="${1:---dry-run}"
if [[ ! "$release_root" = /* || "$release_root" == "/" ]]; then
  echo "error: release root must be a non-root absolute path" >&2
  exit 2
fi
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "error: set LLAMA_CPP_REVISION to a reviewed 40-character commit" >&2
  exit 2
fi
target="$release_root/$revision"
echo "source=https://github.com/ggml-org/llama.cpp.git revision=$revision target=$target"
echo "commands: clone exact revision; cmake -DGGML_CUDA=ON; build; test; record manifest"
if [[ "$mode" == "--dry-run" ]]; then
  echo "dry-run: no files changed"
  exit 0
fi
if [[ "$mode" != "--apply" ]]; then
  echo "error: use --dry-run or --apply" >&2
  exit 2
fi
echo "error: reviewed site packaging hook required before privileged release creation" >&2
exit 1
