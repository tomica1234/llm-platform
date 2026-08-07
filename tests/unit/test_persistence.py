import pytest

from llm_platform.persistence.database import Database
from llm_platform.persistence.models import InferenceRequestRow
from llm_platform.persistence.repositories import RequestRepository


@pytest.mark.asyncio
async def test_request_persists_hash_not_prompt_body() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_tests()
    async with database.session() as session:
        repository = RequestRepository(session)
        body = {"model": "auto", "input": "private source code"}
        first = await repository.create(
            request_id="r1",
            user_id="u1",
            requested_model="auto",
            priority="agent",
            body=body,
            idempotency_key="same",
        )
        second = await repository.create(
            request_id="r2",
            user_id="u1",
            requested_model="auto",
            priority="agent",
            body=body,
            idempotency_key="same",
        )
        assert first.request_id == second.request_id == "r1"
        row = await session.get(InferenceRequestRow, "r1")
        assert row is not None
        assert row.body_hash is not None
        assert "private source code" not in repr(row.__dict__)
        assert await repository.transition("r1", {"queued"}, "running")
        assert not await repository.transition("r1", {"queued"}, "running")
        recovered = await repository.recover_unfinished()
        assert [record.request_id for record in recovered] == ["r1"]
    await database.dispose()
