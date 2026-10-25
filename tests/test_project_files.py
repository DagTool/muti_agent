import pytest

from packages.agent_runtime.openai_adapter import GeneratedProject
from packages.execution.project_files import write_project_files


def manifest(path="app.py"):
    return GeneratedProject.model_validate(
        {
            "summary": "Demo",
            "files": [
                {"path": "README.md", "content": "# Demo"},
                {"path": path, "content": "print('hello')"},
                {"path": "tests/test_app.py", "content": "import unittest"},
            ],
        }
    )


def test_generated_project_is_written_to_new_root(tmp_path):
    root = tmp_path / "run"
    written = write_project_files(root, manifest())
    assert len(written) == 3
    assert (root / "app.py").read_text() == "print('hello')"
    with pytest.raises(ValueError, match="already exists"):
        write_project_files(root, manifest())


@pytest.mark.parametrize("path", ["../escape.py", "/abs.py", "CON.py", ".env", "foo\\bar.py"])
def test_generated_project_rejects_unsafe_paths(tmp_path, path):
    with pytest.raises(ValueError):
        write_project_files(tmp_path / "run", manifest(path))
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz123456",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "github_pat_abcdefghijklmnopqrstuvwxyz123456",
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_generated_project_rejects_known_secret_formats(tmp_path, secret):
    project = manifest()
    project.files[1].content = f"credential = {secret}"
    with pytest.raises(ValueError, match="possible secret"):
        write_project_files(tmp_path / "run", project)
    assert not (tmp_path / "run").exists()
