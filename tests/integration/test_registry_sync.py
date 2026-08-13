from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from llm_platform.common.enums import RuntimeKind
from llm_platform.config.loader import ConfigBundle
from llm_platform.persistence.models import (
    Base,
    DeploymentRow,
    ModelRow,
    ModelSkillEvaluationRow,
)
from llm_platform.persistence.registry import deployment_metadata, sync_registry


def registry_bundle(models: list[Any], deployments: list[Any]) -> ConfigBundle:
    return cast(
        ConfigBundle,
        SimpleNamespace(
            models=SimpleNamespace(models=models),
            deployments=SimpleNamespace(deployments=deployments),
        ),
    )


class AsyncSessionFacade:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def __aenter__(self) -> "AsyncSessionFacade":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is not None:
            self.session.rollback()
        self.session.close()

    def add(self, row: Any) -> None:
        self.session.add(row)

    async def get(self, model: Any, identifier: Any) -> Any:
        return self.session.get(model, identifier)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def rollback(self) -> None:
        self.session.rollback()

    async def scalars(self, statement: Any) -> Any:
        return self.session.scalars(statement)


class RegistryDatabase:
    def __init__(self, path: Path) -> None:
        self.engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSessionFacade:
        return AsyncSessionFacade(self.session_factory())

    async def dispose(self) -> None:
        self.engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_empty_database_creates_configured_model(
    tmp_path: Path, model_factory: Any
) -> None:
    database = RegistryDatabase(tmp_path / "model-only.db")
    model = model_factory("configured-model")

    async with database.session() as session:
        report = await sync_registry(cast(Any, session), registry_bundle([model], []), apply=True)
        await session.commit()
    async with database.session() as session:
        row = await session.get(ModelRow, model.model_id)

    assert report.created_models == (model.model_id,)
    assert row is not None and row.enabled
    await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_empty_database_creates_model_and_deployment_with_valid_fk(
    tmp_path: Path, model_factory: Any, deployment_factory: Any
) -> None:
    database = RegistryDatabase(tmp_path / "registry.db")
    model = model_factory("configured-model", family="initial", quality=0.99)
    deployment = deployment_factory(
        "configured-deployment",
        model_id=model.model_id,
        runtime=RuntimeKind.LLAMA_CPP,
    ).model_copy(update={"environment": {"API_KEY": "must-not-be-stored"}})

    async with database.session() as session:
        report = await sync_registry(
            cast(Any, session), registry_bundle([model], [deployment]), apply=True
        )
        await session.commit()

    async with database.session() as session:
        model_row = await session.get(ModelRow, model.model_id)
        deployment_row = await session.get(DeploymentRow, deployment.deployment_id)
    assert report.created_models == (model.model_id,)
    assert report.created_deployments == (deployment.deployment_id,)
    assert model_row is not None
    assert model_row.capabilities == model.capabilities.model_dump(mode="json")
    assert deployment_row is not None
    assert deployment_row.model_id == model.model_id
    assert deployment_row.config == deployment_metadata(deployment)
    assert "environment" not in deployment_row.config
    assert "artifact" not in deployment_row.config
    assert "executable" not in deployment_row.config
    await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_is_idempotent_and_updates_changed_model_metadata(
    tmp_path: Path, model_factory: Any, deployment_factory: Any
) -> None:
    database = RegistryDatabase(tmp_path / "idempotent.db")
    original = model_factory("configured-model", family="old-family")
    original_deployment = deployment_factory("configured-deployment", model_id=original.model_id)
    bundle = registry_bundle([original], [original_deployment])
    async with database.session() as session:
        await sync_registry(cast(Any, session), bundle, apply=True)
        await session.commit()
    async with database.session() as session:
        deployment_row = await session.get(DeploymentRow, original_deployment.deployment_id)
        assert deployment_row is not None
        deployment_row.profile = "existing-profile"
        deployment_row.benchmark_id = "existing-benchmark"
        await session.commit()
    async with database.session() as session:
        unchanged = await sync_registry(cast(Any, session), bundle, apply=True)
        await session.commit()

    changed = original.model_copy(update={"family": "new-family", "revision": "revision-2"})
    changed_deployment = original_deployment.model_copy(
        update={"runtime_version": "runtime-revision-2"}
    )
    async with database.session() as session:
        updated = await sync_registry(
            cast(Any, session),
            registry_bundle([changed], [changed_deployment]),
            apply=True,
        )
        await session.commit()
    async with database.session() as session:
        row = await session.get(ModelRow, original.model_id)
        deployment_row = await session.get(DeploymentRow, original_deployment.deployment_id)

    assert not unchanged.changed
    assert updated.updated_models == (original.model_id,)
    assert updated.updated_deployments == (original_deployment.deployment_id,)
    assert row is not None
    assert (row.family, row.revision) == ("new-family", "revision-2")
    assert deployment_row is not None
    assert deployment_row.config["runtime_version"] == "runtime-revision-2"
    assert deployment_row.profile == "existing-profile"
    assert deployment_row.benchmark_id == "existing-benchmark"
    await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_retains_stale_rows_and_model_skill_evaluations(
    tmp_path: Path, model_factory: Any, deployment_factory: Any
) -> None:
    database = RegistryDatabase(tmp_path / "stale.db")
    model = model_factory("retained-model")
    deployment = deployment_factory("retained-deployment", model_id=model.model_id)
    async with database.session() as session:
        await sync_registry(cast(Any, session), registry_bundle([model], [deployment]), apply=True)
        await session.flush()
        session.add(
            ModelSkillEvaluationRow(
                id="evaluation-1",
                model_id=model.model_id,
                agent_profile_id=None,
                skill="coding",
                benchmark="fixture",
                benchmark_version="1",
                score=0.8,
                sample_count=10,
                confidence=0.9,
                raw_metrics={},
                measured_at=datetime.now(UTC),
                idempotency_key=None,
                submission_hash=None,
            )
        )
        await session.commit()

    async with database.session() as session:
        report = await sync_registry(cast(Any, session), registry_bundle([], []), apply=True)
        await session.commit()
    async with database.session() as session:
        model_row = await session.get(ModelRow, model.model_id)
        deployment_row = await session.get(DeploymentRow, deployment.deployment_id)
        evaluation = await session.get(ModelSkillEvaluationRow, "evaluation-1")

    assert report.disabled_stale_models == (model.model_id,)
    assert report.disabled_stale_deployments == (deployment.deployment_id,)
    assert model_row is not None and not model_row.enabled
    assert deployment_row is not None and not deployment_row.enabled
    assert evaluation is not None and evaluation.model_id == model.model_id
    await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dry_run_reports_exact_changes_without_modifying_database(
    tmp_path: Path, model_factory: Any
) -> None:
    database = RegistryDatabase(tmp_path / "dry-run.db")
    model = model_factory("dry-run-model")
    async with database.session() as session:
        report = await sync_registry(cast(Any, session), registry_bundle([model], []), apply=False)
        await session.rollback()
    async with database.session() as session:
        rows = (await session.scalars(select(ModelRow))).all()

    assert report.created_models == (model.model_id,)
    assert rows == []
    await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_deployment_flush_rolls_back_model_changes(
    tmp_path: Path, model_factory: Any, deployment_factory: Any
) -> None:
    database = RegistryDatabase(tmp_path / "rollback.db")
    model = model_factory("rolled-back-model")
    deployment = deployment_factory("failed-deployment", model_id=model.model_id)

    def fail_deployment_flush(session: Session, *_args: Any) -> None:
        if any(isinstance(row, DeploymentRow) for row in session.new):
            raise RuntimeError("injected deployment failure")

    event.listen(Session, "before_flush", fail_deployment_flush)
    try:
        async with database.session() as session:
            with pytest.raises(RuntimeError, match="injected deployment failure"):
                await sync_registry(
                    cast(Any, session), registry_bundle([model], [deployment]), apply=True
                )
            await session.rollback()
    finally:
        event.remove(Session, "before_flush", fail_deployment_flush)

    async with database.session() as session:
        assert await session.get(ModelRow, model.model_id) is None
        assert await session.get(DeploymentRow, deployment.deployment_id) is None
    await database.dispose()
