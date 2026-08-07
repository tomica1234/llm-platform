import os
from pathlib import Path

import pytest

from llm_platform.agent_harness.workspace import SafeWorkspace, WorkspaceViolation

pytestmark = pytest.mark.security


def test_workspace_escape_and_absolute_path_rejected(tmp_path: Path) -> None:
    workspace = SafeWorkspace(tmp_path, allow_in_place=True)
    with pytest.raises(WorkspaceViolation, match="escapes"):
        workspace.resolve("../outside")
    with pytest.raises(WorkspaceViolation, match="absolute"):
        workspace.resolve("/etc/passwd")


def test_symlink_attack_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlinks unavailable")
    workspace = SafeWorkspace(tmp_path, allow_in_place=True)
    with pytest.raises(WorkspaceViolation, match="symlink"):
        workspace.read_text("link")


@pytest.mark.asyncio
async def test_sudo_push_and_network_commands_rejected(tmp_path: Path) -> None:
    workspace = SafeWorkspace(tmp_path)
    for argv in (["sudo", "id"], ["git", "push"], ["curl", "https://example.com"]):
        with pytest.raises(WorkspaceViolation):
            await workspace.run(argv)


@pytest.mark.asyncio
async def test_allowlisted_command_cannot_escape_by_argument(tmp_path: Path) -> None:
    workspace = SafeWorkspace(tmp_path)
    for argv in (
        ["sed", "-n", "1p", "/etc/passwd"],
        ["git", "-C", "/tmp", "status"],
        ["python3", "-c", "print('unsafe')"],
        ["find", "..", "-type", "f"],
    ):
        with pytest.raises(WorkspaceViolation):
            await workspace.run(argv)


def test_write_requires_explicit_in_place(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_text("old", encoding="utf-8")
    workspace = SafeWorkspace(tmp_path)
    with pytest.raises(WorkspaceViolation, match="not explicitly enabled"):
        workspace.apply_replacement("file", expected_sha256="unused", old="old", new="new")
