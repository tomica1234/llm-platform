import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llm_platform.common.errors import ConfigurationError
from llm_platform.common.subprocesses import CommandResult
from llm_platform.config.schema import SlurmConfig
from llm_platform.slurm.cli import CliSlurmAdapter
from llm_platform.slurm.submit_helper import SubmitRequest, SubmitService


class StubRunner:
    def __init__(self, response: CommandResult) -> None:
        self.response = response
        self.argv: list[tuple[str, ...]] = []

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        del cwd, env, timeout_seconds
        self.argv.append(tuple(argv))
        return self.response


def command_result(stdout: str = "", stderr: str = "", returncode: int = 0) -> CommandResult:
    return CommandResult(("stub",), returncode, stdout, stderr)


def configure_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    deployment: Any,
    response: CommandResult,
) -> tuple[SubmitService, StubRunner]:
    bundle = SimpleNamespace(
        deployments=SimpleNamespace(deployments=[deployment]),
        platform=SimpleNamespace(slurm=SimpleNamespace(qos="agent-service")),
    )
    monkeypatch.setattr("llm_platform.slurm.submit_helper.load_bundle", lambda _: bundle)
    runner = StubRunner(response)
    service = SubmitService(
        tmp_path / "config",
        tmp_path / "spool",
        tmp_path / "logs",
        runner,
        application_current=Path("/opt/reviewed/current"),
    )
    return service, runner


def test_submit_helper_accepts_only_typed_identifiers() -> None:
    request = SubmitRequest(
        {"operation": "submit", "deployment_id": "qwen-vllm", "instance_id": "instance-1"}
    )
    assert request.deployment_id == "qwen-vllm"


@pytest.mark.parametrize(
    "injected",
    [
        {"executable": "/bin/sh"},
        {"args": ["-c", "id"]},
        {"environment": {"LD_PRELOAD": "/tmp/evil.so"}},
        {"output_path": "/etc/cron.d/evil"},
        {"instance_id": "ok\n#SBATCH --uid=root"},
    ],
)
def test_submit_helper_rejects_arbitrary_launch_fields(injected: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "operation": "submit",
        "deployment_id": "qwen-vllm",
        "instance_id": "instance-1",
    }
    payload.update(injected)
    with pytest.raises((ValueError, ConfigurationError)):
        SubmitRequest(payload)


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "unexpected fields"),
        ({"operation": "status", "deployment_id": "qwen", "instance_id": "i"}, "operation"),
        ({"operation": "submit", "deployment_id": 1, "instance_id": "i"}, "strings"),
        (
            {"operation": "submit", "deployment_id": "../qwen", "instance_id": "i"},
            "invalid deployment ID",
        ),
    ],
)
def test_submit_request_rejects_malformed_protocol(payload: Any, message: str) -> None:
    with pytest.raises((ValueError, ConfigurationError), match=message):
        SubmitRequest(payload)


@pytest.mark.asyncio
async def test_helper_resolves_reviewed_deployment_and_submits_fixed_command(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, runner = configure_service(
        monkeypatch, tmp_path, deployment_factory(), command_result("1234;cluster\n")
    )

    response = await service.submit(
        {
            "operation": "submit",
            "deployment_id": "example-b-vllm-1gpu",
            "instance_id": "instance-qwen",
        }
    )

    script_path = tmp_path / "spool" / "instance-qwen.sbatch"
    assert response == {"ok": True, "stdout": "1234;cluster\n"}
    assert runner.argv == [("sbatch", "--parsable", str(script_path))]
    script = script_path.read_text(encoding="utf-8")
    assert "#SBATCH --qos=agent-service" in script
    assert f"#SBATCH --output={tmp_path}/logs/instance-qwen.log" in script
    assert "/opt/reviewed/current/bin/llm-backend" in script
    assert str(deployment_factory().executable) not in script


@pytest.mark.asyncio
async def test_helper_rejects_unknown_or_disabled_deployment_without_sbatch(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, runner = configure_service(
        monkeypatch,
        tmp_path,
        deployment_factory(enabled=False),
        command_result("1234\n"),
    )

    response = await service.submit(
        {"operation": "submit", "deployment_id": "unknown", "instance_id": "instance-1"}
    )

    assert response["ok"] is False
    assert "not uniquely enabled" in str(response["error"])
    assert runner.argv == []


@pytest.mark.asyncio
async def test_helper_propagates_sbatch_failure_without_claiming_a_job(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = configure_service(
        monkeypatch,
        tmp_path,
        deployment_factory(),
        command_result(stderr="invalid account", returncode=1),
    )

    response = await service.submit(
        {
            "operation": "submit",
            "deployment_id": "example-b-vllm-1gpu",
            "instance_id": "instance-1",
        }
    )

    assert response == {"ok": False, "error": "invalid account"}


@pytest.mark.asyncio
async def test_helper_rejects_invalid_sbatch_job_id(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = configure_service(
        monkeypatch, tmp_path, deployment_factory(), command_result("not-a-job\n")
    )
    response = await service.submit(
        {
            "operation": "submit",
            "deployment_id": "example-b-vllm-1gpu",
            "instance_id": "instance-1",
        }
    )
    assert response == {"ok": False, "error": "sbatch returned an invalid job ID"}


@pytest.mark.asyncio
async def test_helper_cancel_accepts_only_numeric_job_id(tmp_path: Path) -> None:
    runner = StubRunner(command_result())
    service = SubmitService(tmp_path / "config", tmp_path / "spool", tmp_path / "logs", runner)

    rejected = await service.dispatch({"operation": "cancel", "job_id": "1;id"})
    accepted = await service.dispatch({"operation": "cancel", "job_id": "1234"})

    assert rejected == {"ok": False, "error": "invalid Slurm job ID"}
    assert accepted == {"ok": True}
    assert runner.argv == [("scancel", "1234")]


@pytest.mark.asyncio
async def test_unix_socket_handler_returns_structured_malformed_request_error(
    tmp_path: Path,
) -> None:
    service = SubmitService(tmp_path / "config", tmp_path / "spool", tmp_path / "logs")
    reader = asyncio.StreamReader()
    reader.feed_data(b"not-json\n")
    reader.feed_eof()
    written = bytearray()

    class Writer:
        def write(self, data: bytes) -> None:
            written.extend(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    await service.handle(reader, Writer())  # type: ignore[arg-type]
    response = json.loads(written)

    assert response["ok"] is False
    assert "invalid request" in response["error"]


@pytest.mark.asyncio
async def test_production_mode_submits_through_unix_helper(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_path = tmp_path / "submit.sock"
    written = bytearray()

    reader = asyncio.StreamReader()
    reader.feed_data(b'{"ok":true,"stdout":"4321;cluster\\n"}\n')
    reader.feed_eof()

    class Writer:
        def write(self, data: bytes) -> None:
            written.extend(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def connect(path: str) -> tuple[asyncio.StreamReader, Writer]:
        assert path == str(socket_path)
        return reader, Writer()

    monkeypatch.setattr(asyncio, "open_unix_connection", connect)
    adapter = CliSlurmAdapter(
        slurm_config=SlurmConfig(submission_mode="helper", submit_socket=socket_path)
    )
    job = await adapter.submit_backend(
        deployment_factory(), "instance-qwen", tmp_path / "unused.sbatch"
    )
    assert job.job_id == "4321"
    assert json.loads(written) == {
        "operation": "submit",
        "deployment_id": "example-b-vllm-1gpu",
        "instance_id": "instance-qwen",
    }
    assert not (tmp_path / "unused.sbatch").exists()
