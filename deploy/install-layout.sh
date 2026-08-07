#!/usr/bin/env bash
set -euo pipefail

operation="${1:---dry-run}"
entries=(
  "svc-control:svc-control:0750:/var/lib/llm-platform"
  "svc-control:svc-control:0750:/var/log/llm-platform"
  "svc-llm:svc-llm:0700:/scratch/svc-llm"
  "svc-models:modelusers:0750:/srv/models"
  "svc-models:modelusers:0750:/srv/cache/huggingface/hub"
  "root:root:0755:/opt/llm-platform"
  "root:svc-control:0750:/etc/llm-platform"
)
for entry in "${entries[@]}"; do
  IFS=: read -r owner group permissions path <<<"$entry"
  echo "directory path=$path owner=$owner group=$group mode=$permissions"
done
if [[ "$operation" == "--dry-run" ]]; then
  echo "dry-run: no accounts or directories created"
  exit 0
fi
echo "error: account creation and privileged directory changes must be reviewed and applied manually" >&2
exit 1
