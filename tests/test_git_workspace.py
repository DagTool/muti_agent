import shutil
import subprocess
from pathlib import Path

from packages.execution.git_workspace import commit_project


def test_generated_project_gets_reviewable_local_commit(tmp_path):
    source = Path(__file__).parent / "fixtures" / "sandbox_project"
    root = tmp_path / "generated"
    shutil.copytree(source, root)
    first = commit_project(root, "Initial generated code")
    assert len(first) == 40
    assert commit_project(root, "No changes") == first
    (root / "README.md").write_text("# Reviewed")
    second = commit_project(root, "QA reviewed code")
    assert second != first
    result = subprocess.run(
        ["git", "-C", str(root), "show", "--format=%s", "--no-patch", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "QA reviewed code"
