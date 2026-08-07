import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

from llm_platform.common.enums import BackendState
from llm_platform.config.schema import DeploymentConfig
from llm_platform.runtimes.base import (
    Allocation,
    LaunchSpec,
    RuntimeAdapter,
    RuntimeInstance,
    RuntimeMetrics,
)


class FakeRuntimeAdapter(RuntimeAdapter):
    def __init__(self) -> None:
        self.instances: dict[str, RuntimeInstance] = {}
        self.cancelled: set[str] = set()
        self.fail_health = False

    async def validate(self, deployment: DeploymentConfig) -> None:
        if len(deployment.deployment_id) == 0:
            raise ValueError("deployment ID is required")

    def build_launch_spec(self, deployment: DeploymentConfig, allocation: Allocation) -> LaunchSpec:
        return LaunchSpec(
            ("fake-runtime", deployment.deployment_id),
            {"CUDA_VISIBLE_DEVICES": ",".join(allocation.gpu_ids)},
            deployment.serving.host,
            deployment.serving.port,
        )

    async def start(self, deployment: DeploymentConfig, allocation: Allocation) -> RuntimeInstance:
        await self.validate(deployment)
        instance = RuntimeInstance(
            instance_id=f"fake-{uuid.uuid4().hex}",
            deployment_id=deployment.deployment_id,
            base_url=f"http://{deployment.serving.host}:{deployment.serving.port}",
            state=BackendState.STARTING,
            allocation_id=allocation.allocation_id,
        )
        self.instances[instance.instance_id] = instance
        return instance

    async def health(self, instance: RuntimeInstance) -> bool:
        return not self.fail_health and instance.state not in {
            BackendState.FAILED,
            BackendState.STOPPED,
        }

    async def warmup(self, instance: RuntimeInstance) -> None:
        if self.fail_health:
            instance.state = BackendState.FAILED
            raise RuntimeError("injected health failure")
        instance.state = BackendState.READY

    async def drain(self, instance: RuntimeInstance) -> None:
        instance.state = BackendState.DRAINING

    async def sleep(self, instance: RuntimeInstance, level: int | None = None) -> None:
        del level
        instance.state = BackendState.SLEEPING

    async def wake(self, instance: RuntimeInstance) -> None:
        instance.state = BackendState.READY

    async def stop(self, instance: RuntimeInstance) -> None:
        instance.state = BackendState.STOPPED

    async def metrics(self, instance: RuntimeInstance) -> RuntimeMetrics:
        return RuntimeMetrics(await self.health(instance), len(instance.active_requests))

    async def cancel(self, instance: RuntimeInstance, request_id: str) -> None:
        self.cancelled.add(request_id)
        instance.active_requests.discard(request_id)

    async def proxy(
        self,
        instance: RuntimeInstance,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> Mapping[str, Any]:
        del path
        instance.active_requests.add(request_id)
        try:
            model = str(payload.get("model", "fake"))
            if "input" in payload:
                return {
                    "id": request_id,
                    "object": "response",
                    "model": model,
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "fake response"}],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                }
            return {
                "id": request_id,
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "fake response"}}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }
        finally:
            instance.active_requests.discard(request_id)

    async def stream(
        self,
        instance: RuntimeInstance,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> AsyncIterator[bytes]:
        del path, payload
        instance.active_requests.add(request_id)
        try:
            yield b'data: {"type":"response.output_text.delta","delta":"fake"}\n\n'
            yield b"data: [DONE]\n\n"
        finally:
            instance.active_requests.discard(request_id)
