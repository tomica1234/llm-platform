import importlib
import signal
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest


def console_entry(name: str) -> Callable[[], None]:
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    module_name, attribute_name = pyproject["project"]["scripts"][name].split(":", 1)
    return cast(Callable[[], None], getattr(importlib.import_module(module_name), attribute_name))


@pytest.mark.parametrize("name", ["llm-platform", "llm-backend-submit", "llm-backend"])
def test_console_entry_point_help_succeeds(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = importlib.import_module("llm_platform.gateway.main")
    submit_helper = importlib.import_module("llm_platform.slurm.submit_helper")

    def unexpected(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        pytest.fail("help started the console command")

    monkeypatch.setattr(gateway, "load_bundle", unexpected)
    monkeypatch.setattr(gateway.uvicorn, "run", unexpected)
    monkeypatch.setattr(submit_helper.asyncio, "start_unix_server", unexpected)
    monkeypatch.setattr(sys, "argv", [name, "--help"])

    with pytest.raises(SystemExit) as exc_info:
        console_entry(name)()

    assert exc_info.value.code == 0


def test_gateway_console_entry_point_parses_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = importlib.import_module("llm_platform.gateway.main")
    config_dir = tmp_path / "reviewed-config"
    app = object()
    bundle = type(
        "Bundle",
        (),
        {
            "platform": type(
                "Platform",
                (),
                {
                    "gateway": type(
                        "Gateway",
                        (),
                        {"host": "host", "port": 1, "shutdown_grace_seconds": 5},
                    )()
                },
            )()
        },
    )()
    seen: list[Path] = []
    server_runs: list[tuple[object, str, int, int]] = []

    def fake_load_bundle(path: Path) -> Any:
        seen.append(path)
        return bundle

    def fake_build_app(path: Path) -> object:
        seen.append(path)
        return app

    monkeypatch.setattr(gateway, "configure_logging", lambda: None)
    monkeypatch.setattr(gateway, "load_bundle", fake_load_bundle)
    monkeypatch.setattr(gateway, "build_app", fake_build_app)

    class FakeConfig:
        def __init__(
            self,
            actual_app: object,
            *,
            host: str,
            port: int,
            timeout_graceful_shutdown: int,
        ) -> None:
            self.values = (actual_app, host, port, timeout_graceful_shutdown)

    class FakeServer:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config

        def run(self) -> None:
            server_runs.append(self.config.values)

    monkeypatch.setattr(gateway.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(gateway, "GatewayServer", FakeServer)
    monkeypatch.setattr(sys, "argv", ["llm-platform", "--config", str(config_dir)])

    with pytest.raises(SystemExit) as exc_info:
        console_entry("llm-platform")()

    assert exc_info.value.code == 0
    assert seen == [config_dir, config_dir]
    assert server_runs == [(app, "host", 1, 5)]


def test_gateway_server_notifies_control_plane_before_uvicorn_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = importlib.import_module("llm_platform.gateway.main")
    notifications: list[str] = []
    parent_calls: list[int] = []
    control_plane = SimpleNamespace(begin_shutdown=lambda: notifications.append("control-plane"))
    server = object.__new__(gateway.GatewayServer)
    server.config = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(control_plane=control_plane))
    )
    monkeypatch.setattr(
        gateway.uvicorn.Server,
        "handle_exit",
        lambda self, sig, frame: parent_calls.append(sig),
    )

    server.handle_exit(signal.SIGTERM, None)

    assert notifications == ["control-plane"]
    assert parent_calls == [signal.SIGTERM]


def test_submit_console_entry_point_parses_all_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submit_helper = importlib.import_module("llm_platform.slurm.submit_helper")
    config = tmp_path / "config"
    socket = tmp_path / "run" / "submit.sock"
    spool = tmp_path / "spool"
    log_dir = tmp_path / "logs"
    seen: list[tuple[Path, Path, Path, Path]] = []

    async def fake_serve(actual_socket: Path, service: Any) -> None:
        seen.append((service.config_dir, actual_socket, service.spool_dir, service.log_dir))

    monkeypatch.setattr(submit_helper, "serve", fake_serve)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-backend-submit",
            "--config",
            str(config),
            "--socket",
            str(socket),
            "--spool",
            str(spool),
            "--log-dir",
            str(log_dir),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        console_entry("llm-backend-submit")()

    assert exc_info.value.code == 0
    assert seen == [(config, socket, spool, log_dir)]
