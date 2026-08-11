import asyncio
import json
import os
import re
from pathlib import Path

from llm_platform.common.errors import ConfigurationError
from llm_platform.common.subprocesses import AsyncioCommandRunner, CommandRunner
from llm_platform.config.schema import DeploymentConfig, SlurmConfig
from llm_platform.slurm.base import SlurmAdapter, SlurmJob, SlurmJobState

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _job_state(value: str) -> SlurmJobState:
    if value in {"RUNNING", "COMPLETING"}:
        return SlurmJobState.RUNNING
    if value in {"FAILED", "NODE_FAIL", "OUT_OF_MEMORY", "TIMEOUT"}:
        return SlurmJobState.FAILED
    if value == "CANCELLED":
        return SlurmJobState.CANCELLED
    if value == "COMPLETED":
        return SlurmJobState.COMPLETED
    return SlurmJobState.PENDING


def validate_identifier(value: str, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ConfigurationError(f"invalid {label}")
    return value


def render_sbatch_script(
    deployment: DeploymentConfig,
    instance_id: str,
    *,
    application_current: Path = Path("/opt/llm-platform/app/current"),
    config_dir: Path = Path("/etc/llm-platform"),
    qos: str | None = None,
    output_path: Path | None = None,
) -> str:
    validate_identifier(deployment.deployment_id, "deployment ID")
    validate_identifier(instance_id, "instance ID")
    directives = [
        f"#SBATCH --job-name=llm-{deployment.deployment_id}",
        f"#SBATCH --comment={instance_id}",
        f"#SBATCH --gres=gpu:{deployment.resources.gpus}",
        f"#SBATCH --cpus-per-task={deployment.resources.cpus}",
        f"#SBATCH --mem={deployment.resources.ram_gb}G",
    ]
    if qos is not None:
        validate_identifier(qos, "QOS")
        directives.append(f"#SBATCH --qos={qos}")
    if output_path is not None:
        if not output_path.is_absolute() or "\n" in str(output_path):
            raise ConfigurationError("invalid Slurm output path")
        directives.append(f"#SBATCH --output={output_path}")
    return "\n".join(
        ["#!/usr/bin/env bash", *directives, "", "set -euo pipefail"]
        + [
            "# Generated template: the service wrapper resolves the registered deployment.",
            (
                f"{application_current}/bin/llm-backend "
                f"--instance {instance_id} --deployment {deployment.deployment_id} "
                f"--config-dir {config_dir}"
            ),
            "",
        ]
    )


class CliSlurmAdapter(SlurmAdapter):
    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        application_current: Path = Path("/opt/llm-platform/app/current"),
        config_dir: Path = Path("/etc/llm-platform"),
        slurm_config: SlurmConfig | None = None,
    ) -> None:
        self._runner = runner or AsyncioCommandRunner()
        self._application_current = application_current
        self._config_dir = config_dir
        self._config = slurm_config or SlurmConfig()

    async def _submit(
        self, deployment: DeploymentConfig, instance_id: str, script_path: Path
    ) -> str:
        if self._config.submission_mode == "current_user":
            if os.environ.get("LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT") != "1":
                raise ConfigurationError(
                    "current-user Slurm submission requires "
                    "LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT=1"
                )
            _write_script(
                script_path,
                render_sbatch_script(
                    deployment,
                    instance_id,
                    application_current=self._application_current,
                    config_dir=self._config_dir,
                    qos=self._config.qos,
                ),
            )
            result = await self._runner.run(
                ("sbatch", "--parsable", str(script_path)), timeout_seconds=30
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"sbatch failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            return result.stdout
        response = await self._helper_request(
            {
                "operation": "submit",
                "deployment_id": deployment.deployment_id,
                "instance_id": instance_id,
            }
        )
        return str(response.get("stdout", ""))

    async def _helper_request(self, request: dict[str, str]) -> dict[str, object]:
        reader, writer = await asyncio.open_unix_connection(str(self._config.submit_socket))
        writer.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        await writer.drain()
        response_line = await asyncio.wait_for(reader.readline(), timeout=30)
        writer.close()
        await writer.wait_closed()
        if not response_line:
            raise RuntimeError("backend-submit helper closed without a response")
        response_object: object = json.loads(response_line)
        if not isinstance(response_object, dict):
            raise RuntimeError("backend-submit helper returned an invalid response")
        response = {str(key): value for key, value in response_object.items()}
        if not response.get("ok"):
            raise RuntimeError(f"sbatch failed: {response.get('error', 'unknown helper error')}")
        return response

    async def submit_backend(
        self, deployment: DeploymentConfig, instance_id: str, script_path: Path
    ) -> SlurmJob:
        validate_identifier(instance_id, "instance ID")
        if not script_path.is_absolute():
            raise ConfigurationError("sbatch script path must be absolute")
        stdout = await self._submit(deployment, instance_id, script_path)
        job_id = stdout.strip().split(";", 1)[0]
        if not job_id.isdigit():
            raise RuntimeError("sbatch returned an invalid job ID")
        return SlurmJob(job_id, instance_id, deployment.deployment_id, SlurmJobState.PENDING)

    async def inspect(self, job_id: str) -> SlurmJob | None:
        if not job_id.isdigit():
            raise ConfigurationError("invalid Slurm job ID")
        result = await self._runner.run(
            ("squeue", "--noheader", "--jobs", job_id, "--format", "%i|%T|%j|%k"),
            timeout_seconds=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"squeue failed: {result.stderr.strip()}")
        line = result.stdout.strip()
        if not line:
            return None
        fields = line.split("|", 3)
        if len(fields) != 4:
            raise RuntimeError("squeue returned an invalid job record")
        state = _job_state(fields[1])
        deployment_id = fields[2].removeprefix("llm-")
        return SlurmJob(fields[0], fields[3], deployment_id, state)

    async def cancel(self, job_id: str) -> None:
        if not job_id.isdigit():
            raise ConfigurationError("invalid Slurm job ID")
        if self._config.submission_mode == "helper":
            await self._helper_request({"operation": "cancel", "job_id": job_id})
            return
        result = await self._runner.run(("scancel", job_id), timeout_seconds=30)
        if result.returncode != 0:
            raise RuntimeError(f"scancel failed: {result.stderr.strip()}")

    async def list_jobs(self) -> list[SlurmJob]:
        job_user = (
            os.environ.get("USER", "")
            if self._config.submission_mode == "current_user"
            else self._config.job_user
        )
        result = await self._runner.run(
            ("squeue", "--noheader", "--user", job_user, "--format", "%i|%T|%j|%k"),
            timeout_seconds=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"squeue failed: {result.stderr.strip()}")
        jobs: list[SlurmJob] = []
        for line in result.stdout.splitlines():
            fields = line.split("|", 3)
            if len(fields) != 4:
                continue
            if not fields[2].startswith("llm-"):
                continue
            state = _job_state(fields[1])
            jobs.append(SlurmJob(fields[0], fields[3], fields[2].removeprefix("llm-"), state))
        return jobs

    async def accounting(self, job_id: str) -> dict[str, str]:
        if not job_id.isdigit():
            raise ConfigurationError("invalid Slurm job ID")
        result = await self._runner.run(
            (
                "sacct",
                "--noheader",
                "--parsable2",
                "--jobs",
                job_id,
                "--format",
                "JobID,User,QOS,AllocTRES,Start,End,ExitCode,Elapsed",
            ),
            timeout_seconds=30,
        )
        return {"raw": result.stdout.strip()}

    async def detect_orphans(self, known_instance_ids: set[str]) -> list[SlurmJob]:
        return [job for job in await self.list_jobs() if job.instance_id not in known_instance_ids]
