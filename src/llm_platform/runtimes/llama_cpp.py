from llm_platform.common.enums import RuntimeKind
from llm_platform.common.errors import ConfigurationError
from llm_platform.config.schema import DeploymentConfig
from llm_platform.runtimes.base import Allocation, LaunchSpec
from llm_platform.runtimes.external import ExternalRuntimeAdapter


class LlamaCppAdapter(ExternalRuntimeAdapter):
    async def validate(self, deployment: DeploymentConfig) -> None:
        await super().validate(deployment)
        if deployment.runtime is not RuntimeKind.LLAMA_CPP:
            raise ConfigurationError("llama.cpp adapter received another runtime")
        if deployment.artifact.suffix.lower() != ".gguf":
            raise ConfigurationError("llama.cpp requires a GGUF artifact")

    def build_launch_spec(self, deployment: DeploymentConfig, allocation: Allocation) -> LaunchSpec:
        environment = dict(deployment.environment)
        environment["CUDA_VISIBLE_DEVICES"] = ",".join(allocation.gpu_ids)
        argv = (
            str(deployment.executable),
            "--model",
            str(deployment.artifact),
            "--host",
            deployment.serving.host,
            "--port",
            str(deployment.serving.port),
            "--ctx-size",
            str(deployment.serving.context_limit),
            "--alias",
            deployment.model_id,
            *deployment.launch_args,
        )
        return LaunchSpec(argv, environment, deployment.serving.host, deployment.serving.port)
