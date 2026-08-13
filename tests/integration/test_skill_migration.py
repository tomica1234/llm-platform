import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_agent_profile_migration_upgrades_temporary_sqlite_without_data_loss(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "0002")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO users
            (id, linux_username, display_name, status, default_policy, max_concurrency,
             model_permissions, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("existing", "existing", "Existing", "active", "balanced", 1, "[]", "2026-01-01"),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "agent_profiles" in tables
        assert "model_skill_evaluations" in tables
        assert connection.execute(
            "SELECT display_name FROM users WHERE id = 'existing'"
        ).fetchone() == ("Existing",)
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert revision == ("0003",)
