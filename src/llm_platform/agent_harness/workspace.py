import asyncio
import hashlib
import hmac
import os
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


class WorkspaceViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class SafeWorkspace:
    READ_COMMANDS = frozenset({"rg", "find", "ls", "git", "sed", "head", "tail", "wc"})
    BUILD_COMMANDS = frozenset(
        {"python", "python3", "pytest", "ruff", "mypy", "make", "npm", "cargo", "go"}
    )
    FORBIDDEN_EXECUTABLES = frozenset(
        {"sudo", "su", "doas", "ssh", "scp", "curl", "wget", "dd", "mkfs", "mount", "umount"}
    )
    PYTHON_MODULES = frozenset({"pytest", "ruff", "mypy", "compileall", "py_compile", "build"})
    SENSITIVE_ENV_FRAGMENTS = frozenset(
        {"TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY", "CREDENTIAL"}
    )

    def __init__(self, root: Path, *, allow_in_place: bool = False) -> None:
        if not root.exists() or not root.is_dir():
            raise WorkspaceViolation("workspace root must be an existing directory")
        self.root = root.resolve()
        self.allow_in_place = allow_in_place

    def resolve(self, relative: str | Path, *, for_write: bool = False) -> Path:
        value = Path(relative)
        if value.is_absolute():
            raise WorkspaceViolation("absolute paths are not allowed")
        candidate = self.root / value
        parent = candidate.parent.resolve()
        if not parent.is_relative_to(self.root):
            raise WorkspaceViolation("path escapes the workspace")
        if candidate.is_symlink():
            raise WorkspaceViolation("symlink targets are not allowed")
        if candidate.exists() and not candidate.resolve().is_relative_to(self.root):
            raise WorkspaceViolation("resolved path escapes the workspace")
        if for_write and not self.allow_in_place:
            raise WorkspaceViolation("in-place editing was not explicitly enabled")
        return candidate

    def list_files(self) -> list[str]:
        return sorted(
            str(path.relative_to(self.root))
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.parts and not path.is_symlink()
        )

    def search(self, needle: str, *, suffixes: Iterable[str] = ()) -> list[tuple[str, int, str]]:
        suffix_set = set(suffixes)
        matches: list[tuple[str, int, str]] = []
        for relative in self.list_files():
            path = self.resolve(relative)
            if suffix_set and path.suffix not in suffix_set:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(lines, start=1):
                if needle in line:
                    matches.append((relative, line_number, line))
        return matches

    def read_text(self, relative: str | Path, *, max_bytes: int = 1_000_000) -> str:
        path = self.resolve(relative)
        if path.stat().st_size > max_bytes:
            raise WorkspaceViolation("file exceeds read size limit")
        return path.read_text(encoding="utf-8")

    def apply_replacement(
        self,
        relative: str | Path,
        *,
        expected_sha256: str,
        old: str,
        new: str,
    ) -> str:
        path = self.resolve(relative, for_write=True)
        current = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(current.encode()).hexdigest()
        if not hmac.compare_digest(digest, expected_sha256):
            raise WorkspaceViolation("file changed since it was read")
        if current.count(old) != 1:
            raise WorkspaceViolation("patch context must occur exactly once")
        updated = current.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        return hashlib.sha256(updated.encode()).hexdigest()

    def _validate_command(self, argv: Sequence[str]) -> tuple[str, ...]:
        if not argv:
            raise WorkspaceViolation("empty command")
        safe = tuple(str(part) for part in argv)
        executable = Path(safe[0]).name
        if executable in self.FORBIDDEN_EXECUTABLES:
            raise WorkspaceViolation(f"command is forbidden: {executable}")
        if executable not in self.READ_COMMANDS | self.BUILD_COMMANDS:
            raise WorkspaceViolation(f"command is not allowlisted: {executable}")
        if Path(safe[0]).is_absolute():
            allowed_path = (
                Path(sys.executable).resolve() if executable.startswith("python") else None
            )
            if allowed_path is None or Path(safe[0]).resolve() != allowed_path:
                raise WorkspaceViolation("absolute executable is not the harness interpreter")
        elif shutil.which(safe[0]) is None:
            raise WorkspaceViolation("command executable was not found")
        if (
            executable == "git"
            and len(safe) > 1
            and safe[1]
            in {
                "push",
                "reset",
                "clean",
                "checkout",
            }
        ):
            raise WorkspaceViolation(f"git subcommand requires explicit human handling: {safe[1]}")
        if executable == "git" and any(
            part == "-C" or part.startswith("--git-dir") or part.startswith("--work-tree")
            for part in safe[1:]
        ):
            raise WorkspaceViolation("git directory overrides are forbidden")
        if executable.startswith("python") and (
            len(safe) < 3 or safe[1] != "-m" or safe[2] not in self.PYTHON_MODULES
        ):
            raise WorkspaceViolation("Python may only run an approved module")
        for part in safe[1:]:
            if part.startswith("-") or "://" in part:
                continue
            possible_path = Path(part)
            if possible_path.is_absolute() and not possible_path.resolve().is_relative_to(
                self.root
            ):
                raise WorkspaceViolation("command path escapes the workspace")
            if ".." in possible_path.parts:
                resolved = (self.root / possible_path).resolve()
                if not resolved.is_relative_to(self.root):
                    raise WorkspaceViolation("command path escapes the workspace")
        if any("\x00" in part or "\n" in part for part in safe):
            raise WorkspaceViolation("invalid command argument")
        return safe

    async def run(self, argv: Sequence[str], *, timeout_seconds: float = 600) -> ToolResult:
        safe = self._validate_command(argv)
        environment = os.environ.copy()
        # Test instrumentation must not be injected into user tool subprocesses.
        for key in tuple(environment):
            if key.startswith("COV_CORE_") or key == "COVERAGE_PROCESS_START":
                environment.pop(key)
            elif any(fragment in key.upper() for fragment in self.SENSITIVE_ENV_FRAGMENTS):
                environment.pop(key)
        process = await asyncio.create_subprocess_exec(
            *safe,
            cwd=self.root,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            process.terminate()
            await process.wait()
            raise
        return ToolResult(
            safe,
            process.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
