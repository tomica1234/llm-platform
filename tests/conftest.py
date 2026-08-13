from collections.abc import Callable
from pathlib import Path

import pytest

from llm_platform.common.enums import RuntimeKind
from llm_platform.config.schema import (
    BenchmarkSummary,
    Capabilities,
    DeploymentConfig,
    ModelConfig,
    ResourceConfig,
    ScoreWeights,
    ServingConfig,
)


@pytest.fixture
def capabilities() -> Capabilities:
    return Capabilities(
        max_context=32768, tool_calling=True, structured_output=True, multimodal=False
    )


@pytest.fixture
def model_factory(capabilities: Capabilities) -> Callable[..., ModelConfig]:
    def factory(
        model_id: str = "example-model-b",
        *,
        family: str = "qwen",
        quality: float = 0.75,
        enabled: bool = True,
    ) -> ModelConfig:
        return ModelConfig(
            model_id=model_id,
            display_name=model_id,
            family=family,
            revision="test",
            license="test-only",
            capabilities=capabilities,
            quality_score=quality,
            enabled=enabled,
        )

    return factory


@pytest.fixture
def deployment_factory(
    capabilities: Capabilities,
) -> Callable[..., DeploymentConfig]:
    def factory(
        deployment_id: str = "example-b-vllm-1gpu",
        *,
        model_id: str = "example-model-b",
        runtime: RuntimeKind = RuntimeKind.VLLM,
        gpus: int = 1,
        port: int = 8201,
        benchmarked: bool = True,
        enabled: bool = True,
    ) -> DeploymentConfig:
        artifact = (
            Path(f"/srv/models/{model_id}")
            if runtime is not RuntimeKind.LLAMA_CPP
            else Path(f"/srv/models/{model_id}.gguf")
        )
        benchmark = (
            BenchmarkSummary(
                revision="test",
                startup_seconds=10,
                prompt_tps=100,
                generation_tps=50,
                concurrent_tps=80,
                max_vram_gb=20,
                max_ram_gb=10,
                passed=True,
            )
            if benchmarked
            else None
        )
        return DeploymentConfig(
            deployment_id=deployment_id,
            model_id=model_id,
            runtime=runtime,
            artifact=artifact,
            executable=Path(f"/opt/runtime/{runtime}"),
            runtime_version="test",
            resources=ResourceConfig(gpus=gpus, cpus=4, ram_gb=16, vram_gb=20),
            serving=ServingConfig(
                concurrency=2,
                context_limit=32768,
                host="127.0.0.1",
                port=port,
            ),
            capabilities=capabilities,
            benchmark=benchmark,
            enabled=enabled,
        )

    return factory


@pytest.fixture
def weights() -> dict[str, ScoreWeights]:
    return {
        "fast": ScoreWeights(
            quality_weight=0.6,
            latency_weight=2,
            wait_weight=2,
            switch_weight=1.8,
            resource_weight=0.6,
            loaded_bonus=0.5,
            batching_bonus=0.3,
        ),
        "balanced": ScoreWeights(
            quality_weight=1,
            latency_weight=1,
            wait_weight=1,
            switch_weight=1,
        ),
        "strong": ScoreWeights(
            quality_weight=2,
            latency_weight=0.5,
            wait_weight=0.5,
            switch_weight=0.4,
            resource_weight=0.1,
        ),
        "max": ScoreWeights(
            quality_weight=4,
            latency_weight=0.1,
            wait_weight=0.1,
            switch_weight=0.05,
            resource_weight=0.02,
            loaded_bonus=0.03,
            batching_bonus=0.03,
        ),
    }
