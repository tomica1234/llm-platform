from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from llm_platform.common.enums import RuntimeKind, SchedulerMode

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseConfig(StrictModel):
    url: str = "sqlite+aiosqlite:///./llm-platform.db"
    echo: bool = False

    @field_validator("url")
    @classmethod
    def supported_database(cls, value: str) -> str:
        if not value.startswith(("sqlite+aiosqlite://", "postgresql+asyncpg://")):
            raise ValueError("database must use async SQLite or PostgreSQL")
        return value


class GatewayConfig(StrictModel):
    host: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)] = 8000
    public_base_url: str = "http://127.0.0.1:8000"
    request_timeout_seconds: PositiveInt = 600
    shutdown_grace_seconds: PositiveInt = 5
    cancel_on_disconnect: bool = True
    trusted_proxy_headers: bool = False


class SchedulerConfig(StrictModel):
    mode: SchedulerMode = SchedulerMode.AUTO
    reconcile_interval_seconds: NonNegativeFloat = 2
    same_model_coalesce_window_seconds: NonNegativeFloat = 2
    minimum_profile_dwell_seconds: NonNegativeFloat = 120
    rebalance_idle_seconds: NonNegativeFloat = 90
    drain_timeout_seconds: PositiveInt = 300
    backend_health_timeout_seconds: PositiveInt = 30
    max_switches_per_10_minutes: PositiveInt = 3
    retry_budget: Annotated[int, Field(ge=0)] = 3


class SlurmConfig(StrictModel):
    qos: str | None = None
    submission_mode: Literal["helper", "current_user"] = "helper"
    submit_socket: Path = Path("/run/llm-platform/backend-submit.sock")
    job_user: str = "svc-llm"

    @field_validator("qos", "job_user")
    @classmethod
    def safe_slurm_token(cls, value: str | None) -> str | None:
        if value is not None and (
            not value or not value.replace("-", "").replace("_", "").isalnum()
        ):
            raise ValueError("Slurm values must contain only letters, digits, '-' or '_'")
        return value

    @field_validator("submit_socket")
    @classmethod
    def absolute_socket(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Slurm submit socket must be absolute")
        return value


class QueueConfig(StrictModel):
    default_user_concurrency: PositiveInt = 1
    max_user_concurrency: PositiveInt = 2
    max_pending_per_user: PositiveInt = 20
    max_users: Annotated[int, Field(ge=1, le=3)] = 3

    @model_validator(mode="after")
    def concurrency_order(self) -> "QueueConfig":
        if self.default_user_concurrency > self.max_user_concurrency:
            raise ValueError("default concurrency exceeds maximum")
        return self


class PrivacyConfig(StrictModel):
    store_prompt_body: bool = False
    store_code_body: bool = False
    metadata_retention_days: PositiveInt = 90

    @model_validator(mode="after")
    def secure_defaults(self) -> "PrivacyConfig":
        if self.store_code_body and not self.store_prompt_body:
            raise ValueError("code body storage requires explicit prompt body debug storage")
        return self


class PlatformConfig(StrictModel):
    environment: Literal["development", "test", "production"] = "development"
    config_revision: str = "development"
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    slurm: SlurmConfig = Field(default_factory=SlurmConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    backend_bind: str = "127.0.0.1"

    @field_validator("backend_bind")
    @classmethod
    def backend_is_loopback(cls, value: str) -> str:
        if value not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("backend_bind must be loopback")
        return value

    @model_validator(mode="after")
    def production_requires_submit_helper(self) -> "PlatformConfig":
        if self.environment == "production" and self.slurm.submission_mode != "helper":
            raise ValueError("production requires the svc-llm submit helper")
        return self


class Capabilities(StrictModel):
    max_context: PositiveInt
    tool_calling: bool = False
    structured_output: bool = False
    multimodal: bool = False


class ModelConfig(StrictModel):
    model_id: str
    display_name: str
    family: str
    revision: str
    license: str
    capabilities: Capabilities
    quality_score: Annotated[float, Field(ge=0, le=1)] = 0.5
    tags: set[str] = Field(default_factory=set)
    known_constraints: list[str] = Field(default_factory=list)
    enabled: bool = False


class ModelsFile(StrictModel):
    models: list[ModelConfig]

    @model_validator(mode="after")
    def unique_ids(self) -> "ModelsFile":
        ids = [model.model_id for model in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("model IDs must be unique")
        return self


class ResourceConfig(StrictModel):
    gpus: Annotated[int, Field(ge=0, le=3)]
    cpus: PositiveInt
    ram_gb: PositiveInt
    vram_gb: Annotated[int, Field(ge=0)] = 0


class ServingConfig(StrictModel):
    concurrency: PositiveInt = 1
    context_limit: PositiveInt
    host: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1024, le=65535)]
    health_path: str = "/health"
    metrics_path: str = "/metrics"

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("runtime services must bind to loopback")
        return value


class BenchmarkSummary(StrictModel):
    revision: str
    startup_seconds: NonNegativeFloat
    prompt_tps: NonNegativeFloat
    generation_tps: NonNegativeFloat
    concurrent_tps: NonNegativeFloat
    max_vram_gb: NonNegativeFloat
    max_ram_gb: NonNegativeFloat
    passed: bool


class DeploymentConfig(StrictModel):
    deployment_id: str
    model_id: str
    runtime: RuntimeKind
    artifact: Path
    executable: Path
    runtime_version: str
    resources: ResourceConfig
    serving: ServingConfig
    launch_args: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    capabilities: Capabilities
    benchmark: BenchmarkSummary | None = None
    enabled: bool = False

    @field_validator("artifact", "executable")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("deployment paths must be absolute")
        return value

    @property
    def auto_eligible(self) -> bool:
        return self.enabled and self.benchmark is not None and self.benchmark.passed


class DeploymentsFile(StrictModel):
    deployments: list[DeploymentConfig]

    @model_validator(mode="after")
    def unique_ids(self) -> "DeploymentsFile":
        ids = [item.deployment_id for item in self.deployments]
        if len(ids) != len(set(ids)):
            raise ValueError("deployment IDs must be unique")
        ports = [item.serving.port for item in self.deployments]
        if len(ports) != len(set(ports)):
            raise ValueError("deployment listen ports must be unique")
        return self


class ScoreWeights(StrictModel):
    quality_weight: NonNegativeFloat
    latency_weight: NonNegativeFloat
    wait_weight: NonNegativeFloat
    switch_weight: NonNegativeFloat
    resource_weight: NonNegativeFloat = 0.25
    loaded_bonus: NonNegativeFloat = 0.2
    batching_bonus: NonNegativeFloat = 0.1
    continuity_bonus: NonNegativeFloat = 0.05
    diversity_bonus: NonNegativeFloat = 0.05


class RoutingFile(StrictModel):
    modes: dict[str, ScoreWeights]

    @model_validator(mode="after")
    def exact_modes(self) -> "RoutingFile":
        if set(self.modes) != {"fast", "balanced", "strong", "max"}:
            raise ValueError("routing modes must be exactly fast, balanced, strong, and max")
        return self


class GpuProfile(StrictModel):
    name: str
    deployments: list[str]
    protected_non_preemptible: bool = True


class GpuProfilesFile(StrictModel):
    profiles: list[GpuProfile]


class UserConfig(StrictModel):
    username: Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")]
    display_name: str
    status: Literal["active", "disabled"] = "disabled"
    scopes: set[Literal["inference", "admin"]] = Field(default_factory=set)
    model_permissions: set[str] = Field(default_factory=set)
    max_concurrency: Annotated[int, Field(ge=1, le=2)] = 1
    daily_token_limit: Annotated[int, Field(ge=0)] = 0


class UsersFile(StrictModel):
    users: list[UserConfig]

    @model_validator(mode="after")
    def at_most_three_unique_users(self) -> "UsersFile":
        usernames = [user.username for user in self.users]
        if len(usernames) > 3:
            raise ValueError("at most three users are supported")
        if len(usernames) != len(set(usernames)):
            raise ValueError("usernames must be unique")
        return self
