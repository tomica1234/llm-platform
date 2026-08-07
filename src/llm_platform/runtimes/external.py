import uuid
from abc import abstractmethod
from collections.abc import AsyncIterator, Mapping
from typing import Any

from llm_platform.common.enums import BackendState
from llm_platform.common.errors import ConfigurationError
from llm_platform.config.schema import DeploymentConfig
from llm_platform.runtimes.base import (
    Allocation,
    LaunchSpec,
    RuntimeAdapter,
    RuntimeInstance,
    RuntimeMetrics,
)
from llm_platform.runtimes.http import RuntimeHttpClient
from llm_platform.runtimes.process import LocalProcessSupervisor, ProcessSupervisor


class ExternalRuntimeAdapter(RuntimeAdapter):
    def __init__(
        self,
        supervisor: ProcessSupervisor | None = None,
        http_client: RuntimeHttpClient | None = None,
    ) -> None:
        self._supervisor = supervisor or LocalProcessSupervisor()
        self._http = http_client or RuntimeHttpClient()

    async def validate(self, deployment: DeploymentConfig) -> None:
        if deployment.resources.gpus < 1:
            raise ConfigurationError("GPU runtime deployment requires at least one GPU")
        if deployment.serving.host not in {"127.0.0.1", "::1", "localhost"}:
            raise ConfigurationError("runtime must bind to loopback")
        if not deployment.executable.is_absolute() or not deployment.artifact.is_absolute():
            raise ConfigurationError("runtime paths must be absolute")

    @abstractmethod
    def build_launch_spec(
        self, deployment: DeploymentConfig, allocation: Allocation
    ) -> LaunchSpec: ...

    async def start(self, deployment: DeploymentConfig, allocation: Allocation) -> RuntimeInstance:
        await self.validate(deployment)
        if len(allocation.gpu_ids) != deployment.resources.gpus:
            raise ConfigurationError("allocation GPU count does not match deployment")
        spec = self.build_launch_spec(deployment, allocation)
        process = await self._supervisor.start(spec)
        return RuntimeInstance(
            instance_id=f"backend-{uuid.uuid4().hex}",
            deployment_id=deployment.deployment_id,
            base_url=f"http://{spec.host}:{spec.port}",
            state=BackendState.STARTING,
            allocation_id=allocation.allocation_id,
            process_id=process.pid,
        )

    async def health(self, instance: RuntimeInstance) -> bool:
        return await self._http.get_health(instance.base_url)

    async def warmup(self, instance: RuntimeInstance) -> None:
        if not await self.health(instance):
            raise ConfigurationError("runtime failed warmup health check")
        instance.state = BackendState.READY

    async def drain(self, instance: RuntimeInstance) -> None:
        instance.state = BackendState.DRAINING

    async def sleep(self, instance: RuntimeInstance, level: int | None = None) -> None:
        del level
        raise ConfigurationError("sleep is not enabled for this runtime deployment")

    async def wake(self, instance: RuntimeInstance) -> None:
        raise ConfigurationError("wake is not enabled for this runtime deployment")

    async def stop(self, instance: RuntimeInstance) -> None:
        instance.state = BackendState.STOPPING
        if instance.process_id is not None:
            await self._supervisor.stop(instance.process_id)
        instance.state = BackendState.STOPPED

    async def metrics(self, instance: RuntimeInstance) -> RuntimeMetrics:
        healthy = await self.health(instance)
        return RuntimeMetrics(healthy, len(instance.active_requests))

    async def cancel(self, instance: RuntimeInstance, request_id: str) -> None:
        instance.active_requests.discard(request_id)

    async def proxy(
        self,
        instance: RuntimeInstance,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> Mapping[str, Any]:
        instance.active_requests.add(request_id)
        try:
            return await self._http.post_json(instance.base_url, path, payload, request_id)
        finally:
            instance.active_requests.discard(request_id)

    async def stream(
        self,
        instance: RuntimeInstance,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> AsyncIterator[bytes]:
        instance.active_requests.add(request_id)
        try:
            async for chunk in self._http.stream_bytes(
                instance.base_url, path, payload, request_id
            ):
                yield chunk
        finally:
            instance.active_requests.discard(request_id)
