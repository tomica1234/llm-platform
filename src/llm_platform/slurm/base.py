from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from llm_platform.config.schema import DeploymentConfig


class SlurmJobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class SlurmJob:
    job_id: str
    instance_id: str
    deployment_id: str
    state: SlurmJobState
    gpu_ids: tuple[str, ...] = ()
    exit_code: int | None = None
    preemptible: bool = False


class SlurmAdapter(ABC):
    @abstractmethod
    async def submit_backend(
        self, deployment: DeploymentConfig, instance_id: str, script_path: Path
    ) -> SlurmJob: ...

    @abstractmethod
    async def inspect(self, job_id: str) -> SlurmJob | None: ...

    @abstractmethod
    async def cancel(self, job_id: str) -> None: ...

    @abstractmethod
    async def list_jobs(self) -> list[SlurmJob]: ...

    @abstractmethod
    async def accounting(self, job_id: str) -> dict[str, str]: ...

    @abstractmethod
    async def detect_orphans(self, known_instance_ids: set[str]) -> list[SlurmJob]: ...
