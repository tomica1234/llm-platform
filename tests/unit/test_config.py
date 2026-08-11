from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_platform.config.loader import load_bundle
from llm_platform.config.schema import DeploymentConfig, PlatformConfig


def test_example_bundle_validates() -> None:
    bundle = load_bundle(Path("config"))
    assert bundle.platform.queue.max_users == 3
    assert len(bundle.deployments.deployments) == 5
    assert len(bundle.users.users) == 1
    assert not any(item.auto_eligible for item in bundle.deployments.deployments)


def test_backend_bind_must_be_loopback() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        PlatformConfig(backend_bind="0.0.0.0")


def test_production_rejects_current_user_slurm_submission() -> None:
    with pytest.raises(ValidationError, match="production requires"):
        PlatformConfig(environment="production", slurm={"submission_mode": "current_user"})


def test_deployment_rejects_relative_path(deployment_factory: object) -> None:
    deployment = deployment_factory()  # type: ignore[operator]
    payload = deployment.model_dump()
    payload["artifact"] = "relative/model"
    with pytest.raises(ValidationError, match="absolute"):
        DeploymentConfig.model_validate(payload)


def test_unknown_config_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        PlatformConfig.model_validate({"unexpected": True})
