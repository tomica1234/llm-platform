from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llm_platform.config.loader import ConfigBundle
from llm_platform.config.schema import DeploymentConfig, ModelConfig
from llm_platform.persistence.models import DeploymentRow, ModelRow


@dataclass(frozen=True, slots=True)
class RegistrySyncReport:
    created_models: tuple[str, ...] = ()
    updated_models: tuple[str, ...] = ()
    disabled_stale_models: tuple[str, ...] = ()
    created_deployments: tuple[str, ...] = ()
    updated_deployments: tuple[str, ...] = ()
    disabled_stale_deployments: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return any(
            (
                self.created_models,
                self.updated_models,
                self.disabled_stale_models,
                self.created_deployments,
                self.updated_deployments,
                self.disabled_stale_deployments,
            )
        )


def model_values(model: ModelConfig) -> dict[str, Any]:
    return {
        "family": model.family,
        "revision": model.revision,
        "capabilities": model.capabilities.model_dump(mode="json"),
        "license": model.license,
        "enabled": model.enabled,
    }


def deployment_metadata(deployment: DeploymentConfig) -> dict[str, Any]:
    """Return non-secret deployment metadata suitable for the SQL registry."""
    return {
        "runtime_version": deployment.runtime_version,
        "resources": deployment.resources.model_dump(mode="json"),
        "serving": deployment.serving.model_dump(mode="json"),
        "capabilities": deployment.capabilities.model_dump(mode="json"),
        "benchmark": (
            deployment.benchmark.model_dump(mode="json")
            if deployment.benchmark is not None
            else None
        ),
    }


def deployment_values(deployment: DeploymentConfig) -> dict[str, Any]:
    return {
        "model_id": deployment.model_id,
        "runtime": deployment.runtime.value,
        "config": deployment_metadata(deployment),
        "enabled": deployment.enabled,
    }


def _changed(row: object, values: dict[str, Any]) -> bool:
    return any(getattr(row, name) != value for name, value in values.items())


def _update(row: object, values: dict[str, Any]) -> None:
    for name, value in values.items():
        setattr(row, name, value)


async def sync_registry(
    session: AsyncSession,
    bundle: ConfigBundle,
    *,
    apply: bool = False,
) -> RegistrySyncReport:
    """Calculate or apply the desired config registry in the caller's transaction."""
    configured_models = {model.model_id: model for model in bundle.models.models}
    configured_deployments = {
        deployment.deployment_id: deployment for deployment in bundle.deployments.deployments
    }
    unknown_models = sorted(
        {
            deployment.model_id
            for deployment in configured_deployments.values()
            if deployment.model_id not in configured_models
        }
    )
    if unknown_models:
        raise ValueError(
            "configured deployments reference missing models: " + ", ".join(unknown_models)
        )

    model_rows = {row.id: row for row in (await session.scalars(select(ModelRow))).all()}
    deployment_rows = {row.id: row for row in (await session.scalars(select(DeploymentRow))).all()}

    created_models: list[str] = []
    updated_models: list[str] = []
    disabled_stale_models: list[str] = []
    created_deployments: list[str] = []
    updated_deployments: list[str] = []
    disabled_stale_deployments: list[str] = []

    for model_id, model in configured_models.items():
        values = model_values(model)
        model_row = model_rows.get(model_id)
        if model_row is None:
            created_models.append(model_id)
            if apply:
                session.add(ModelRow(id=model_id, **values))
        elif _changed(model_row, values):
            updated_models.append(model_id)
            if apply:
                _update(model_row, values)

    for model_id, model_row in model_rows.items():
        if model_id not in configured_models and model_row.enabled:
            disabled_stale_models.append(model_id)
            if apply:
                model_row.enabled = False

    # Materialize parent rows before deployment upserts while retaining one transaction.
    if apply:
        await session.flush()

    for deployment_id, deployment in configured_deployments.items():
        values = deployment_values(deployment)
        deployment_row = deployment_rows.get(deployment_id)
        if deployment_row is None:
            created_deployments.append(deployment_id)
            if apply:
                session.add(
                    DeploymentRow(
                        id=deployment_id,
                        profile="configuration",
                        benchmark_id=None,
                        **values,
                    )
                )
        elif _changed(deployment_row, values):
            updated_deployments.append(deployment_id)
            if apply:
                _update(deployment_row, values)

    for deployment_id, deployment_row in deployment_rows.items():
        if deployment_id not in configured_deployments and deployment_row.enabled:
            disabled_stale_deployments.append(deployment_id)
            if apply:
                deployment_row.enabled = False

    if apply:
        await session.flush()

    return RegistrySyncReport(
        created_models=tuple(sorted(created_models)),
        updated_models=tuple(sorted(updated_models)),
        disabled_stale_models=tuple(sorted(disabled_stale_models)),
        created_deployments=tuple(sorted(created_deployments)),
        updated_deployments=tuple(sorted(updated_deployments)),
        disabled_stale_deployments=tuple(sorted(disabled_stale_deployments)),
    )
