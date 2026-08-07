from dataclasses import dataclass
from pathlib import Path

from llm_platform.agent_harness.state import AgentTaskState
from llm_platform.common.enums import AgentPhase


@dataclass(frozen=True, slots=True)
class TaskFeatures:
    task_type: str
    phase: AgentPhase
    files_changed: int
    languages: tuple[str, ...]
    repository_files: int
    context_tokens: int
    failure_count: int
    repeated_failure_count: int
    high_risk: bool

    def headers(self) -> dict[str, str]:
        return {
            "X-Agent-Phase": self.phase.value,
            "X-Agent-Risk": "high" if self.high_risk else "normal",
            "X-Agent-Context-Tokens": str(self.context_tokens),
            "X-Agent-Failure-Count": str(self.failure_count),
        }


RISK_TERMS = frozenset(
    {"auth", "permission", "payment", "delete", "migration", "secret", "security"}
)
LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
}


def extract_features(root: Path, state: AgentTaskState, changed_files: list[str]) -> TaskFeatures:
    files = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]
    languages = sorted({LANGUAGES[path.suffix] for path in files if path.suffix in LANGUAGES})
    request = state.user_request.lower()
    high_risk = any(term in request for term in RISK_TERMS)
    task_type = "review" if "review" in request else "implementation"
    context_tokens = min(sum(path.stat().st_size for path in files) // 4, 2_000_000)
    return TaskFeatures(
        task_type,
        state.phase,
        len(changed_files),
        tuple(languages),
        len(files),
        context_tokens,
        len([item for item in state.test_history if item.get("returncode") != 0]),
        state.repeated_failures,
        high_risk,
    )
