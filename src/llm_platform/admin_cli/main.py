import asyncio
import json
import os
import secrets
import uuid
from pathlib import Path

import typer

from llm_platform.auth.keys import hash_api_key, key_prefix
from llm_platform.config.loader import load_bundle
from llm_platform.persistence.database import Database
from llm_platform.persistence.models import ApiKeyRow, UserRow

app = typer.Typer(help="Administrative control and inspection CLI")
key_app = typer.Typer(help="API key helpers")
config_app = typer.Typer(help="Configuration helpers")
profile_app = typer.Typer(help="Profile inspection and requested changes")
deployment_app = typer.Typer(help="Deployment operations")
model_app = typer.Typer(help="Model registry operations")
maintenance_app = typer.Typer(help="Maintenance mode operations")
rollback_app = typer.Typer(help="Version rollback planning")
app.add_typer(key_app, name="key")
app.add_typer(config_app, name="config")
app.add_typer(profile_app, name="profile")
app.add_typer(deployment_app, name="deployment")
app.add_typer(model_app, name="model")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(rollback_app, name="rollback")


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
