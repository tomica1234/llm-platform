import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from llm_platform.common.enums import BackendState
from llm_platform.config.schema import DeploymentConfig
from llm_platform.gateway.service import DeploymentRegistry
from llm_platform.runtimes.base import Allocation, RuntimeAdapter, RuntimeInstance
from llm_platform.runtimes.external import ExternalRuntimeAdapter
from llm_platform.scheduler.planner import ProfilePlan
from llm_platform.scheduler.policy import CircuitBreaker
from llm_platform.slurm.base import SlurmAdapter


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    started: tuple[str, ...]
    stopped: tuple[str, ...]
    kept: tuple[str, ...]
    blocked: bool = False
    failures: tuple["ReconcileFailure", ...] = ()


@dataclass(frozen=True, slots=True)
class ReconcileFailure:
    deployment_id: str
    operation: str
    reason: str


class Reconciler:
    def __init__(
        self,
        deployments: Mapping[str, DeploymentConfig],
        runtime_adapters: Mapping[str, RuntimeAdapter],
        slurm: SlurmAdapter,
        *,
        drain_timeout: float = 300,
        health_timeout: float = 30,
        registry: DeploymentRegistry | None = None,
        slurm_managed_runtime: bool = False,
        retry_budget: int = 3,
        script_directory: Path = Path("/var/lib/llm-platform/slurm"),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.deployments = deployments
        self.runtime_adapters = runtime_adapters
        self.slurm = slurm
        self.drain_timeout = drain_timeout
        self.health_timeout = health_timeout
        self.registry = registry
        self.slurm_managed_runtime = slurm_managed_runtime
        self.script_directory = script_directory
        self.clock = clock
        self.instances: dict[str, RuntimeInstance] = {}
        self.breaker = CircuitBreaker(
            failure_threshold=max(1, retry_budget), cooldown_seconds=300, clock=clock
        )

    def _publish(self, deployment_id: str, instance: RuntimeInstance) -> None:
        if self.registry is not None:
            self.registry.register(deployment_id, self.runtime_adapters[deployment_id], instance)

    def _unpublish(self, deployment_id: str) -> None:
        if self.registry is not None:
            self.registry.unregister(deployment_id)

    async def _wait_until_ready(self, deployment_id: str, instance: RuntimeInstance) -> bool:
        adapter = self.runtime_adapters[deployment_id]
        deadline = self.clock() + self.health_timeout
        instance.state = BackendState.STARTING
        while self.clock() < deadline:
            job = await self.slurm.inspect(instance.allocation_id or "")
            if job is None or job.state.value in {"failed", "cancelled", "completed"}:
                break
            if await adapter.health(instance):
                instance.state = BackendState.READY
                self.breaker.record_success(deployment_id)
                self._publish(deployment_id, instance)
                return True
            await asyncio.sleep(0.25)
        instance.state = BackendState.FAILED
        instance.failure_reason = "backend did not become healthy before timeout"
        self.breaker.record_failure(deployment_id)
        self._unpublish(deployment_id)
        return False

    async def _drain_and_stop(self, deployment_id: str) -> bool:
        instance = self.instances[deployment_id]
        adapter = self.runtime_adapters[deployment_id]
        await adapter.drain(instance)
        self._unpublish(deployment_id)
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
            if not self.breaker.allow_attempt(deployment_id):
                continue
            instance_id = f"instance-{deployment_id}"
            # Submission failures are operational status, not control-plane process death.
            try:
                job = await self.slurm.submit_backend(
                    deployment, instance_id, self.script_directory / f"{instance_id}.sbatch"
                )
            except Exception as exc:
                self.breaker.record_failure(deployment_id)
                return ReconcileResult(
                    tuple(started),
                    tuple(stopped),
                    plan.keep,
                    failures=(ReconcileFailure(deployment_id, "submit", str(exc)),),
                )
            allocation = Allocation(
                job.job_id, job.gpu_ids, deployment.resources.cpus, deployment.resources.ram_gb
            )
            adapter = self.runtime_adapters[deployment_id]
            if self.slurm_managed_runtime:
                if not isinstance(adapter, ExternalRuntimeAdapter):
                    raise TypeError("Slurm-managed deployments require an external runtime adapter")
                instance = await adapter.attach(deployment, job.job_id, instance_id)
            else:
                instance = await adapter.start(deployment, allocation)
            self.instances[deployment_id] = instance
            if self.slurm_managed_runtime:
                if await self._wait_until_ready(deployment_id, instance):
                    started.append(deployment_id)
                else:
                    await self.slurm.cancel(job.job_id)
                    self.instances.pop(deployment_id, None)
            else:
                instance.state = BackendState.WARMING
                await adapter.warmup(instance)
                self._publish(deployment_id, instance)
                started.append(deployment_id)
        return ReconcileResult(tuple(started), tuple(stopped), plan.keep)

    async def recover(self) -> tuple[str, ...]:
        jobs = await self.slurm.list_jobs()
        orphans: list[str] = []
        for job in jobs:
            deployment = self.deployments.get(job.deployment_id)
            adapter = self.runtime_adapters.get(job.deployment_id)
            if deployment is None or adapter is None or not deployment.enabled:
                orphans.append(job.job_id)
                continue
            if job.deployment_id in self.instances:
                continue
            if not isinstance(adapter, ExternalRuntimeAdapter):
                orphans.append(job.job_id)
                continue
            instance = await adapter.attach(deployment, job.job_id, job.instance_id)
            self.instances[job.deployment_id] = instance
            await self._wait_until_ready(job.deployment_id, instance)
        return tuple(orphans)
