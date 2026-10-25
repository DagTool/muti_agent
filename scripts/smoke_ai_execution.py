"""Test the generated-code path with a fixture and real Docker sandbox."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from packages.agent_runtime.openai_adapter import GeneratedProject, ModelResult
from workers import ai_worker


def main():
    source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sandbox_project"
    files = [
        {"path": path.relative_to(source).as_posix(), "content": path.read_text(encoding="utf-8")}
        for path in source.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    project = GeneratedProject.model_validate({"summary": "Fixture calculator", "files": files})
    with tempfile.TemporaryDirectory(prefix="agentforge-ai-smoke-") as temp:
        ai_worker.get_settings = lambda: SimpleNamespace(artifact_root=temp, openai_model="fixture")
        ai_worker.generate_project = lambda _prompt, _model: (
            project,
            ModelResult("Fixture calculator", 0, 0),
        )
        project_id, run_id = str(uuid4()), str(uuid4())
        developer = ai_worker._perform("developer", project_id, run_id, "calculator", "", "")
        qa = ai_worker._perform("qa", project_id, run_id, "calculator", "", "")
        if not qa.passed:
            raise RuntimeError(qa.content)
        print(f"Generated project and sandbox QA passed: {developer.summary}")


if __name__ == "__main__":
    main()
