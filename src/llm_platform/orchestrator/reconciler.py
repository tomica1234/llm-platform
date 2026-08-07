import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from llm_platform.common.enums import BackendState
from llm_platform.config.schema import DeploymentConfig
from llm_platform.runtimes.base import Allocation, RuntimeAdapter, RuntimeInstance
from llm_platform.scheduler.planner import ProfilePlan
from llm_platform.slurm.base import SlurmAdapter


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    started: tuple[str, ...]
    stopped: tuple[str, ...]
    kept: tuple[str, ...]
    blocked: bool = False


class Reconciler:
    def __init__(
        self,
        deployments: Mapping[str, DeploymentConfig],
        runtime_adapters: Mapping[str, RuntimeAdapter],
        slurm: SlurmAdapter,
        *,
        drain_timeout: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.deployments = deployments
        self.runtime_adapters = runtime_adapters
        self.slurm = slurm
        self.drain_timeout = drain_timeout
        self.clock = clock
        self.instances: dict[str, RuntimeInstance] = {}

    async def _drain_and_stop(self, deployment_id: str) -> bool:
        instance = self.instances[deployment_id]
        adapter = self.runtime_adapters[deployment_id]
        await adapter.drain(instance)
        deadline = self.clock() + self.drain_timeout
        while instance.active_requests:
            if self.clock() >= deadline:
                instance.state = BackendState.TIMEOUT
                return False
            await asyncio.sleep(0)
        await adapter.stop(instance)
        if instance.allocation_id is not None:
            await self.slurm.cancel(instance.allocation_id)
        self.instances.pop(deployment_id)
        return True

    async def reconcile(self, plan: ProfilePlan) -> ReconcileResult:
        if plan.blocked_by_protected_job:
            return ReconcileResult((), (), plan.keep, True)
        stopped: list[str] = []
        for deployment_id in plan.drain:
            if deployment_id not in self.instances:
                continue
            if await self._drain_and_stop(deployment_id):
                stopped.append(deployment_id)
            else:
                return ReconcileResult((), tuple(stopped), plan.keep, True)
        started: list[str] = []
        for deployment_id in plan.start:
            if deployment_id in self.instances:
                continue
            deployment = self.deployments[deployment_id]
            instance_id = f"instance-{deployment_id}"
            job = await self.slurm.submit_backend(
                deployment, instance_id, Path(f"/run/llm-platform/{instance_id}.sbatch")
            )
            allocation = Allocation(
                job.job_id, job.gpu_ids, deployment.resources.cpus, deployment.resources.ram_gb
            )
            adapter = self.runtime_adapters[deployment_id]
            instance = await adapter.start(deployment, allocation)
            instance.state = BackendState.WARMING
            await adapter.warmup(instance)
            self.instances[deployment_id] = instance
            started.append(deployment_id)
        return ReconcileResult(tuple(started), tuple(stopped), plan.keep)

    async def recover(self) -> tuple[str, ...]:
        jobs = await self.slurm.list_jobs()
        known = {instance.instance_id for instance in self.instances.values()}
        return tuple(job.job_id for job in jobs if job.instance_id not in known)
