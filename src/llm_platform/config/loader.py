from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from llm_platform.common.errors import ConfigurationError
from llm_platform.config.schema import (
    DeploymentsFile,
    GpuProfilesFile,
    ModelsFile,
    PlatformConfig,
    RoutingFile,
    UsersFile,
)


def load_yaml[ConfigT: BaseModel](path: Path, model: type[ConfigT]) -> ConfigT:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        return model.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"invalid configuration {path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    platform: PlatformConfig
    models: ModelsFile
    deployments: DeploymentsFile
    routing: RoutingFile
    gpu_profiles: GpuProfilesFile
    users: UsersFile


def load_bundle(config_dir: Path) -> ConfigBundle:
    return ConfigBundle(
        platform=load_yaml(config_dir / "platform.example.yaml", PlatformConfig),
        models=load_yaml(config_dir / "models.example.yaml", ModelsFile),
        deployments=load_yaml(config_dir / "deployments.example.yaml", DeploymentsFile),
        routing=load_yaml(config_dir / "routing.example.yaml", RoutingFile),
        gpu_profiles=load_yaml(config_dir / "gpu-profiles.example.yaml", GpuProfilesFile),
        users=load_yaml(config_dir / "users.example.yaml", UsersFile),
    )
