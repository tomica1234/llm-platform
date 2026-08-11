from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from llm_platform.admin_cli.main import provision_key
from llm_platform.auth.keys import authenticate, hash_api_key, key_prefix
from llm_platform.auth.sqlalchemy_store import SqlAlchemyKeyStore
from llm_platform.persistence.models import ApiKeyRow, Base, UserRow


def configured_bundle(username: str) -> Any:
    configured_user = SimpleNamespace(
        username=username,
        display_name=username.title(),
        status="active",
        max_concurrency=2,
        model_permissions=["qwen"],
        scopes=["inference"],
    )
    return SimpleNamespace(
        users=SimpleNamespace(users=[configured_user]),
        platform=SimpleNamespace(
            database=SimpleNamespace(url="unused", echo=False),
        ),
    )


class AsyncSessionFacade:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def __aenter__(self) -> "AsyncSessionFacade":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is not None:
            self.session.rollback()
        self.session.close()

    def add(self, row: Any) -> None:
        self.session.add(row)

    async def get(self, model: Any, identifier: Any) -> Any:
        return self.session.get(model, identifier)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def execute(self, statement: Any) -> Any:
        return self.session.execute(statement)

    async def scalar(self, statement: Any) -> Any:
        return self.session.scalar(statement)

    async def scalars(self, statement: Any) -> Any:
        return self.session.scalars(statement)


class ForeignKeyDatabase:
    def __init__(self, path: Path) -> None:
        self.engine = create_engine(f"sqlite:///{path}")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection: Any, _: Any) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        with self.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSessionFacade:
        return AsyncSessionFacade(self.session_factory())

    def sessions(self) -> AsyncSessionFacade:
        return self.session()

    async def dispose(self) -> None:
        self.engine.dispose()


def foreign_key_database(path: Path) -> ForeignKeyDatabase:
    return ForeignKeyDatabase(path)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provision_key_creates_user_then_adds_authenticating_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = foreign_key_database(tmp_path / "provision.db")
    monkeypatch.setattr(
        "llm_platform.admin_cli.main.load_bundle", lambda _: configured_bundle("shunta")
    )
    monkeypatch.setattr("llm_platform.admin_cli.main.Database", lambda *_args, **_kwargs: database)

    first_key = await provision_key(tmp_path / "config", "shunta")
    second_key = await provision_key(tmp_path / "config", "shunta")

    async with database.session() as session:
        user = await session.get(UserRow, "shunta")
        key_count = await session.scalar(
            select(func.count()).select_from(ApiKeyRow).where(ApiKeyRow.user_id == "shunta")
        )
    assert user is not None
    assert key_count == 2
    store = SqlAlchemyKeyStore(cast(Any, database.sessions))
    first_principal = await authenticate(first_key, store)
    second_principal = await authenticate(second_key, store)
    assert first_principal.user_id == "shunta"
    assert second_principal.user_id == "shunta"
    await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_provision_rolls_back_flushed_user_and_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = foreign_key_database(tmp_path / "rollback.db")
    collision_key = "existing-plaintext-key"
    async with database.session() as session:
        session.add(
            UserRow(
                id="existing",
                linux_username="existing",
                display_name="Existing",
                status="active",
                default_policy="balanced",
                max_concurrency=1,
                model_permissions=[],
            )
        )
        await session.flush()
        session.add(
            ApiKeyRow(
                id="key-collision",
                user_id="existing",
                key_prefix=key_prefix(collision_key),
                key_hash=hash_api_key(collision_key),
                scopes=[],
                expires_at=None,
                last_used_at=None,
                revoked_at=None,
            )
        )
        await session.commit()

    monkeypatch.setattr(
        "llm_platform.admin_cli.main.load_bundle", lambda _: configured_bundle("shunta")
    )
    monkeypatch.setattr("llm_platform.admin_cli.main.Database", lambda *_args, **_kwargs: database)
    monkeypatch.setattr(
        "llm_platform.admin_cli.main.uuid.uuid4",
        lambda: SimpleNamespace(hex="collision"),
    )

    with pytest.raises(IntegrityError):
        await provision_key(tmp_path / "config", "shunta")

    async with database.session() as session:
        assert await session.get(UserRow, "shunta") is None
        keys = (await session.scalars(select(ApiKeyRow))).all()
    assert [key.id for key in keys] == ["key-collision"]
    await database.dispose()
