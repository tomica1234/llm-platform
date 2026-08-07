import os
from pathlib import Path
from typing import Annotated

import typer

from llm_platform.config.loader import load_bundle
from llm_platform.runtimes.base import Allocation
from llm_platform.runtimes.llama_cpp import LlamaCppAdapter
from llm_platform.runtimes.vllm import VllmAdapter


def run_backend(
    instance: Annotated[str, typer.Option("--instance")],
    deployment: Annotated[str, typer.Option("--deployment")],
    config_dir: Annotated[Path, typer.Option("--config-dir")] = Path("/etc/llm-platform"),
    print_spec: Annotated[bool, typer.Option("--print-spec")] = False,
) -> None:
    bundle = load_bundle(config_dir)
    matches = [item for item in bundle.deployments.deployments if item.deployment_id == deployment]
    if len(matches) != 1:
        raise typer.BadParameter("deployment is not uniquely registered")
    selected = matches[0]
    visible = tuple(
        value for value in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if value
    )
    if len(visible) != selected.resources.gpus:
        raise typer.BadParameter("Slurm GPU allocation does not match deployment")
    allocation = Allocation(instance, visible, selected.resources.cpus, selected.resources.ram_gb)
    if selected.runtime.value == "llama_cpp":
        spec = LlamaCppAdapter().build_launch_spec(selected, allocation)
    elif selected.runtime.value == "vllm":
        spec = VllmAdapter().build_launch_spec(selected, allocation)
    else:
        raise typer.BadParameter("fake runtime may not be launched in production")
    if print_spec:
        typer.echo("argv=" + " ".join(spec.argv))
        typer.echo(f"host={spec.host} port={spec.port}")
        return
    environment = os.environ.copy()
    environment.update(spec.environment)
    # Exact executable and argument vector came from a validated deployment manifest.
    os.execve(spec.argv[0], spec.argv, environment)  # noqa: S606


if __name__ == "__main__":
    typer.run(run_backend)
