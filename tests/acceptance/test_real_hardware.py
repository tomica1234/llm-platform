import os
import shutil
import subprocess
from pathlib import Path

import pytest

from llm_platform.auth.keys import ApiPrincipal
from llm_platform.common.enums import BackendState, RuntimeKind
from llm_platform.common.subprocesses import AsyncioCommandRunner
from llm_platform.config.loader import load_bundle
from llm_platform.gateway.service import DeploymentRegistry, GatewayService
from llm_platform.orchestrator.reconciler import Reconciler
from llm_platform.routing.router import RuleRouter
from llm_platform.runtimes.llama_cpp import LlamaCppAdapter
from llm_platform.runtimes.vllm import VllmAdapter
from llm_platform.scheduler.planner import ProfilePlan
from llm_platform.slurm.cli import CliSlurmAdapter

pytestmark = pytest.mark.hardware


def require_hardware_opt_in() -> None:
    if os.environ.get("LLM_PLATFORM_HARDWARE_TESTS") != "1":
        pytest.skip("set LLM_PLATFORM_HARDWARE_TESTS=1 on the reviewed GPU host")


def test_three_nvidia_gpus_are_visible() -> None:
    require_hardware_opt_in()
    executable = shutil.which("nvidia-smi")
    if executable is None:
        pytest.fail("nvidia-smi is required on the hardware test host")
    result = subprocess.run(  # noqa: S603
        [executable, "--query-gpu=index", "--format=csv,noheader"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert len(result.stdout.splitlines()) == 3


def test_slurm_cli_and_site_gpu_smoke_script() -> None:
    require_hardware_opt_in()
    for command in ("squeue", "sbatch", "sacct"):
        assert shutil.which(command), f"{command} is required"
    smoke_script = os.environ.get("LLM_PLATFORM_SLURM_GPU_SMOKE_SCRIPT")
    if not smoke_script:
        pytest.skip("set a reviewed 1/2/3-GPU Slurm smoke script path")
    assert os.path.isabs(smoke_script)
    result = subprocess.run([smoke_script], check=False)  # noqa: S603
    assert result.returncode == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deployment_id", "runtime"),
    [
        ("smoke-qwen3-llama-1gpu", RuntimeKind.LLAMA_CPP),
        ("smoke-qwen3-vllm-1gpu", RuntimeKind.VLLM),
    ],
)
async def test_orchestrator_gateway_backend_and_gpu_release(
    deployment_id: str, runtime: RuntimeKind, tmp_path: Path
) -> None:
    require_hardware_opt_in()
    config_dir_value = os.environ.get("LLM_PLATFORM_HARDWARE_CONFIG_DIR")
    if not config_dir_value:
        pytest.fail("set LLM_PLATFORM_HARDWARE_CONFIG_DIR to the reviewed smoke config")
    config_dir = Path(config_dir_value)
    bundle = load_bundle(config_dir)
    deployment = next(
        (item for item in bundle.deployments.deployments if item.deployment_id == deployment_id),
        None,
    )
    if deployment is None or not deployment.enabled:
        pytest.fail(f"explicitly enable reviewed hardware deployment {deployment_id}")
    model = next(item for item in bundle.models.models if item.model_id == deployment.model_id)
    if not model.enabled:
        pytest.fail(f"explicitly enable smoke model {model.model_id}")

    registry = DeploymentRegistry()
    adapter = LlamaCppAdapter() if runtime is RuntimeKind.LLAMA_CPP else VllmAdapter()
    slurm = CliSlurmAdapter(config_dir=config_dir)
    reconciler = Reconciler(
        {deployment_id: deployment},
        {deployment_id: adapter},
        slurm,
        registry=registry,
        slurm_managed_runtime=True,
        health_timeout=180,
        script_directory=tmp_path,
    )
    start = ProfilePlan("hardware-smoke", (deployment_id,), (), ())
    stop = ProfilePlan("idle", (), (deployment_id,), ())
    job_id: str | None = None
    try:
        result = await reconciler.reconcile(start)
        assert result.started == (deployment_id,)
        instance = reconciler.instances[deployment_id]
        job_id = instance.allocation_id
        assert instance.state is BackendState.READY
        assert registry.ready_ids() == frozenset({deployment_id})

        squeue = shutil.which("squeue")
        assert squeue is not None
        owner = await AsyncioCommandRunner().run(
            (squeue, "--noheader", "--jobs", str(job_id), "--format", "%u"),
            timeout_seconds=30,
        )
        assert owner.returncode == 0
        assert owner.stdout.strip() == "svc-llm"

        router = RuleRouter([model], [deployment], bundle.routing.modes)
        service = GatewayService(router, registry, [model], request_timeout_seconds=180)
        principal = ApiPrincipal(
            "hardware-test",
            frozenset({"inference"}),
            frozenset({model.model_id}),
            1,
        )
        response = await service.complete(
            "/v1/chat/completions",
            {
                "model": f"force-deployment/{deployment_id}",
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 8,
            },
            principal,
            {},
            f"hardware-{deployment_id}",
        )
        assert "choices" in response.body
    finally:
        if deployment_id in reconciler.instances:
            stopped = await reconciler.reconcile(stop)
            assert stopped.stopped == (deployment_id,)
        if job_id is not None:
            assert await slurm.inspect(job_id) is None
