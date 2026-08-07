from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from llm_platform.common.errors import ConfigurationError
from llm_platform.common.subprocesses import CommandResult
from llm_platform.slurm.cli import CliSlurmAdapter, render_sbatch_script


class StubRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
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
        return self.results.pop(0)


def result(stdout: str = "", stderr: str = "", returncode: int = 0) -> CommandResult:
    return CommandResult(("stub",), returncode, stdout, stderr)


def test_sbatch_template_uses_validated_instance_comment(deployment_factory: Any) -> None:
    deployment = deployment_factory()
    script = render_sbatch_script(deployment, "instance-qwen")
    assert "#SBATCH --comment=instance-qwen" in script
    assert "--deployment qwen-vllm-1gpu" in script
    with pytest.raises(ConfigurationError):
        render_sbatch_script(deployment, "bad\n#SBATCH --gres=gpu:99")


@pytest.mark.asyncio
async def test_cli_submit_and_list_preserve_instance_mapping(deployment_factory: Any) -> None:
    runner = StubRunner(
        [result("1234;cluster\n"), result("1234|RUNNING|llm-qwen-vllm-1gpu|instance-qwen\n")]
    )
    adapter = CliSlurmAdapter(runner)
    deployment = deployment_factory()
    submitted = await adapter.submit_backend(
        deployment, "instance-qwen", Path("/run/llm-platform/backend.sbatch")
    )
    assert submitted.job_id == "1234"
    jobs = await adapter.list_jobs()
    assert jobs[0].instance_id == "instance-qwen"
    assert runner.argv[0][:2] == ("sbatch", "--parsable")
    assert "--format" in runner.argv[1]


@pytest.mark.asyncio
async def test_cli_rejects_non_numeric_job_id(deployment_factory: Any) -> None:
    adapter = CliSlurmAdapter(StubRunner([result("not-a-job\n")]))
    with pytest.raises(RuntimeError, match="invalid job ID"):
        await adapter.submit_backend(
            deployment_factory(), "instance-qwen", Path("/run/backend.sbatch")
        )
