from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from llm_platform.common.errors import ConfigurationError
from llm_platform.common.subprocesses import CommandResult
from llm_platform.config.schema import SlurmConfig
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
    assert "#SBATCH --uid" not in script
    assert "#SBATCH --qos" not in script
    assert "/opt/llm-platform/app/current/bin/llm-backend" in script
    assert "--deployment example-b-vllm-1gpu" in script
    with pytest.raises(ConfigurationError):
        render_sbatch_script(deployment, "bad\n#SBATCH --gres=gpu:99")


def test_sbatch_directives_precede_first_shell_command(deployment_factory: Any) -> None:
    script = render_sbatch_script(
        deployment_factory(),
        "instance-qwen",
        qos="agent-service",
        output_path=Path("/tmp/instance-qwen.log"),
    )
    lines = script.splitlines()

    assert lines[0] == "#!/usr/bin/env bash"
    first_shell_line = next(
        index
        for index, line in enumerate(lines[1:], start=1)
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert lines[first_shell_line] == "set -euo pipefail"
    assert all(not line.lstrip().startswith("#SBATCH") for line in lines[first_shell_line + 1 :])


def test_sbatch_template_includes_configured_qos(deployment_factory: Any) -> None:
    script = render_sbatch_script(deployment_factory(), "instance-qwen", qos="agent-service")
    assert "#SBATCH --qos=agent-service" in script
    with pytest.raises(ConfigurationError, match="invalid QOS"):
        render_sbatch_script(deployment_factory(), "instance-qwen", qos="bad\n#SBATCH --uid=root")


@pytest.mark.asyncio
async def test_cli_submit_and_list_preserve_instance_mapping(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = StubRunner(
        [result("1234;cluster\n"), result("1234|RUNNING|llm-example-b-vllm-1gpu|instance-qwen\n")]
    )
    monkeypatch.setenv("LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT", "1")
    monkeypatch.setenv("USER", "shunta")
    adapter = CliSlurmAdapter(runner, slurm_config=SlurmConfig(submission_mode="current_user"))
    deployment = deployment_factory()
    submitted = await adapter.submit_backend(
        deployment, "instance-qwen", tmp_path / "backend.sbatch"
    )
    assert submitted.job_id == "1234"
    assert (tmp_path / "backend.sbatch").is_file()
    jobs = await adapter.list_jobs()
    assert jobs[0].instance_id == "instance-qwen"
    assert runner.argv[0][:2] == ("sbatch", "--parsable")
    assert "--format" in runner.argv[1]


@pytest.mark.asyncio
async def test_cli_rejects_non_numeric_job_id(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT", "1")
    adapter = CliSlurmAdapter(
        StubRunner([result("not-a-job\n")]),
        slurm_config=SlurmConfig(submission_mode="current_user"),
    )
    with pytest.raises(RuntimeError, match="invalid job ID"):
        await adapter.submit_backend(
            deployment_factory(), "instance-qwen", tmp_path / "backend.sbatch"
        )


@pytest.mark.asyncio
async def test_current_user_mode_requires_explicit_environment(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT", raising=False)
    adapter = CliSlurmAdapter(
        StubRunner([]), slurm_config=SlurmConfig(submission_mode="current_user")
    )
    with pytest.raises(ConfigurationError, match="requires"):
        await adapter.submit_backend(
            deployment_factory(), "instance-qwen", tmp_path / "backend.sbatch"
        )


@pytest.mark.asyncio
async def test_current_user_submit_propagates_sbatch_failure(
    deployment_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT", "1")
    adapter = CliSlurmAdapter(
        StubRunner([result(stderr="QOS rejected", returncode=1)]),
        slurm_config=SlurmConfig(submission_mode="current_user", qos="agent-service"),
    )
    with pytest.raises(RuntimeError, match="sbatch failed: QOS rejected"):
        await adapter.submit_backend(
            deployment_factory(), "instance-qwen", tmp_path / "backend.sbatch"
        )
    assert "#SBATCH --qos=agent-service" in (tmp_path / "backend.sbatch").read_text()


@pytest.mark.asyncio
async def test_inspect_rejects_command_failure_and_malformed_record() -> None:
    failed = CliSlurmAdapter(StubRunner([result(stderr="controller unavailable", returncode=1)]))
    with pytest.raises(RuntimeError, match="squeue failed: controller unavailable"):
        await failed.inspect("123")

    malformed = CliSlurmAdapter(StubRunner([result("123|RUNNING|missing-comment\n")]))
    with pytest.raises(RuntimeError, match="invalid job record"):
        await malformed.inspect("123")


@pytest.mark.asyncio
async def test_list_jobs_propagates_failure() -> None:
    adapter = CliSlurmAdapter(StubRunner([result(stderr="permission denied", returncode=1)]))
    with pytest.raises(RuntimeError, match="squeue failed: permission denied"):
        await adapter.list_jobs()


@pytest.mark.asyncio
async def test_current_user_cancel_propagates_failure() -> None:
    adapter = CliSlurmAdapter(
        StubRunner([result(stderr="job already finished", returncode=1)]),
        slurm_config=SlurmConfig(submission_mode="current_user"),
    )
    with pytest.raises(RuntimeError, match="scancel failed: job already finished"):
        await adapter.cancel("123")
