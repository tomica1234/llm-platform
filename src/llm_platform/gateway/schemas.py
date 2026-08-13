import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_platform.common.enums import SkillName

HASH_PATTERN = r"^[0-9a-f]{64}$"
SENSITIVE_KEY_PARTS = ("api_key", "apikey", "password", "secret", "token", "prompt", "repo")


def validate_safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode()) > 16_384:
        raise ValueError("metadata must not exceed 16 KiB")

    def check(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = str(key).lower().replace("-", "_")
                if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                    raise ValueError(f"sensitive metadata key is not allowed: {key}")
                check(nested)
        elif isinstance(item, list):
            for nested in item:
                check(nested)

    check(value)
    return value


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentProfileCreate(ApiModel):
    harness_name: str = Field(min_length=1, max_length=128)
    harness_version: str = Field(min_length=1, max_length=128)
    config_hash: str = Field(pattern=HASH_PATTERN)
    toolset_hash: str = Field(pattern=HASH_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def safe_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_safe_metadata(value)


class SkillEvaluationCreate(ApiModel):
    agent_profile_id: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=128)
    skill: SkillName
    benchmark: str = Field(min_length=1, max_length=128)
    benchmark_version: str | None = Field(default=None, max_length=128)
    score: float = Field(ge=0.0, le=1.0)
    sample_count: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    measured_at: datetime

    @field_validator("raw_metrics")
    @classmethod
    def safe_raw_metrics(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_safe_metadata(value)

    @field_validator("measured_at")
    @classmethod
    def aware_measurement_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("measured_at must include a timezone")
        return value
