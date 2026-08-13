import asyncio
import json
import os
import secrets
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import typer

from llm_platform.auth.keys import hash_api_key, key_prefix
from llm_platform.common.enums import SkillName
from llm_platform.config.loader import load_bundle
from llm_platform.persistence.database import Database
from llm_platform.persistence.models import AgentProfileRow, ApiKeyRow, ModelRow, UserRow
from llm_platform.persistence.registry import RegistrySyncReport, sync_registry
from llm_platform.persistence.skills import AgentProfileRepository, ModelSkillRepository

app = typer.Typer(help="Administrative control and inspection CLI")
key_app = typer.Typer(help="API key helpers")
config_app = typer.Typer(help="Configuration helpers")
profile_app = typer.Typer(help="Profile inspection and requested changes")
deployment_app = typer.Typer(help="Deployment operations")
model_app = typer.Typer(help="Model registry operations")
maintenance_app = typer.Typer(help="Maintenance mode operations")
rollback_app = typer.Typer(help="Version rollback planning")
agent_profile_app = typer.Typer(help="Agent profile inspection")
skill_app = typer.Typer(help="Model skill evaluation operations")
registry_app = typer.Typer(help="Configuration-to-SQL registry synchronization")
app.add_typer(key_app, name="key")
app.add_typer(config_app, name="config")
app.add_typer(profile_app, name="profile")
app.add_typer(deployment_app, name="deployment")
app.add_typer(model_app, name="model")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(rollback_app, name="rollback")
app.add_typer(agent_profile_app, name="agent-profile")
app.add_typer(skill_app, name="skill")
app.add_typer(registry_app, name="registry")


def database_from_config(config_dir: Path) -> Database:
    bundle = load_bundle(config_dir)
    database_url = os.environ.get("LLM_PLATFORM_DATABASE_URL", bundle.platform.database.url)
    return Database(database_url, echo=bundle.platform.database.echo)


def json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, SkillName):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


async def record_base_skill(
    config_dir: Path,
    model_id: str,
    skill: SkillName,
    benchmark: str,
    benchmark_version: str | None,
    score: float,
    samples: int,
    confidence: float,
) -> dict[str, object]:
    database = database_from_config(config_dir)
    try:
        async with database.session() as session:
            if await session.get(ModelRow, model_id) is None:
                raise typer.BadParameter(f"model {model_id!r} is not registered")
            evaluation, _ = await ModelSkillRepository(session).record(
                model_id=model_id,
                skill=skill,
                benchmark=benchmark,
                benchmark_version=benchmark_version,
                score=score,
                sample_count=samples,
                confidence=confidence,
            )
            return asdict(evaluation)
    finally:
        await database.dispose()


@skill_app.command("record-base")
def skill_record_base(
    model_id: str = typer.Option(..., "--model"),
    skill: SkillName = typer.Option(..., "--skill"),
    benchmark: str = typer.Option(..., "--benchmark"),
    score: float = typer.Option(..., min=0.0, max=1.0),
    samples: int = typer.Option(..., min=0),
    confidence: float = typer.Option(..., min=0.0, max=1.0),
    benchmark_version: str | None = typer.Option(None, "--benchmark-version"),
    json_output: bool = typer.Option(False, "--json"),
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
) -> None:
    result = asyncio.run(
        record_base_skill(
            config_dir,
            model_id,
            skill,
            benchmark,
            benchmark_version,
            score,
            samples,
            confidence,
        )
    )
    if json_output:
        typer.echo(json.dumps(result, default=json_default, sort_keys=True))
    else:
        typer.echo(f"recorded global evaluation {result['id']}")


async def skill_query(
    config_dir: Path,
    model_id: str,
    agent_profile_id: str | None,
    *,
    profile: bool,
) -> object:
    database = database_from_config(config_dir)
    try:
        async with database.session() as session:
            if (
                agent_profile_id is not None
                and await session.get(AgentProfileRow, agent_profile_id) is None
            ):
                raise typer.BadParameter(f"agent profile {agent_profile_id!r} was not found")
            repository = ModelSkillRepository(session)
            if profile:
                return await repository.profile(model_id, agent_profile_id=agent_profile_id)
            return [
                asdict(item)
                for item in await repository.history(
                    model_id,
                    agent_profile_id=agent_profile_id,
                    global_only=agent_profile_id is None,
                )
            ]
    finally:
        await database.dispose()


@skill_app.command("history")
def skill_history(
    model_id: str = typer.Option(..., "--model"),
    agent_profile_id: str | None = typer.Option(None, "--agent-profile"),
    json_output: bool = typer.Option(False, "--json"),
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
) -> None:
    result = asyncio.run(skill_query(config_dir, model_id, agent_profile_id, profile=False))
    if json_output:
        typer.echo(json.dumps(result, default=json_default, sort_keys=True))
        return
    assert isinstance(result, list)
    for row in result:
        typer.echo(f"{row['id']} {row['skill']} {row['benchmark']} score={row['score']:.4f}")


@skill_app.command("profile")
def skill_profile(
    model_id: str = typer.Option(..., "--model"),
    agent_profile_id: str | None = typer.Option(None, "--agent-profile"),
    json_output: bool = typer.Option(False, "--json"),
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
) -> None:
    result = asyncio.run(skill_query(config_dir, model_id, agent_profile_id, profile=True))
    if json_output:
        typer.echo(json.dumps(result, default=json_default, sort_keys=True))
        return
    assert isinstance(result, dict)
    for name, value in result.items():
        score = value["score"]
        typer.echo(
            f"{name}: {'unavailable' if score is None else f'{score:.4f}'} ({value['source']})"
        )


async def list_profiles(config_dir: Path, user_id: str) -> list[dict[str, object]]:
    database = database_from_config(config_dir)
    try:
        async with database.session() as session:
            if await session.get(UserRow, user_id) is None:
                raise typer.BadParameter(f"user {user_id!r} was not found")
            return [
                asdict(profile)
                for profile in await AgentProfileRepository(session).list_for_user(user_id)
            ]
    finally:
        await database.dispose()


@agent_profile_app.command("list")
def agent_profile_list(
    user_id: str = typer.Option(..., "--user"),
    json_output: bool = typer.Option(False, "--json"),
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
) -> None:
    result = asyncio.run(list_profiles(config_dir, user_id))
    if json_output:
        typer.echo(json.dumps(result, default=json_default, sort_keys=True))
        return
    for profile in result:
        typer.echo(f"{profile['id']} {profile['harness_name']}@{profile['harness_version']}")


@app.command()
def status(config_dir: Path = Path("config")) -> None:
    bundle = load_bundle(config_dir)
    typer.echo(
        json.dumps(
            {
                "mode": bundle.platform.scheduler.mode,
                "config_revision": bundle.platform.config_revision,
                "enabled_models": sum(model.enabled for model in bundle.models.models),
                "enabled_deployments": sum(item.enabled for item in bundle.deployments.deployments),
            },
            indent=2,
        )
    )


@config_app.command("validate")
def validate(config_dir: Path = Path("config")) -> None:
    bundle = load_bundle(config_dir)
    typer.echo(
        f"valid: revision={bundle.platform.config_revision} "
        f"models={len(bundle.models.models)} deployments={len(bundle.deployments.deployments)}"
    )


def format_registry_report(report: RegistrySyncReport, *, apply: bool) -> str:
    prefix = "applied" if apply else "dry-run"
    categories = (
        ("created models", report.created_models),
        ("updated models", report.updated_models),
        ("disabled stale models", report.disabled_stale_models),
        ("created deployments", report.created_deployments),
        ("updated deployments", report.updated_deployments),
        ("disabled stale deployments", report.disabled_stale_deployments),
    )
    lines = [prefix]
    lines.extend(f"{name}: {', '.join(ids) if ids else '(none)'}" for name, ids in categories)
    return "\n".join(lines)


async def synchronize_registry(config_dir: Path, *, apply: bool) -> RegistrySyncReport:
    bundle = load_bundle(config_dir)
    database_url = os.environ.get("LLM_PLATFORM_DATABASE_URL", bundle.platform.database.url)
    database = Database(database_url, echo=bundle.platform.database.echo)
    try:
        async with database.session() as session:
            try:
                report = await sync_registry(session, bundle, apply=apply)
                if apply:
                    await session.commit()
                else:
                    await session.rollback()
                return report
            except Exception:
                await session.rollback()
                raise
    finally:
        await database.dispose()


@registry_app.command("sync")
def registry_sync(
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
    apply: bool = typer.Option(False, "--apply"),
) -> None:
    """Synchronize the validated configuration registry into SQL."""
    report = asyncio.run(synchronize_registry(config_dir, apply=apply))
    typer.echo(format_registry_report(report, apply=apply))


@key_app.command("hash")
def key_hash(value: str | None = typer.Option(None, prompt=True, hide_input=True)) -> None:
    """Hash a key read from a protected prompt."""
    if value is None:
        raise typer.BadParameter("key is required")
    typer.echo(f"prefix={key_prefix(value)}")
    typer.echo(hash_api_key(value))


async def provision_key(config_dir: Path, username: str) -> str:
    bundle = load_bundle(config_dir)
    users = [user for user in bundle.users.users if user.username == username]
    if len(users) != 1:
        raise typer.BadParameter("user must be uniquely configured")
    configured = users[0]
    if configured.status != "active":
        raise typer.BadParameter("user must be explicitly enabled before key provisioning")
    database_url = os.environ.get("LLM_PLATFORM_DATABASE_URL", bundle.platform.database.url)
    database = Database(database_url, echo=bundle.platform.database.echo)
    plaintext = "llmp_" + secrets.token_urlsafe(32)
    try:
        async with database.session() as session:
            row = await session.get(UserRow, username)
            if row is None:
                row = UserRow(
                    id=username,
                    linux_username=username,
                    display_name=configured.display_name,
                    status="active",
                    default_policy="balanced",
                    max_concurrency=configured.max_concurrency,
                    model_permissions=sorted(configured.model_permissions),
                )
                session.add(row)
                await session.flush()
            key_row = ApiKeyRow(
                id=f"key-{uuid.uuid4().hex}",
                user_id=username,
                key_prefix=key_prefix(plaintext),
                key_hash=hash_api_key(plaintext),
                scopes=sorted(configured.scopes),
                expires_at=None,
                last_used_at=None,
                revoked_at=None,
            )
            session.add(key_row)
            await session.commit()
    finally:
        await database.dispose()
    return plaintext


@key_app.command("provision")
def key_provision(
    username: str,
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
    apply: bool = typer.Option(False, "--apply"),
) -> None:
    if not apply:
        typer.echo(f"dry-run: would provision a new hashed key for {username}")
        return
    plaintext = asyncio.run(provision_key(config_dir, username))
    typer.echo("Store this key now; it will not be shown again:")
    typer.echo(plaintext)


@profile_app.command("show")
def profile_show(config_dir: Path = Path("config")) -> None:
    bundle = load_bundle(config_dir)
    for profile in bundle.gpu_profiles.profiles:
        typer.echo(f"{profile.name}: {', '.join(profile.deployments) or '(none)'}")


@profile_app.command("set")
def profile_set(name: str, apply: bool = typer.Option(False, "--apply")) -> None:
    if not apply:
        typer.echo(f"dry-run: would request profile {name}")
        return
    raise typer.BadParameter("live control API is not configured; no state was changed")


@app.command()
def queue() -> None:
    typer.echo("queue inspection requires a configured admin API")


@app.command()
def backends() -> None:
    typer.echo("backend inspection requires a configured admin API")


@app.command()
def gpus() -> None:
    typer.echo("GPU inspection requires Slurm/NVML on the configured target host")


@app.command()
def routes(request: str = typer.Option(..., "--request")) -> None:
    typer.echo(f"route {request} inspection requires a configured admin API")


@app.command()
def drain(backend: str, apply: bool = typer.Option(False, "--apply")) -> None:
    typer.echo(f"{'would drain' if not apply else 'cannot drain without admin API:'} {backend}")


@app.command()
def restart(backend: str, apply: bool = typer.Option(False, "--apply")) -> None:
    typer.echo(f"{'would restart' if not apply else 'cannot restart without admin API:'} {backend}")


def deployment_change(deployment_id: str, action: str, apply: bool) -> None:
    if apply:
        raise typer.BadParameter("live registry admin API is not configured; no state changed")
    typer.echo(f"dry-run: would {action} deployment {deployment_id}")


@deployment_app.command("enable")
def deployment_enable(deployment_id: str, apply: bool = typer.Option(False, "--apply")) -> None:
    deployment_change(deployment_id, "enable", apply)


@deployment_app.command("disable")
def deployment_disable(deployment_id: str, apply: bool = typer.Option(False, "--apply")) -> None:
    deployment_change(deployment_id, "disable", apply)


@deployment_app.command("benchmark")
def deployment_benchmark(deployment_id: str) -> None:
    typer.echo(f"run: scripts/benchmark-deployment.sh {deployment_id} --dry-run")


@model_app.command("add")
def model_add(manifest: Path) -> None:
    typer.echo(f"run reviewed disabled-first workflow for {manifest.resolve()}")


@model_app.command("verify")
def model_verify(model_id: str) -> None:
    typer.echo(f"model {model_id} verification requires the target model store")


@maintenance_app.command("enter")
def maintenance_enter(apply: bool = typer.Option(False, "--apply")) -> None:
    profile_set("maintenance", apply)


@maintenance_app.command("exit")
def maintenance_exit(apply: bool = typer.Option(False, "--apply")) -> None:
    profile_set("auto", apply)


@rollback_app.command("gateway")
def rollback_gateway(version: str) -> None:
    typer.echo(f"run: scripts/rollback-release.sh gateway {version} --dry-run")


@rollback_app.command("runtime")
def rollback_runtime(runtime: str, version: str) -> None:
    typer.echo(f"run: scripts/rollback-release.sh {runtime} {version} --dry-run")


if __name__ == "__main__":
    app()
