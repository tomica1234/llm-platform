from datetime import UTC, datetime

import pytest

from llm_platform.common.enums import SkillName
from llm_platform.persistence.database import Database
from llm_platform.persistence.models import ModelRow, UserRow
from llm_platform.persistence.skills import AgentProfileRepository, ModelSkillRepository


async def seed_identity(database: Database) -> None:
    async with database.session() as session:
        session.add(
            UserRow(
                id="shunta",
                linux_username="shunta",
                display_name="Shunta",
                model_permissions=["qwen"],
            )
        )
        session.add(
            ModelRow(
                id="qwen",
                family="qwen",
                revision="test",
                capabilities={},
                license="test",
                enabled=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_profile_ownership_and_exact_profile_fallback() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_tests()
    await seed_identity(database)
    async with database.session() as session:
        profiles = AgentProfileRepository(session)
        v1 = await profiles.create(
            user_id="shunta",
            harness_name="agent",
            harness_version="1",
            config_hash="a" * 64,
            toolset_hash="b" * 64,
        )
        v2 = await profiles.create(
            user_id="shunta",
            harness_name="agent",
            harness_version="2",
            config_hash="c" * 64,
            toolset_hash="d" * 64,
        )
        repository = ModelSkillRepository(session)
        base, _ = await repository.record(
            model_id="qwen",
            skill=SkillName.CODING,
            benchmark="global",
            score=0.70,
            sample_count=400,
            confidence=0.95,
        )
        v1_evaluation, _ = await repository.record(
            model_id="qwen",
            agent_profile_id=v1.id,
            skill=SkillName.CODING,
            benchmark="agent-bench",
            score=0.82,
            sample_count=100,
            confidence=0.9,
        )
        assert (await repository.profile("qwen"))["coding"]["score"] == pytest.approx(0.70)
        assert (await repository.profile("qwen", agent_profile_id=v1.id))["coding"][
            "score"
        ] == pytest.approx(0.82)
        v2_profile = await repository.profile("qwen", agent_profile_id=v2.id)
        assert v2_profile["coding"]["score"] == pytest.approx(0.70)
        assert v2_profile["coding"]["source"] == "global"
        history = await repository.history("qwen")
        assert {item.id for item in history} == {base.id, v1_evaluation.id}
    await database.dispose()


@pytest.mark.asyncio
async def test_weighted_aggregation_and_idempotent_submission() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_tests()
    await seed_identity(database)
    async with database.session() as session:
        profile = await AgentProfileRepository(session).create(
            user_id="shunta",
            harness_name="agent",
            harness_version="1",
            config_hash="a" * 64,
            toolset_hash="b" * 64,
        )
        repository = ModelSkillRepository(session)
        measured = datetime(2026, 8, 13, tzinfo=UTC)
        first, created = await repository.record(
            model_id="qwen",
            agent_profile_id=profile.id,
            skill=SkillName.CODING,
            benchmark="small",
            score=1.0,
            sample_count=1,
            confidence=1.0,
            measured_at=measured,
            idempotency_key="run-1",
        )
        retry, retry_created = await repository.record(
            model_id="qwen",
            agent_profile_id=profile.id,
            skill=SkillName.CODING,
            benchmark="small",
            score=1.0,
            sample_count=1,
            confidence=1.0,
            measured_at=measured,
            idempotency_key="run-1",
        )
        await repository.record(
            model_id="qwen",
            agent_profile_id=profile.id,
            skill=SkillName.CODING,
            benchmark="large",
            score=0.5,
            sample_count=100,
            confidence=1.0,
            measured_at=datetime(2026, 8, 14, tzinfo=UTC),
        )
        coding = (await repository.profile("qwen", agent_profile_id=profile.id))["coding"]
        assert created is True
        assert retry_created is False
        assert retry.id == first.id
        assert coding["score"] == pytest.approx(51 / 101)
        assert coding["confidence"] == pytest.approx(1.0)
        assert coding["sample_count"] == 101
        assert coding["evidence_count"] == 2
        assert coding["benchmarks"] == ["large", "small"]
        with pytest.raises(ValueError, match="different evaluation"):
            await repository.record(
                model_id="qwen",
                agent_profile_id=profile.id,
                skill=SkillName.CODING,
                benchmark="small",
                score=0.1,
                sample_count=1,
                confidence=1.0,
                measured_at=measured,
                idempotency_key="run-1",
            )
    await database.dispose()
