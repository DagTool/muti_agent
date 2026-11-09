from packages.execution.sandbox_manager import SandboxResult
from scripts import smoke_ai_execution
from workers import ai_worker


def test_ai_smoke_publishes_before_qa(monkeypatch, capsys):
    monkeypatch.setattr(
        ai_worker,
        "run_in_sandbox",
        lambda *_args: SandboxResult(exit_code=0, stdout="", stderr="Ran 1 test"),
    )
    smoke_ai_execution.main()
    assert "Generated project and sandbox QA passed" in capsys.readouterr().out
