import os
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from fastapi import FastAPI

from llm_platform.auth.sqlalchemy_store import SqlAlchemyKeyStore
from llm_platform.config.loader import load_bundle
from llm_platform.gateway.app import create_app
from llm_platform.gateway.service import DeploymentRegistry, GatewayService
from llm_platform.orchestrator.control_plane import ControlPlane
from llm_platform.orchestrator.reconciler import Reconciler
from llm_platform.persistence.database import Database
from llm_platform.routing.router import RuleRouter
from llm_platform.runtimes.base import RuntimeAdapter
from llm_platform.runtimes.llama_cpp import LlamaCppAdapter
from llm_platform.runtimes.vllm import VllmAdapter
from llm_platform.scheduler.planner import ResourcePlanner
from llm_platform.slurm.cli import CliSlurmAdapter
from llm_platform.telemetry.logging import configure_logging


def build_app(config_dir: Path) -> FastAPI:
    bundle = load_bundle(config_dir)
    router = RuleRouter(bundle.models.models, bundle.deployments.deployments, bundle.routing.modes)
    registry = DeploymentRegistry()
    service = GatewayService(
        router,
        registry,
        bundle.models.models,
        request_timeout_seconds=bundle.platform.gateway.request_timeout_seconds,
        config_revision=bundle.platform.config_revision,
    )
    database_url = os.environ.get("LLM_PLATFORM_DATABASE_URL", bundle.platform.database.url)
    database = Database(database_url, echo=bundle.platform.database.echo)
    enabled = [item for item in bundle.deployments.deployments if item.enabled]
    adapters: dict[str, RuntimeAdapter] = {}
    for deployment in enabled:
        if deployment.runtime.value == "llama_cpp":
            adapters[deployment.deployment_id] = LlamaCppAdapter()
        elif deployment.runtime.value == "vllm":
            adapters[deployment.deployment_id] = VllmAdapter()
        else:
            raise RuntimeError("production control plane may not use a fake runtime")
    deployments = {item.deployment_id: item for item in enabled}
    planner = ResourcePlanner(enabled, bundle.gpu_profiles.profiles)
    reconciler = Reconciler(
        deployments,
        adapters,
        CliSlurmAdapter(config_dir=config_dir, slurm_config=bundle.platform.slurm),
        drain_timeout=bundle.platform.scheduler.drain_timeout_seconds,
        health_timeout=bundle.platform.scheduler.backend_health_timeout_seconds,
        registry=registry,
        slurm_managed_runtime=True,
        retry_budget=bundle.platform.scheduler.retry_budget,
    )
    control_plane = ControlPlane(
        reconciler,
        planner,
        bundle.gpu_profiles.profiles,
        database.sessions,
        interval_seconds=bundle.platform.scheduler.reconcile_interval_seconds,
        max_users=bundle.platform.queue.max_users,
        max_pending_per_user=bundle.platform.queue.max_pending_per_user,
    )
    service.control_plane = control_plane

    async def shutdown() -> None:
        await control_plane.stop()
        await database.dispose()

    app = create_app(
        service,
        SqlAlchemyKeyStore(database.sessions),
        startup=control_plane.start,
        shutdown=shutdown,
    )
    app.state.database = database
    return app


def run(
    config: Annotated[Path, typer.Option("--config", help="Configuration directory")] = Path(
        "config"
    ),
) -> None:
    configure_logging()
    bundle = load_bundle(config)
    app = build_app(config)
    uvicorn.run(app, host=bundle.platform.gateway.host, port=bundle.platform.gateway.port)


if __name__ == "__main__":
    run()
