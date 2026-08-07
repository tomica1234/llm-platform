#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

if command -v uv >/dev/null 2>&1; then
  uv sync --extra dev
  echo "Development environment ready. Run: uv run make PYTHON='uv run python' check"
  exit 0
fi

python_bin="${PYTHON_BIN:-python3}"
python_version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! "$python_bin" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
  echo "error: Python 3.12+ is required; found $python_version" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  "$python_bin" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
if [[ -f requirements.lock ]]; then
  .venv/bin/python -m pip install -r requirements.lock
  .venv/bin/python -m pip install --no-deps --no-build-isolation -e .
else
  .venv/bin/python -m pip install -e '.[dev]'
fi
echo "Development environment ready. Run: . .venv/bin/activate && make check"
