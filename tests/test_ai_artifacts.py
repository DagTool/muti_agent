from types import SimpleNamespace

import pytest

from packages.agent_runtime.openai_adapter import GeneratedFile, GeneratedProject, ModelResult
from workers import ai_worker


def test_developer_attempts_publish_only_the_selected_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ai_worker,
        "get_settings",
        lambda: SimpleNamespace(artifact_root=str(tmp_path), openai_model="test-model"),
    )
    summaries = iter(("first attempt", "second attempt"))

    def fake_generate(*_args):
        summary = next(summaries)
        return (
            GeneratedProject(
                summary=summary,
                files=[
                    GeneratedFile(path="README.md", content=f"# {summary}"),
                    GeneratedFile(
                        path="tests/test_example.py", content="def test_example(): pass\n"
                    ),
                ],
            ),
            ModelResult(text=summary, input_tokens=1, output_tokens=1),
        )

    monkeypatch.setattr(ai_worker, "generate_project", fake_generate)
    ai_worker._perform("developer", "project", "run", "requirement", "prd", "design", 1)
    ai_worker._perform("developer", "project", "run", "requirement", "prd", "design", 2)

    root = tmp_path / "project" / "run"
    first = tmp_path / "project" / ".run.attempt-1"
    second = tmp_path / "project" / ".run.attempt-2"
    assert not root.exists()
    assert (first / "README.md").read_text() == "# first attempt"
    assert (second / "README.md").read_text() == "# second attempt"

    ai_worker._publish_project("project", "run", 2)
    assert (root / "README.md").read_text() == "# second attempt"
    assert not second.exists()
    with pytest.raises(RuntimeError, match="cannot be published"):
        ai_worker._publish_project("project", "run", 1)
    assert (root / "README.md").read_text() == "# second attempt"
