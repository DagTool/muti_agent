"""Validate a generated file manifest before it reaches disk."""

import re
import shutil
from pathlib import Path, PurePosixPath
from uuid import uuid4

from packages.agent_runtime.openai_adapter import GeneratedProject

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_ALLOWED_SUFFIXES = {".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml"}
_DENIED_NAMES = {".env", ".git", ".npmrc", "pyproject.local.toml"}
_WINDOWS_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_relative_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or "\\" in raw
        or len(path.parts) > 5
        or not path.parts
        or any(not _SAFE_SEGMENT.fullmatch(part) for part in path.parts)
        or any(part.lower() in _DENIED_NAMES or part.startswith(".") for part in path.parts)
        or any(part.split(".", 1)[0].lower() in _WINDOWS_DEVICES for part in path.parts)
        or path.suffix.lower() not in _ALLOWED_SUFFIXES
    ):
        raise ValueError(f"Unsafe generated path: {raw!r}")
    return path


def write_project_files(root: Path, project: GeneratedProject) -> list[Path]:
    """Write only ordinary text files below a fresh, dedicated run directory."""
    if root.exists():
        raise ValueError("Run workspace already exists")
    if len(project.files) > 30:
        raise ValueError("Generated project exceeds file limit")
    validated: list[tuple[PurePosixPath, str]] = []
    seen: set[str] = set()
    total_bytes = 0
    for item in project.files:
        path = safe_relative_path(item.path)
        key = item.path.lower()
        if key in seen:
            raise ValueError("Duplicate generated path")
        seen.add(key)
        size = len(item.content.encode("utf-8"))
        if size > 100_000:
            raise ValueError("Generated file exceeds size limit")
        total_bytes += size
        validated.append((path, item.content))
    if total_bytes > 500_000:
        raise ValueError("Generated project exceeds size limit")
    if not any(str(path).lower() == "readme.md" for path, _ in validated):
        raise ValueError("Generated project must include README.md")
    if not any(
        path.parts[0] == "tests" and path.name.startswith("test_") and path.suffix == ".py"
        for path, _ in validated
    ):
        raise ValueError("Generated project must include unittest tests")
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = root.parent / f".{root.name}.stage-{uuid4().hex}"
    stage.mkdir()
    try:
        for path, content in validated:
            target = stage.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if root.exists():
            raise ValueError("Run workspace already exists")
        stage.rename(root)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return [root.joinpath(*path.parts) for path, _ in validated]
