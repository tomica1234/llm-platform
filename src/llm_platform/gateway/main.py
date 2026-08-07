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
from llm_platform.persistence.database import Database
from llm_platform.routing.router import RuleRouter
from llm_platform.telemetry.logging import configure_logging


def build_app(config_dir: Path) -> FastAPI:
    bundle = load_bundle(config_dir)
    router = RuleRouter(bundle.models.models, bundle.deployments.deployments, bundle.routing.modes)
    service = GatewayService(
        router,
        DeploymentRegistry(),
        bundle.models.models,
        request_timeout_seconds=bundle.platform.gateway.request_timeout_seconds,
        config_revision=bundle.platform.config_revision,
    )
    database_url = os.environ.get("LLM_PLATFORM_DATABASE_URL", bundle.platform.database.url)
    database = Database(database_url, echo=bundle.platform.database.echo)
    app = create_app(service, SqlAlchemyKeyStore(database.sessions), shutdown=database.dispose)
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
