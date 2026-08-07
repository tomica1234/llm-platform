import re
from pathlib import Path

from llm_platform.common.errors import ConfigurationError
from llm_platform.common.subprocesses import AsyncioCommandRunner, CommandRunner
from llm_platform.config.schema import DeploymentConfig
from llm_platform.slurm.base import SlurmAdapter, SlurmJob, SlurmJobState

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_identifier(value: str, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ConfigurationError(f"invalid {label}")
    return value


def render_sbatch_script(deployment: DeploymentConfig, instance_id: str) -> str:
    validate_identifier(deployment.deployment_id, "deployment ID")
    validate_identifier(instance_id, "instance ID")
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"#SBATCH --job-name=llm-{deployment.deployment_id}",
            f"#SBATCH --comment={instance_id}",
            "#SBATCH --qos=agent-service",
            f"#SBATCH --gres=gpu:{deployment.resources.gpus}",
            f"#SBATCH --cpus-per-task={deployment.resources.cpus}",
            f"#SBATCH --mem={deployment.resources.ram_gb}G",
            "# Generated template: the service wrapper resolves the registered deployment.",
            (
                "/opt/llm-platform/gateway/current/bin/llm-backend "
                f"--instance {instance_id} --deployment {deployment.deployment_id}"
            ),
            "",
        ]
    )


class CliSlurmAdapter(SlurmAdapter):
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or AsyncioCommandRunner()

    async def submit_backend(
        self, deployment: DeploymentConfig, instance_id: str, script_path: Path
    ) -> SlurmJob:
        validate_identifier(instance_id, "instance ID")
        if not script_path.is_absolute():
            raise ConfigurationError("sbatch script path must be absolute")
        result = await self._runner.run(
            ("sbatch", "--parsable", str(script_path)), timeout_seconds=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"sbatch failed: {result.stderr.strip()}")
        job_id = result.stdout.strip().split(";", 1)[0]
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
        line = result.stdout.strip()
        if not line:
            return None
        fields = line.split("|", 3)
        if len(fields) != 4:
            raise RuntimeError("squeue returned an invalid job record")
        state = SlurmJobState.RUNNING if fields[1] == "RUNNING" else SlurmJobState.PENDING
        deployment_id = fields[2].removeprefix("llm-")
        return SlurmJob(fields[0], fields[3], deployment_id, state)

    async def cancel(self, job_id: str) -> None:
        if not job_id.isdigit():
            raise ConfigurationError("invalid Slurm job ID")
        result = await self._runner.run(("scancel", job_id), timeout_seconds=30)
        if result.returncode != 0:
            raise RuntimeError(f"scancel failed: {result.stderr.strip()}")

    async def list_jobs(self) -> list[SlurmJob]:
        result = await self._runner.run(
            ("squeue", "--noheader", "--name", "llm-*", "--format", "%i|%T|%j|%k"),
            timeout_seconds=30,
        )
        jobs: list[SlurmJob] = []
        for line in result.stdout.splitlines():
            fields = line.split("|", 3)
            if len(fields) != 4:
                continue
            state = SlurmJobState.RUNNING if fields[1] == "RUNNING" else SlurmJobState.PENDING
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
