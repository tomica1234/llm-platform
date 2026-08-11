import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from llm_platform.common.errors import ConfigurationError
from llm_platform.config.schema import SlurmConfig
from llm_platform.slurm.cli import CliSlurmAdapter
from llm_platform.slurm.submit_helper import SubmitRequest


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
        "deployment_id": "qwen-vllm-1gpu",
        "instance_id": "instance-qwen",
    }
    assert not (tmp_path / "unused.sbatch").exists()
