#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if git grep -n -E '(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|hf_[A-Za-z0-9]{24,}|sk-[A-Za-z0-9]{20,})' -- . ':!scripts/check-secrets.sh'; then
  echo "potential committed secret found" >&2
  exit 1
fi
echo "secret-pattern check passed"
