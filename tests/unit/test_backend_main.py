import importlib
import sys
import tomllib
from pathlib import Path

import pytest


def test_console_entry_point_invokes_typer(monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    entry_point = pyproject["project"]["scripts"]["llm-backend"]
    module_name, attribute_name = entry_point.split(":", 1)
    entry = getattr(importlib.import_module(module_name), attribute_name)
    monkeypatch.setattr(sys, "argv", ["llm-backend", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        entry()

    assert exc_info.value.code == 0
