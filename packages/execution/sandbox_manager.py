"""Local isolated test runner. Public multi-tenant use needs a stronger boundary."""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ALLOWED_COMMANDS = {
    ("python", "-m", "pytest"),
    ("python", "-m", "compileall"),
    ("python", "-m", "unittest", "discover"),
    ("npm", "test"),
    ("npm", "run", "build"),
}
IGNORED_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    ".agentforge",
    "__pycache__",
    ".npmrc",
    ".pypirc",
    ".netrc",
}
ALLOWED_IMAGES = {"python:3.13-slim", "node:24-bookworm-slim"}


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str


class SandboxError(RuntimeError):
    pass


def _validate_command(command: list[str]) -> None:
    if not command or not any(
        tuple(command[: len(prefix)]) == prefix for prefix in ALLOWED_COMMANDS
    ):
        raise SandboxError("Command is not in the sandbox allowlist")
    if any(
        part.startswith("-") and ("=" in part or "/" in part or "\\" in part) for part in command
    ):
        raise SandboxError("Command arguments contain unsupported flags")
    if any(part in {"..", ".env"} or ".." in Path(part).parts for part in command):
        raise SandboxError("Command arguments cannot traverse directories")


def run_in_sandbox(
    worktree: Path,
    command: list[str],
    *,
    image: str = "python:3.13-slim",
    timeout_seconds: int = 120,
) -> SandboxResult:
    """Run one allowlisted command in a locked-down ephemeral Docker container."""
    _validate_command(command)
    root = worktree.resolve(strict=True)
    if not root.is_dir():
        raise SandboxError("Worktree must be a directory")
    if timeout_seconds < 1 or timeout_seconds > 600:
        raise SandboxError("Timeout must be between 1 and 600 seconds")
    if image not in ALLOWED_IMAGES:
        raise SandboxError("Image is not in the sandbox allowlist")

    with tempfile.TemporaryDirectory(prefix="agentforge-sandbox-") as temp_dir:
        staged = Path(temp_dir) / "source"
        staged.mkdir()
        copied_bytes = 0
        copied_files = 0
        for current_root, dirs, files in os.walk(root, followlinks=False):
            current = Path(current_root)
            dirs[:] = [
                name
                for name in dirs
                if name not in IGNORED_NAMES
                and not name.startswith(".env")
                and not (current / name).is_symlink()
            ]
            target = staged / current.relative_to(root)
            target.mkdir(parents=True, exist_ok=True)
            for name in files:
                source = current / name
                if (
                    name.startswith(".env")
                    or name in IGNORED_NAMES
                    or name.endswith((".pem", ".key"))
                    or source.is_symlink()
                ):
                    continue
                copied_files += 1
                copied_bytes += source.stat().st_size
                if copied_files > 1000 or copied_bytes > 20_000_000:
                    raise SandboxError("Workspace exceeds sandbox staging limit")
                shutil.copy2(source, target / name)
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--user",
            "10001:10001",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--tmpfs",
            "/workspace:rw,exec,nosuid,size=256m,mode=1777",
            "--mount",
            f"type=bind,source={staged},target=/source,readonly",
            "--workdir",
            "/workspace",
            image,
            "sh",
            "-eu",
            "-c",
            'cp -R /source/. /workspace/; exec "$@"',
            "sh",
            *command,
        ]
        try:
            completed = subprocess.run(
                docker_command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxError("Sandbox command timed out") from exc
    return SandboxResult(
        exit_code=completed.returncode,
        stdout=completed.stdout[:100000],
        stderr=completed.stderr[:100000],
    )
