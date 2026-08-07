import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from llm_platform.common.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult: ...


def validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if not argv or not argv[0]:
        raise ConfigurationError("an executable is required")
    values = tuple(str(value) for value in argv)
    if any("\x00" in value for value in values):
        raise ConfigurationError("command arguments may not contain NUL bytes")
    return values


class AsyncioCommandRunner:
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        safe_argv = validate_argv(argv)
        process = await asyncio.create_subprocess_exec(
            *safe_argv,
            cwd=cwd,
            env=None if env is None else dict(env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            process.terminate()
            await process.wait()
            raise
        return CommandResult(
            argv=safe_argv,
            returncode=process.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )
