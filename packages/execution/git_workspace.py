"""Create reviewable local Git commits for generated projects."""

import os
import subprocess
import tempfile
from pathlib import Path


class GitWorkspaceError(RuntimeError):
    pass


def _git(root: Path, hooks: Path, *arguments: str) -> str:
    command = [
        "git",
        "-C",
        str(root),
        "-c",
        f"core.hooksPath={hooks}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "user.name=AgentForge AI",
        "-c",
        "user.email=agentforge@localhost",
        *arguments,
    ]
    clean_env = os.environ.copy()
    clean_env["GIT_CONFIG_NOSYSTEM"] = "1"
    clean_env["GIT_CONFIG_GLOBAL"] = str(hooks.parent / "empty.gitconfig")
    clean_env["GIT_TEMPLATE_DIR"] = str(hooks.parent / "template")
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=clean_env,
    )
    if completed.returncode:
        raise GitWorkspaceError(f"Git {arguments[0]} failed (exit {completed.returncode})")
    return completed.stdout.strip()


def commit_project(root: Path, message: str) -> str:
    """Commit ordinary generated files; never run repository hooks."""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise GitWorkspaceError("Generated workspace is not a directory")
    with tempfile.TemporaryDirectory(prefix="agentforge-empty-git-") as temp:
        hooks = Path(temp) / "hooks"
        hooks.mkdir()
        template = Path(temp) / "template"
        template.mkdir()
        (Path(temp) / "empty.gitconfig").touch()
        if not (root / ".git").exists():
            _git(root, hooks, "init", "--initial-branch=main", f"--template={template}")
        _git(root, hooks, "add", "--all")
        if _git(root, hooks, "status", "--porcelain"):
            _git(root, hooks, "commit", "-m", message)
        return _git(root, hooks, "rev-parse", "HEAD")
