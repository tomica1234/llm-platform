from typing import Any

import pytest

from llm_platform.common.enums import RuntimeKind
from llm_platform.common.errors import ConfigurationError
from llm_platform.runtimes.base import Allocation
from llm_platform.runtimes.fake import FakeRuntimeAdapter
from llm_platform.runtimes.llama_cpp import LlamaCppAdapter
from llm_platform.runtimes.vllm import VllmAdapter


def test_llama_launch_spec_uses_argument_array_and_allocation(deployment_factory: Any) -> None:
    deployment = deployment_factory(
        "example-model-a-llama",
        model_id="example-model-a",
        runtime=RuntimeKind.LLAMA_CPP,
        gpus=2,
        port=8101,
    )
    spec = LlamaCppAdapter().build_launch_spec(deployment, Allocation("1", ("2", "0"), 4, 16))
    assert spec.argv[0] == "/opt/runtime/llama_cpp"
    assert spec.environment["CUDA_VISIBLE_DEVICES"] == "2,0"
    assert "--model" in spec.argv
    assert str(deployment.artifact) in spec.argv


def test_vllm_launch_spec_sets_tensor_parallel(deployment_factory: Any) -> None:
    deployment = deployment_factory(gpus=3)
    spec = VllmAdapter().build_launch_spec(deployment, Allocation("1", ("0", "1", "2"), 4, 16))
    index = spec.argv.index("--tensor-parallel-size")
    assert spec.argv[index + 1] == "3"


@pytest.mark.asyncio
async def test_adapter_rejects_wrong_runtime(deployment_factory: Any) -> None:
    deployment = deployment_factory(runtime=RuntimeKind.VLLM)
    with pytest.raises(ConfigurationError):
        await LlamaCppAdapter().validate(deployment)


@pytest.mark.asyncio
async def test_fake_runtime_contract(deployment_factory: Any) -> None:
    deployment = deployment_factory()
    adapter = FakeRuntimeAdapter()
    instance = await adapter.start(deployment, Allocation("1", ("0",), 4, 16))
    await adapter.warmup(instance)
    assert await adapter.health(instance)
    body = await adapter.proxy(instance, "/v1/responses", {"model": "qwen", "input": "x"}, "r1")
    assert body["object"] == "response"
    chunks = [chunk async for chunk in adapter.stream(instance, "/v1/responses", {}, "r2")]
    assert chunks[-1] == b"data: [DONE]\n\n"
    await adapter.cancel(instance, "r2")
    assert "r2" in adapter.cancelled
    await adapter.drain(instance)
    await adapter.stop(instance)
    assert not await adapter.health(instance)
