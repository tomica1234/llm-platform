import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from llm_platform.common.enums import SkillName
from llm_platform.persistence.models import (
    AgentProfileRow,
    ModelSkillEvaluationRow,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class AgentProfile:
    id: str
    user_id: str
    harness_name: str
    harness_version: str
    config_hash: str
    toolset_hash: str
    metadata: dict[str, Any]
    created_at: datetime
    retired_at: datetime | None


@dataclass(frozen=True, slots=True)
class SkillEvaluation:
    id: str
    model_id: str
    agent_profile_id: str | None
    skill: SkillName
    benchmark: str
    benchmark_version: str | None
    score: float
    sample_count: int
    confidence: float
    raw_metrics: dict[str, Any]
    measured_at: datetime
    created_at: datetime


def timezone_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AgentProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: str,
        harness_name: str,
        harness_version: str,
        config_hash: str,
        toolset_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentProfile:
        row = AgentProfileRow(
            id=f"ap-{uuid.uuid4().hex}",
            user_id=user_id,
            harness_name=harness_name,
            harness_version=harness_version,
            config_hash=config_hash,
            toolset_hash=toolset_hash,
            profile_metadata=metadata or {},
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return self._profile(row)

    async def get(self, profile_id: str) -> AgentProfile | None:
        row = await self.session.get(AgentProfileRow, profile_id)
        return None if row is None else self._profile(row)

    async def list_for_user(self, user_id: str) -> list[AgentProfile]:
        rows = (
            await self.session.scalars(
                select(AgentProfileRow)
                .where(AgentProfileRow.user_id == user_id)
                .order_by(AgentProfileRow.created_at.desc(), AgentProfileRow.id)
            )
        ).all()
        return [self._profile(row) for row in rows]

    @staticmethod
    def _profile(row: AgentProfileRow) -> AgentProfile:
        return AgentProfile(
            id=row.id,
            user_id=row.user_id,
            harness_name=row.harness_name,
            harness_version=row.harness_version,
            config_hash=row.config_hash,
            toolset_hash=row.toolset_hash,
            metadata=dict(row.profile_metadata),
            created_at=timezone_aware(row.created_at),
            retired_at=None if row.retired_at is None else timezone_aware(row.retired_at),
        )


class ModelSkillRepository:
    """Stores immutable evidence and derives profiles without cross-profile fallback."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        model_id: str,
        skill: SkillName,
        benchmark: str,
        score: float,
        sample_count: int,
        confidence: float,
        measured_at: datetime | None = None,
        agent_profile_id: str | None = None,
        benchmark_version: str | None = None,
        raw_metrics: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[SkillEvaluation, bool]:
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")
        if sample_count < 0:
            raise ValueError("sample_count must be non-negative")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        measured = timezone_aware(measured_at or utc_now())
        metrics = raw_metrics or {}
        submission_hash = self._submission_hash(
            model_id=model_id,
            skill=skill,
            benchmark=benchmark,
            benchmark_version=benchmark_version,
            score=score,
            sample_count=sample_count,
            confidence=confidence,
            raw_metrics=metrics,
            measured_at=measured,
        )
        if idempotency_key is not None:
            existing = await self._idempotent_row(agent_profile_id, idempotency_key)
            if existing is not None:
                return self._same_submission(existing, submission_hash), False
        row = ModelSkillEvaluationRow(
            id=f"mse-{uuid.uuid4().hex}",
            model_id=model_id,
            agent_profile_id=agent_profile_id,
            skill=skill.value,
            benchmark=benchmark,
            benchmark_version=benchmark_version,
            score=score,
            sample_count=sample_count,
            confidence=confidence,
            raw_metrics=metrics,
            measured_at=measured,
            idempotency_key=idempotency_key,
            submission_hash=submission_hash if idempotency_key is not None else None,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            if idempotency_key is None:
                raise
            existing = await self._idempotent_row(agent_profile_id, idempotency_key)
            if existing is None:
                raise
            return self._same_submission(existing, submission_hash), False
        await self.session.refresh(row)
        return self._evaluation(row), True

    async def history(
        self,
        model_id: str,
        *,
        skill: SkillName | None = None,
        agent_profile_id: str | None = None,
        global_only: bool = False,
    ) -> list[SkillEvaluation]:
        conditions = [ModelSkillEvaluationRow.model_id == model_id]
        if skill is not None:
            conditions.append(ModelSkillEvaluationRow.skill == skill.value)
        if agent_profile_id is not None:
            conditions.append(ModelSkillEvaluationRow.agent_profile_id == agent_profile_id)
        elif global_only:
            conditions.append(ModelSkillEvaluationRow.agent_profile_id.is_(None))
        rows = (
            await self.session.scalars(
                select(ModelSkillEvaluationRow)
                .where(*conditions)
                .order_by(
                    ModelSkillEvaluationRow.measured_at.desc(),
                    ModelSkillEvaluationRow.created_at.desc(),
                    ModelSkillEvaluationRow.id.desc(),
                )
            )
        ).all()
        return [self._evaluation(row) for row in rows]

    async def profile(
        self, model_id: str, *, agent_profile_id: str | None = None
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for skill in SkillName:
            rows: list[ModelSkillEvaluationRow] = []
            source = "unavailable"
            if agent_profile_id is not None:
                rows = await self._evidence(model_id, skill, agent_profile_id)
                if rows:
                    source = "agent_profile"
            if not rows:
                rows = await self._evidence(model_id, skill, None)
                if rows:
                    source = "global"
            result[skill.value] = self._aggregate(source, rows)
        return result

    async def _evidence(
        self, model_id: str, skill: SkillName, agent_profile_id: str | None
    ) -> list[ModelSkillEvaluationRow]:
        profile_condition = (
            ModelSkillEvaluationRow.agent_profile_id.is_(None)
            if agent_profile_id is None
            else ModelSkillEvaluationRow.agent_profile_id == agent_profile_id
        )
        return list(
            (
                await self.session.scalars(
                    select(ModelSkillEvaluationRow)
                    .where(
                        ModelSkillEvaluationRow.model_id == model_id,
                        ModelSkillEvaluationRow.skill == skill.value,
                        profile_condition,
                    )
                    .order_by(
                        ModelSkillEvaluationRow.measured_at,
                        ModelSkillEvaluationRow.created_at,
                        ModelSkillEvaluationRow.id,
                    )
                )
            ).all()
        )

    async def _idempotent_row(
        self, agent_profile_id: str | None, idempotency_key: str
    ) -> ModelSkillEvaluationRow | None:
        return cast(
            ModelSkillEvaluationRow | None,
            await self.session.scalar(
                select(ModelSkillEvaluationRow).where(
                    ModelSkillEvaluationRow.agent_profile_id == agent_profile_id,
                    ModelSkillEvaluationRow.idempotency_key == idempotency_key,
                )
            ),
        )

    @classmethod
    def _same_submission(
        cls, row: ModelSkillEvaluationRow, submission_hash: str
    ) -> SkillEvaluation:
        if row.submission_hash != submission_hash:
            raise ValueError("idempotency key was already used for a different evaluation")
        return cls._evaluation(row)

    @staticmethod
    def _submission_hash(**values: Any) -> str:
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _aggregate(source: str, rows: list[ModelSkillEvaluationRow]) -> dict[str, Any]:
        if not rows:
            return {
                "score": None,
                "source": "unavailable",
                "confidence": None,
                "sample_count": 0,
                "evidence_count": 0,
                "latest_measured_at": None,
                "benchmarks": [],
            }
        weights = [row.confidence * row.sample_count for row in rows]
        total_weight = sum(weights)
        score = (
            sum(row.score * weight for row, weight in zip(rows, weights, strict=True))
            / total_weight
            if total_weight > 0
            else None
        )
        total_samples = sum(row.sample_count for row in rows)
        aggregate_confidence = (
            sum(row.confidence * row.sample_count for row in rows) / total_samples
            if total_samples > 0
            else None
        )
        return {
            "score": score,
            "source": source,
            "confidence": aggregate_confidence,
            "sample_count": total_samples,
            "evidence_count": len(rows),
            "latest_measured_at": max(timezone_aware(row.measured_at) for row in rows),
            "benchmarks": sorted({row.benchmark for row in rows}),
        }

    @staticmethod
    def _evaluation(row: ModelSkillEvaluationRow) -> SkillEvaluation:
        return SkillEvaluation(
            id=row.id,
            model_id=row.model_id,
            agent_profile_id=row.agent_profile_id,
            skill=SkillName(row.skill),
            benchmark=row.benchmark,
            benchmark_version=row.benchmark_version,
            score=row.score,
            sample_count=row.sample_count,
            confidence=row.confidence,
            raw_metrics=dict(row.raw_metrics),
            measured_at=timezone_aware(row.measured_at),
            created_at=timezone_aware(row.created_at),
        )
