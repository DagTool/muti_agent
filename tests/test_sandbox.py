from pathlib import Path
from subprocess import CompletedProcess

import pytest

from packages.execution import sandbox_manager


def test_sandbox_restricts_execution(monkeypatch, tmp_path):
    calls = []
    (tmp_path / ".env").write_text("SECRET=hidden")
    (tmp_path / "main.py").write_text("print('ok')")

    def fake_run(args, **kwargs):
        mount = args[args.index("--mount") + 1]
        staged = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
        assert (staged / "main.py").exists()
        assert not (staged / ".env").exists()
        calls.append((args, kwargs))
        return CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(sandbox_manager.subprocess, "run", fake_run)
    result = sandbox_manager.run_in_sandbox(Path(tmp_path), ["python", "-m", "pytest"])
    assert result.exit_code == 0
    command = calls[0][0]
    assert ["--network", "none"] == command[
        command.index("--network") : command.index("--network") + 2
    ]
    assert "--read-only" in command
    assert "--cap-drop" in command
    assert "--user" in command
    assert "--rm" in command


@pytest.mark.parametrize(
    "command", [["sh", "-c", "echo bad"], ["python", "-m", "pytest", "../secrets"]]
)
def test_sandbox_rejects_unapproved_commands(tmp_path, command):
    with pytest.raises(sandbox_manager.SandboxError):
        sandbox_manager.run_in_sandbox(tmp_path, command)
