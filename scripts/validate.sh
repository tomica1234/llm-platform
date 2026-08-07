#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
python_bin="${PYTHON_BIN:-.venv/bin/python}"
"$python_bin" -m llm_platform.admin_cli.main config validate --config-dir config
"$python_bin" -m ruff format --check .
"$python_bin" -m ruff check .
"$python_bin" -m mypy src
"$python_bin" -m pytest -m 'not hardware'
