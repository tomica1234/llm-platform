from pathlib import Path

from llm_platform.config.schema import DeploymentConfig
from llm_platform.slurm.base import SlurmAdapter, SlurmJob, SlurmJobState


class FakeSlurmAdapter(SlurmAdapter):
    def __init__(self, total_gpus: int = 3) -> None:
        self.total_gpus = total_gpus
        self.jobs: dict[str, SlurmJob] = {}
        self.protected_batch_gpus = 0
        self._next_id = 1000

    def available_gpus(self) -> int:
        used = sum(
            len(job.gpu_ids)
            for job in self.jobs.values()
            if job.state in {SlurmJobState.PENDING, SlurmJobState.RUNNING}
        )
        return self.total_gpus - self.protected_batch_gpus - used

    async def submit_backend(
        self, deployment: DeploymentConfig, instance_id: str, script_path: Path
    ) -> SlurmJob:
        del script_path
        if deployment.resources.gpus > self.available_gpus():
            raise RuntimeError("insufficient unprotected GPU capacity")
        job_id = str(self._next_id)
        self._next_id += 1
        allocated = tuple(str(i) for i in range(deployment.resources.gpus))
        job = SlurmJob(
            job_id,
            instance_id,
            deployment.deployment_id,
            SlurmJobState.RUNNING,
            allocated,
        )
        self.jobs[job_id] = job
        return job

    async def inspect(self, job_id: str) -> SlurmJob | None:
        return self.jobs.get(job_id)

    async def cancel(self, job_id: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].state = SlurmJobState.CANCELLED

    async def list_jobs(self) -> list[SlurmJob]:
        return list(self.jobs.values())

    async def accounting(self, job_id: str) -> dict[str, str]:
        job = self.jobs[job_id]
        return {
            "job_id": job.job_id,
            "state": job.state,
            "gpus": str(len(job.gpu_ids)),
        }

    async def detect_orphans(self, known_instance_ids: set[str]) -> list[SlurmJob]:
        return [job for job in self.jobs.values() if job.instance_id not in known_instance_ids]
