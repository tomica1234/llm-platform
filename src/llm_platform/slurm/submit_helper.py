import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from llm_platform.common.errors import ConfigurationError
from llm_platform.common.subprocesses import AsyncioCommandRunner, CommandRunner
from llm_platform.config.loader import load_bundle
from llm_platform.slurm.cli import render_sbatch_script, validate_identifier


class SubmitRequest:
    """A deliberately tiny protocol: all launch details are resolved from reviewed config."""

    def __init__(self, payload: Any) -> None:
        if not isinstance(payload, dict) or set(payload) != {
            "operation",
            "deployment_id",
            "instance_id",
        }:
            raise ValueError("submit request has unexpected fields")
        if payload["operation"] != "submit":
            raise ValueError("invalid submit operation")
        if not isinstance(payload["deployment_id"], str) or not isinstance(
            payload["instance_id"], str
        ):
            raise ValueError("request identifiers must be strings")
        self.deployment_id = validate_identifier(payload["deployment_id"], "deployment ID")
        self.instance_id = validate_identifier(payload["instance_id"], "instance ID")


class SubmitService:
    def __init__(
        self,
        config_dir: Path,
        spool_dir: Path,
        log_dir: Path,
        runner: CommandRunner | None = None,
        *,
        application_current: Path = Path("/opt/llm-platform/app/current"),
    ) -> None:
        for path, label in ((config_dir, "config"), (spool_dir, "spool"), (log_dir, "log")):
            if not path.is_absolute():
                raise ValueError(f"{label} directory must be absolute")
        self.config_dir = config_dir
        self.spool_dir = spool_dir
        self.log_dir = log_dir
        self.runner = runner or AsyncioCommandRunner()
        self.application_current = application_current

    async def submit(self, payload: Any) -> dict[str, Any]:
        try:
            request = SubmitRequest(payload)
            bundle = load_bundle(self.config_dir)
            matches = [
                item
                for item in bundle.deployments.deployments
                if item.deployment_id == request.deployment_id and item.enabled
            ]
            if len(matches) != 1:
                raise ValueError("deployment is not uniquely enabled in reviewed configuration")
            deployment = matches[0]
            self.spool_dir.mkdir(parents=True, exist_ok=True)
            script_path = self.spool_dir / f"{request.instance_id}.sbatch"
            output_path = self.log_dir / f"{request.instance_id}.log"
            script = render_sbatch_script(
                deployment,
                request.instance_id,
                application_current=self.application_current,
                config_dir=self.config_dir,
                qos=bundle.platform.slurm.qos,
                output_path=output_path,
            )
            script_path.write_text(script, encoding="utf-8")  # noqa: ASYNC240
            result = await self.runner.run(
                ("sbatch", "--parsable", str(script_path)), timeout_seconds=30
            )
            if result.returncode != 0:
                return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
            job_id = result.stdout.strip().split(";", 1)[0]
            if not job_id.isdigit():
                return {"ok": False, "error": "sbatch returned an invalid job ID"}
            return {"ok": True, "stdout": result.stdout}
        except (ConfigurationError, ValueError, OSError, ValidationError) as exc:
            return {"ok": False, "error": str(exc)}

    async def dispatch(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict) and payload.get("operation") == "cancel":
            if set(payload) != {"operation", "job_id"} or not isinstance(payload["job_id"], str):
                return {"ok": False, "error": "cancel request has unexpected fields"}
            job_id = payload["job_id"]
            if not job_id.isdigit():
                return {"ok": False, "error": "invalid Slurm job ID"}
            result = await self.runner.run(("scancel", job_id), timeout_seconds=30)
            if result.returncode != 0:
                return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
            return {"ok": True}
        return await self.submit(payload)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if len(line) > 4096:
                response = {"ok": False, "error": "request is too large"}
            else:
                response = await self.dispatch(json.loads(line))
        except (TimeoutError, json.JSONDecodeError) as exc:
            response = {"ok": False, "error": f"invalid request: {exc}"}
        writer.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def serve(socket_path: Path, service: SubmitService) -> None:
    if not socket_path.is_absolute():
        raise ValueError("socket path must be absolute")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():  # noqa: ASYNC240 -- one-time startup setup
        if not socket_path.is_socket():  # noqa: ASYNC240 -- one-time startup setup
            raise RuntimeError("refusing to replace non-socket submit path")
        socket_path.unlink()  # noqa: ASYNC240 -- one-time startup setup
    server = await asyncio.start_unix_server(service.handle, path=str(socket_path))
    os.chmod(socket_path, 0o660)
    async with server:
        await server.serve_forever()


def run(
    config: Annotated[Path, typer.Option("--config")] = Path("/etc/llm-platform"),
    socket: Annotated[Path, typer.Option("--socket")] = Path(
        "/run/llm-platform/backend-submit.sock"
    ),
    spool: Annotated[Path, typer.Option("--spool")] = Path("/var/lib/llm-platform/slurm"),
    log_dir: Annotated[Path, typer.Option("--log-dir")] = Path("/var/log/llm-platform/backends"),
) -> None:
    asyncio.run(serve(socket, SubmitService(config, spool, log_dir)))


if __name__ == "__main__":
    typer.run(run)
