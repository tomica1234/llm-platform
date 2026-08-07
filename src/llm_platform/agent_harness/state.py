import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from llm_platform.common.enums import AgentPhase

TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(slots=True)
class AgentTaskState:
    task_id: str
    repository: str
    user_request: str
    phase: AgentPhase = AgentPhase.DISCOVER
    plan: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    test_history: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    model: str = "auto"
    runtime: str | None = None
    deployment: str | None = None
    route_reasons: list[str] = field(default_factory=list)
    request_ids: list[str] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    repeated_failures: int = 0
    status: str = "active"


class TaskStateStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    def _path(self, task_id: str) -> Path:
        if not TASK_ID.fullmatch(task_id):
            raise ValueError("invalid task ID")
        return self.state_dir / f"{task_id}.json"

    def save(self, state: AgentTaskState) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(state.task_id)
        temporary = path.with_suffix(".tmp")
        payload = asdict(state)
        payload["phase"] = state.phase.value
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def load(self, task_id: str) -> AgentTaskState:
        payload = json.loads(self._path(task_id).read_text(encoding="utf-8"))
        payload["phase"] = AgentPhase(payload["phase"])
        return AgentTaskState(**payload)
