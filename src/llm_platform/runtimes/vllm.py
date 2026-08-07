from llm_platform.common.enums import RuntimeKind
from llm_platform.common.errors import ConfigurationError
from llm_platform.config.schema import DeploymentConfig
from llm_platform.runtimes.base import Allocation, LaunchSpec
from llm_platform.runtimes.external import ExternalRuntimeAdapter


class VllmAdapter(ExternalRuntimeAdapter):
    async def validate(self, deployment: DeploymentConfig) -> None:
        await super().validate(deployment)
        if deployment.runtime is not RuntimeKind.VLLM:
            raise ConfigurationError("vLLM adapter received another runtime")

    def build_launch_spec(self, deployment: DeploymentConfig, allocation: Allocation) -> LaunchSpec:
        environment = dict(deployment.environment)
        environment["CUDA_VISIBLE_DEVICES"] = ",".join(allocation.gpu_ids)
        argv = (
            str(deployment.executable),
            "serve",
            str(deployment.artifact),
            "--host",
            deployment.serving.host,
            "--port",
            str(deployment.serving.port),
            "--served-model-name",
            deployment.model_id,
            "--max-model-len",
            str(deployment.serving.context_limit),
            "--tensor-parallel-size",
            str(deployment.resources.gpus),
            *deployment.launch_args,
        )
        return LaunchSpec(argv, environment, deployment.serving.host, deployment.serving.port)
