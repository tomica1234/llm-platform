import os
import shutil
import subprocess

import pytest

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
