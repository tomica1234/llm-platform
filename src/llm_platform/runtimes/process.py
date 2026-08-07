import asyncio
import os
from typing import Protocol

from llm_platform.runtimes.base import LaunchSpec


class ProcessHandle(Protocol):
    @property
    def pid(self) -> int: ...

    def terminate(self) -> None: ...

    async def wait(self) -> int: ...


class ProcessSupervisor(Protocol):
    async def start(self, spec: LaunchSpec) -> ProcessHandle: ...

    async def stop(self, process_id: int) -> None: ...


class LocalProcessSupervisor:
    def __init__(self) -> None:
        self._processes: dict[int, asyncio.subprocess.Process] = {}

    async def start(self, spec: LaunchSpec) -> asyncio.subprocess.Process:
        environment = os.environ.copy()
        environment.update(spec.environment)
        process = await asyncio.create_subprocess_exec(
            *spec.argv,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[process.pid] = process
        return process

    async def stop(self, process_id: int) -> None:
        process = self._processes.pop(process_id, None)
        if process is None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=30)
        except TimeoutError:
            process.kill()
            await process.wait()
