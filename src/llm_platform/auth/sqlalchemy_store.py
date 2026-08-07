from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm_platform.auth.keys import ApiPrincipal, KeyRecord
from llm_platform.persistence.models import ApiKeyRow, UserRow


class SqlAlchemyKeyStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def candidates(self, prefix: str) -> list[KeyRecord]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(ApiKeyRow, UserRow)
                    .join(UserRow, UserRow.id == ApiKeyRow.user_id)
                    .where(ApiKeyRow.key_prefix == prefix, UserRow.status == "active")
                )
            ).all()
        records: list[KeyRecord] = []
        for key, user in rows:
            expires_at = key.expires_at
            revoked_at = key.revoked_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if revoked_at is not None and revoked_at.tzinfo is None:
                revoked_at = revoked_at.replace(tzinfo=UTC)
            records.append(
                KeyRecord(
                    key.id,
                    key.key_prefix,
                    key.key_hash,
                    ApiPrincipal(
                        user.id,
                        frozenset(key.scopes),
                        frozenset(user.model_permissions),
                        user.max_concurrency,
                    ),
                    expires_at,
                    revoked_at,
                )
            )
        return records
