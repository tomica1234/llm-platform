from datetime import datetime, timedelta

import pytest

from llm_platform.auth.keys import (
    ApiPrincipal,
    InMemoryKeyStore,
    KeyRecord,
    authenticate,
    hash_api_key,
    key_prefix,
    verify_api_key,
)
from llm_platform.auth.sqlalchemy_store import SqlAlchemyKeyStore
from llm_platform.common.errors import AuthenticationError, AuthorizationError
from llm_platform.persistence.database import Database
from llm_platform.persistence.models import ApiKeyRow, UserRow


def test_scrypt_hash_round_trip_and_random_salt() -> None:
    key = "local-test-key-with-enough-entropy"
    first = hash_api_key(key)
    second = hash_api_key(key)
    assert first != second
    assert verify_api_key(key, first)
    assert not verify_api_key(f"{key}-wrong", first)
    assert key not in first


@pytest.mark.asyncio
async def test_authenticate_scope_expiry_and_revocation() -> None:
    key = "local-test-key-with-enough-entropy"
    principal = ApiPrincipal("alice", frozenset({"inference"}), frozenset({"qwen"}))
    record = KeyRecord("id", key_prefix(key), hash_api_key(key), principal)
    store = InMemoryKeyStore([record])
    assert await authenticate(key, store) == principal
    with pytest.raises(AuthorizationError):
        principal.require_scope("admin")
    record.expires_at = datetime.now().astimezone() - timedelta(seconds=1)
    with pytest.raises(AuthenticationError, match="expired"):
        await authenticate(key, store)


@pytest.mark.asyncio
async def test_wrong_key_does_not_authenticate() -> None:
    key = "local-test-key-with-enough-entropy"
    principal = ApiPrincipal("alice", frozenset({"inference"}), frozenset({"qwen"}))
    store = InMemoryKeyStore([KeyRecord("id", key_prefix(key), hash_api_key(key), principal)])
    with pytest.raises(AuthenticationError):
        await authenticate("other-key-with-enough-entropy", store)


@pytest.mark.asyncio
async def test_sqlalchemy_key_store_authenticates_persisted_hash() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_tests()
    key = "persistent-key-with-enough-entropy"
    async with database.session() as session:
        session.add(
            UserRow(
                id="alice",
                linux_username="alice",
                display_name="Alice",
                status="active",
                model_permissions=["qwen"],
                max_concurrency=1,
            )
        )
        session.add(
            ApiKeyRow(
                id="key-1",
                user_id="alice",
                key_prefix=key_prefix(key),
                key_hash=hash_api_key(key),
                scopes=["inference"],
                expires_at=None,
                last_used_at=None,
                revoked_at=None,
            )
        )
        await session.commit()
    principal = await authenticate(key, SqlAlchemyKeyStore(database.sessions))
    assert principal.user_id == "alice"
    assert principal.model_permissions == frozenset({"qwen"})
    await database.dispose()
