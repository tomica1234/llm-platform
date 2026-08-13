from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now().astimezone()


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    linux_username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    default_policy: Mapped[str] = mapped_column(String(32), default="balanced")
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    model_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    repository_hash: Mapped[str] = mapped_column(String(128))
    initial_commit: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStepRow(Base):
    __tablename__ = "agent_steps"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    phase: Mapped[str] = mapped_column(String(32))
    task_features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    selected_model: Mapped[str | None] = mapped_column(String(128))
    selected_runtime: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InferenceRequestRow(Base):
    __tablename__ = "inference_requests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    mode: Mapped[str] = mapped_column(String(32))
    requested_model: Mapped[str] = mapped_column(String(255))
    selected_deployment: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), index=True)
    body_hash: Mapped[str | None] = mapped_column(String(128))
    body_size: Mapped[int] = mapped_column(Integer, default=0)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))


class RouteDecisionRow(Base):
    __tablename__ = "route_decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("inference_requests.id"), index=True)
    config_revision: Mapped[str] = mapped_column(String(128))
    candidate_scores: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    hard_filter_reasons: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    selected_deployment: Mapped[str] = mapped_column(String(128))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)


class ModelRow(Base):
    __tablename__ = "models"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    family: Mapped[str] = mapped_column(String(128))
    revision: Mapped[str] = mapped_column(String(255))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    license: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentProfileRow(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    harness_name: Mapped[str] = mapped_column(String(128))
    harness_version: Mapped[str] = mapped_column(String(128))
    config_hash: Mapped[str] = mapped_column(String(64))
    toolset_hash: Mapped[str] = mapped_column(String(64))
    profile_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelSkillEvaluationRow(Base):
    __tablename__ = "model_skill_evaluations"
    __table_args__ = (
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_skill_score_range"),
        CheckConstraint("sample_count >= 0", name="ck_skill_sample_count"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0", name="ck_skill_confidence_range"
        ),
        UniqueConstraint(
            "agent_profile_id",
            "idempotency_key",
            name="uq_skill_evaluation_profile_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    agent_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_profiles.id"), index=True
    )
    skill: Mapped[str] = mapped_column(String(64), index=True)
    benchmark: Mapped[str] = mapped_column(String(128))
    benchmark_version: Mapped[str | None] = mapped_column(String(128))
    score: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    submission_hash: Mapped[str | None] = mapped_column(String(64))


class ModelArtifactRow(Base):
    __tablename__ = "model_artifacts"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    format: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DeploymentRow(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    runtime: Mapped[str] = mapped_column(String(64))
    profile: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    benchmark_id: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class BackendInstanceRow(Base):
    __tablename__ = "backend_instances"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployments.id"), index=True)
    slurm_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32))
    port: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class GpuProfileRow(Base):
    __tablename__ = "gpu_profiles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    desired_deployments: Mapped[list[str]] = mapped_column(JSON, default=list)
    config_revision: Mapped[str] = mapped_column(String(128))


class ControlPlaneStateRow(Base):
    __tablename__ = "control_plane_state"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="singleton")
    desired_profile: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BenchmarkRow(Base):
    __tablename__ = "benchmarks"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployments.id"), index=True)
    hardware_revision: Mapped[str] = mapped_column(String(128))
    runtime_revision: Mapped[str] = mapped_column(String(128))
    startup_seconds: Mapped[float] = mapped_column(Float)
    prompt_tps: Mapped[float] = mapped_column(Float)
    generation_tps: Mapped[float] = mapped_column(Float)
    concurrent_tps: Mapped[float] = mapped_column(Float)
    max_vram: Mapped[float] = mapped_column(Float)
    max_ram: Mapped[float] = mapped_column(Float)
    quality_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(255))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OutcomeRow(Base):
    __tablename__ = "routing_outcomes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    assignment_bucket: Mapped[str] = mapped_column(String(64))
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    selected_model: Mapped[str] = mapped_column(String(128))
    selected_runtime: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean)
    elapsed_seconds: Mapped[float] = mapped_column(Float)
    human_accepted: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
