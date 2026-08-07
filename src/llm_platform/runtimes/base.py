from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from llm_platform.common.enums import BackendState
from llm_platform.config.schema import DeploymentConfig


@dataclass(frozen=True, slots=True)
class Allocation:
    allocation_id: str
    gpu_ids: tuple[str, ...]
    cpus: int
    ram_gb: int


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    host: str
    port: int


@dataclass(slots=True)
class RuntimeInstance:
    instance_id: str
    deployment_id: str
    base_url: str
    state: BackendState
    allocation_id: str | None = None
    process_id: int | None = None
    active_requests: set[str] = field(default_factory=set)
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeMetrics:
    healthy: bool
    active_requests: int
    values: Mapping[str, float] = field(default_factory=dict)


class RuntimeAdapter(ABC):
    @abstractmethod
    async def validate(self, deployment: DeploymentConfig) -> None: ...

    @abstractmethod
    def build_launch_spec(
        self, deployment: DeploymentConfig, allocation: Allocation
    ) -> LaunchSpec: ...

    @abstractmethod
    async def start(
        self, deployment: DeploymentConfig, allocation: Allocation
    ) -> RuntimeInstance: ...

    @abstractmethod
    async def health(self, instance: RuntimeInstance) -> bool: ...

    @abstractmethod
    async def warmup(self, instance: RuntimeInstance) -> None: ...

    @abstractmethod
    async def drain(self, instance: RuntimeInstance) -> None: ...

    @abstractmethod
    async def sleep(self, instance: RuntimeInstance, level: int | None = None) -> None: ...

    @abstractmethod
    async def wake(self, instance: RuntimeInstance) -> None: ...

    @abstractmethod
    async def stop(self, instance: RuntimeInstance) -> None: ...

    @abstractmethod
    async def metrics(self, instance: RuntimeInstance) -> RuntimeMetrics: ...

    @abstractmethod
    async def cancel(self, instance: RuntimeInstance, request_id: str) -> None: ...

    @abstractmethod
    async def proxy(
        self,
        instance: RuntimeInstance,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> Mapping[str, Any]: ...

    @abstractmethod
    async def stream(
        self,
        instance: RuntimeInstance,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> AsyncIterator[bytes]:
        if False:
            yield b""
