import asyncio
import contextlib

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm_platform.config.schema import GpuProfile
from llm_platform.orchestrator.reconciler import Reconciler
from llm_platform.persistence.repositories import ControlPlaneStateRepository, RequestRepository
from llm_platform.queueing.fair import FairRequestQueue, QueueItem
from llm_platform.scheduler.planner import ResourcePlanner


class ControlPlane:
    """Long-running queue-to-profile reconciliation loop."""

    def __init__(
        self,
        reconciler: Reconciler,
        planner: ResourcePlanner,
        profiles: list[GpuProfile],
        sessions: async_sessionmaker[AsyncSession],
        *,
        interval_seconds: float = 2,
        max_users: int = 3,
        max_pending_per_user: int = 20,
    ) -> None:
        self.reconciler = reconciler
        self.planner = planner
        self.sessions = sessions
        self.interval_seconds = interval_seconds
        self.queue = FairRequestQueue(max_users, max_pending_per_user)
        self._profiles = {profile.name: profile for profile in profiles}
        self._desired_profile = "idle"
        self._wake = asyncio.Event()
        self._ready = asyncio.Condition()
        self._task: asyncio.Task[None] | None = None
        self.orphan_job_ids: tuple[str, ...] = ()

    async def start(self) -> None:
        self.orphan_job_ids = await self.reconciler.recover()
        async with self.sessions() as session:
            persisted = await ControlPlaneStateRepository(session).desired_profile()
        current = set(self.reconciler.instances)
        matching = [
            profile.name
            for profile in self._profiles.values()
            if set(profile.deployments) == current
        ]
        if persisted in self._profiles:
            self._desired_profile = persisted
        elif matching:
            self._desired_profile = sorted(matching)[0]
            async with self.sessions() as session:
                await ControlPlaneStateRepository(session).set_desired_profile(
                    self._desired_profile
                )
        self._task = asyncio.create_task(self._run(), name="control-plane-reconciler")

    async def set_desired_profile(self, profile: str) -> None:
        if profile not in self._profiles:
            raise ValueError(f"unknown GPU profile {profile}")
        async with self.sessions() as session:
            await ControlPlaneStateRepository(session).set_desired_profile(profile)
        self._desired_profile = profile
        self._wake.set()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    def _profile_for(self, deployment_id: str) -> str:
        candidates = [
            profile
            for profile in self._profiles.values()
            if deployment_id in profile.deployments
            and all(item in self.reconciler.deployments for item in profile.deployments)
        ]
        if not candidates:
            raise RuntimeError(f"no GPU profile contains deployment {deployment_id}")
        return min(candidates, key=lambda item: (len(item.deployments), item.name)).name

    async def wait_for_deployment(
        self,
        deployment_id: str,
        request_id: str,
        user_id: str,
        requested_model: str,
        body: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> None:
        item = QueueItem(request_id, user_id, deployment_id)
        self.queue.enqueue(item)
        async with self.sessions() as session:
            repository = RequestRepository(session)
            await repository.create(
                request_id=request_id,
                user_id=user_id,
                requested_model=requested_model,
                priority=item.queue_class.value,
                body=body,
            )
        already_ready = (
            deployment_id in self.reconciler.instances
            and self.reconciler.instances[deployment_id].state.value == "ready"
        )
        if not already_ready:
            await self.set_desired_profile(self._profile_for(deployment_id))
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self._ready:
                    await self._ready.wait_for(
                        lambda: (
                            deployment_id in self.reconciler.instances
                            and self.reconciler.instances[deployment_id].state.value == "ready"
                        )
                    )
            async with self.sessions() as session:
                await RequestRepository(session).transition(
                    request_id, {"queued"}, "assigned", selected_deployment=deployment_id
                )
            self.queue.assign(request_id)
        except BaseException:
            self.queue.cancel(request_id)
            async with self.sessions() as session:
                await RequestRepository(session).transition(
                    request_id, {"queued", "assigned"}, "failed", error_code="backend_unavailable"
                )
            raise

    async def request_started(self, request_id: str, deployment_id: str) -> None:
        async with self.sessions() as session:
            await RequestRepository(session).transition(
                request_id, {"assigned"}, "running", selected_deployment=deployment_id
            )

    async def request_finished(self, request_id: str, *, failed: bool = False) -> None:
        async with self.sessions() as session:
            await RequestRepository(session).transition(
                request_id,
                {"running", "assigned"},
                "failed" if failed else "completed",
                error_code="backend_error" if failed else None,
            )
        self.queue.complete(request_id)

    async def _run(self) -> None:
        while True:
            plan = self.planner.plan(self._desired_profile, set(self.reconciler.instances))
            await self.reconciler.reconcile(plan)
            async with self._ready:
                self._ready.notify_all()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass
