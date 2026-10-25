from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.app import main
from apps.api.app.db.base import (
    ApiToken,
    Approval,
    Base,
    OutboxEvent,
    ProcessedEvent,
    Project,
    Requirement,
    Task,
    WorkflowRun,
    Workspace,
    utcnow,
)
from apps.api.app.db.session import get_db
from packages.communication.contracts import TASK_COMMANDS, TASK_RESULTS, EventEnvelope
from packages.orchestration.graph import build_graph
from workers import agent_worker, ai_worker, dispatcher_worker, outbox_worker, recovery_worker


@pytest.fixture
def environment(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        db.add_all([Workspace(id="ws", name="Test"), Workspace(id="other", name="Other")])

    def db_override():
        with sessions() as db:
            yield db

    class Settings:
        api_key = "test-secret"
        workspace_id = "ws"
        agent_mode = "mock"

    main.app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main, "get_settings", lambda: Settings())
    monkeypatch.setattr(agent_worker, "new_session", sessions)
    monkeypatch.setattr(ai_worker, "new_session", sessions)
    monkeypatch.setattr(outbox_worker, "new_session", sessions)
    monkeypatch.setattr(recovery_worker, "new_session", sessions)
    yield TestClient(main.app), sessions
    main.app.dependency_overrides.clear()
    engine.dispose()


def test_api_outbox_worker_and_duplicate(environment):
    client, sessions = environment
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "project-1"}
    response = client.post("/api/v1/projects", json={"name": "Demo"}, headers=headers)
    assert response.status_code == 200, response.text
    project_id = response.json()["id"]
    activity = client.get(f"/api/v1/projects/{project_id}/activity", headers=headers)
    assert activity.status_code == 200
    assert activity.json()[0]["action"] == "project.created"
    assert (
        client.post("/api/v1/projects", json={"name": "Demo"}, headers=headers).json()["id"]
        == project_id
    )
    assert (
        client.post("/api/v1/projects", json={"name": "Different"}, headers=headers).status_code
        == 409
    )

    headers["Idempotency-Key"] = "task-1"
    response = client.post(
        f"/api/v1/projects/{project_id}/tasks", json={"title": "Build API"}, headers=headers
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["id"]
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/tasks", json={"title": "Build API"}, headers=headers
        ).json()["id"]
        == task_id
    )

    with sessions() as db:
        command = db.scalar(select(OutboxEvent).where(OutboxEvent.topic == TASK_COMMANDS))
        assert command is not None
        event = EventEnvelope.model_validate(command.payload)
        assert str(event.task_id) == task_id
        assert str(event.correlation_id) == response.json()["correlation_id"]

    assert agent_worker.process_event(event) is True
    assert agent_worker.process_event(event) is False
    with sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == "completed"
        assert task.result == "Mock developer completed: Build API"
        assert len(db.scalars(select(ProcessedEvent)).all()) == 1
        assert (
            len(db.scalars(select(OutboxEvent).where(OutboxEvent.topic == TASK_RESULTS)).all()) == 1
        )


def test_auth_and_workspace_scope(environment):
    client, sessions = environment
    assert client.get("/api/v1/projects").status_code == 401
    with sessions.begin() as db:
        db.add(Project(workspace_id="other", name="Hidden", request_key="hidden"))
    response = client.get("/api/v1/projects", headers={"X-API-Key": "test-secret"})
    assert response.status_code == 200
    assert response.json() == []
    with sessions() as db:
        hidden_id = db.scalar(select(Project.id).where(Project.workspace_id == "other"))
    assert (
        client.get(
            f"/api/v1/projects/{hidden_id}/activity", headers={"X-API-Key": "test-secret"}
        ).status_code
        == 404
    )


def test_member_tokens_enforce_roles_and_can_be_revoked(environment):
    client, sessions = environment
    owner = {"X-API-Key": "test-secret", "Idempotency-Key": "rbac-project"}
    project = client.post("/api/v1/projects", json={"name": "RBAC"}, headers=owner).json()
    viewer_response = client.post(
        "/api/v1/members",
        json={"email": "viewer@example.test", "name": "Viewer", "role": "viewer"},
        headers=owner,
    )
    assert viewer_response.status_code == 200, viewer_response.text
    viewer = viewer_response.json()
    viewer_headers = {"X-API-Key": viewer["api_token"]}
    assert client.get("/api/v1/auth/me", headers=viewer_headers).json()["role"] == "viewer"
    assert client.get("/api/v1/projects", headers=viewer_headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"content": "A sufficiently long requirement"},
            headers=viewer_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/budget",
            json={"token_budget": 600000},
            headers=viewer_headers,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/members", headers=viewer_headers).status_code == 403
    with sessions() as db:
        stored = db.scalar(select(ApiToken).where(ApiToken.id == viewer["token_id"]))
        assert viewer["api_token"] != stored.token_hash

    member = client.post(
        "/api/v1/members",
        json={"email": "member@example.test", "name": "Member", "role": "member"},
        headers=owner,
    ).json()
    member_headers = {"X-API-Key": member["api_token"]}
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"content": "A sufficiently long requirement"},
            headers=member_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/budget",
            json={"token_budget": 600000},
            headers=member_headers,
        ).status_code
        == 403
    )
    changed = client.post(
        f"/api/v1/members/{viewer['id']}/role",
        json={"role": "member"},
        headers=owner,
    )
    assert changed.status_code == 200
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"content": "Another sufficiently long requirement"},
            headers=viewer_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/tokens/{viewer['token_id']}/revoke", headers=owner).status_code == 200
    )
    assert client.get("/api/v1/projects", headers=viewer_headers).status_code == 401


def test_contract_rejects_unknown_version():
    data = {
        "event_type": "task.execute.requested",
        "schema_version": 2,
        "correlation_id": str(uuid4()),
        "workspace_id": "ws",
        "project_id": str(uuid4()),
        "task_id": str(uuid4()),
        "execution_id": str(uuid4()),
        "idempotency_key": "key",
        "sender": "api",
        "recipient_role": "developer",
        "attempt": 1,
        "payload": {},
    }
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(data)


def test_outbox_and_dispatcher_route_once(environment, monkeypatch):
    client, _sessions = environment
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "project-2"}
    project = client.post("/api/v1/projects", json={"name": "Demo"}, headers=headers).json()
    headers["Idempotency-Key"] = "task-2"
    client.post(f"/api/v1/projects/{project['id']}/tasks", json={"title": "Build"}, headers=headers)
    sent = []
    monkeypatch.setattr(
        outbox_worker,
        "publish_sync",
        lambda _, topic, key, payload: sent.append((topic, key, payload)),
    )
    assert outbox_worker.publish_batch(object()) == 1
    assert outbox_worker.publish_batch(object()) == 0
    assert sent[0][0] == TASK_COMMANDS

    routed = []
    monkeypatch.setattr(
        dispatcher_worker,
        "publish_sync",
        lambda _, topic, key, payload: routed.append((topic, key, payload)),
    )
    dispatcher_worker.dispatch_payload(
        EventEnvelope.model_validate(sent[0][2]).model_dump_json().encode(), object()
    )
    assert routed[0][0] == "agentforge.tasks.developer.v1"


def test_mock_graph_persists_completed_state():
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "test-run"}}
    result = graph.invoke({"requirement": "Create a task API"}, config)
    assert result["review"] == "passed"
    assert graph.get_state(config).values == result


def test_run_scope_qa_handover_flow(environment):
    client, sessions = environment
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "project-run"}
    project = client.post("/api/v1/projects", json={"name": "Run demo"}, headers=headers).json()
    project_id = project["id"]
    requirement = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"content": "Create a small REST API for tasks."},
        headers=headers,
    )
    assert requirement.status_code == 200, requirement.text
    headers["Idempotency-Key"] = "run-1"
    run = client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers)
    assert run.status_code == 200, run.text
    run_id = run.json()["id"]
    assert run.json()["status"] == "awaiting_scope_approval"
    assert (
        client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers).json()["id"]
        == run_id
    )

    approvals = client.get("/api/v1/approvals", headers=headers).json()
    scope = next(item for item in approvals if item["run_id"] == run_id)
    response = client.post(
        f"/api/v1/approvals/{scope['id']}/decision",
        json={"decision": "approve"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert (
        client.post(
            f"/api/v1/approvals/{scope['id']}/decision",
            json={"decision": "approve"},
            headers=headers,
        ).status_code
        == 200
    )

    with sessions() as db:
        developer = db.scalar(select(Task).where(Task.run_id == run_id, Task.role == "developer"))
        command = db.scalar(select(OutboxEvent).where(OutboxEvent.event_key == developer.id))
        developer_event = EventEnvelope.model_validate(command.payload)
    assert agent_worker.process_event(developer_event) is True

    with sessions() as db:
        qa = db.scalar(select(Task).where(Task.run_id == run_id, Task.role == "qa"))
        command = db.scalar(select(OutboxEvent).where(OutboxEvent.event_key == qa.id))
        qa_event = EventEnvelope.model_validate(command.payload)
    assert agent_worker.process_event(qa_event, role="qa") is True

    assert (
        client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"]
        == "awaiting_handover_approval"
    )
    with sessions() as db:
        handover = db.scalar(
            select(Approval).where(Approval.run_id == run_id, Approval.action == "handover")
        )
        handover_id = handover.id
    assert (
        client.post(
            f"/api/v1/approvals/{handover_id}/decision",
            json={"decision": "approve"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "completed"
    artifacts = client.get(f"/api/v1/projects/{project_id}/artifacts", headers=headers).json()
    assert {item["kind"] for item in artifacts} == {
        "mock_prd_draft",
        "mock_implementation_note",
        "mock_qa_report",
    }


@pytest.mark.parametrize("action", ["cancel", "reject"])
def test_run_stops_before_dispatch(environment, action):
    client, sessions = environment
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": f"project-{action}"}
    project_id = client.post("/api/v1/projects", json={"name": action}, headers=headers).json()[
        "id"
    ]
    client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"content": "Create a test API and tests."},
        headers=headers,
    )
    headers["Idempotency-Key"] = f"run-{action}"
    run_id = client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers).json()[
        "id"
    ]
    scope = next(
        item
        for item in client.get("/api/v1/approvals", headers=headers).json()
        if item["run_id"] == run_id
    )
    if action == "cancel":
        response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)
        assert response.json()["status"] == "cancelled"
        assert (
            client.post(
                f"/api/v1/approvals/{scope['id']}/decision",
                json={"decision": "approve"},
                headers=headers,
            ).status_code
            == 409
        )
    else:
        response = client.post(
            f"/api/v1/approvals/{scope['id']}/decision",
            json={"decision": "reject"},
            headers=headers,
        )
        assert response.json()["status"] == "rejected"
        assert client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "blocked"
    with sessions() as db:
        assert db.scalars(select(Task).where(Task.run_id == run_id)).all() == []


def test_other_workspace_approval_is_hidden(environment):
    client, sessions = environment
    with sessions.begin() as db:
        project = Project(workspace_id="other", name="Private", request_key="private")
        db.add(project)
        db.flush()
        requirement = Requirement(project_id=project.id, version=1, content="Private requirement")
        db.add(requirement)
        db.flush()
        run = WorkflowRun(
            project_id=project.id, requirement_id=requirement.id, request_key="private"
        )
        db.add(run)
        db.flush()
        approval = Approval(run_id=run.id, action="scope")
        db.add(approval)
        db.flush()
        approval_id = approval.id
    headers = {"X-API-Key": "test-secret"}
    assert client.get("/api/v1/approvals", headers=headers).json() == []
    assert (
        client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve"},
            headers=headers,
        ).status_code
        == 404
    )


def test_openai_workflow_with_stubbed_agent_outputs(environment, monkeypatch, tmp_path):
    client, sessions = environment

    class OpenAISettings:
        api_key = "test-secret"
        workspace_id = "ws"
        agent_mode = "openai"

    OpenAISettings.artifact_root = str(tmp_path / "generated")

    monkeypatch.setattr(main, "get_settings", lambda: OpenAISettings())
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "openai-project"}
    project_id = client.post("/api/v1/projects", json={"name": "AI demo"}, headers=headers).json()[
        "id"
    ]
    client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"content": "Build a simple calculator API with tests."},
        headers=headers,
    )
    headers["Idempotency-Key"] = "openai-run"
    run = client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers).json()
    assert run["mode"] == "openai"
    assert run["status"] == "running"
    run_id = run["id"]

    def fake_perform(role, *_args):
        return ai_worker.WorkOutput(
            kind={
                "pm": "prd",
                "architect": "architecture",
                "developer": "generated_project",
                "qa": "qa_report",
            }[role],
            content=f"{role} output",
            summary=f"{role} done",
            input_tokens=600 if role != "qa" else 0,
            output_tokens=400 if role != "qa" else 0,
        )

    monkeypatch.setattr(ai_worker, "_perform", fake_perform)

    def perform(role):
        with sessions() as db:
            task = db.scalar(select(Task).where(Task.run_id == run_id, Task.role == role))
            event = EventEnvelope.model_validate(
                db.scalar(select(OutboxEvent).where(OutboxEvent.event_key == task.id)).payload
            )
        assert ai_worker.process_ai_event(event, role) is True
        assert ai_worker.process_ai_event(event, role) is False

    perform("pm")
    assert (
        client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"]
        == "awaiting_scope_approval"
    )
    scope = next(
        item
        for item in client.get("/api/v1/approvals", headers=headers).json()
        if item["run_id"] == run_id
    )
    client.post(
        f"/api/v1/approvals/{scope['id']}/decision",
        json={"decision": "approve"},
        headers=headers,
    )
    perform("architect")
    perform("developer")
    perform("qa")
    assert (
        client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"]
        == "awaiting_handover_approval"
    )
    handover = next(
        item
        for item in client.get("/api/v1/approvals", headers=headers).json()
        if item["run_id"] == run_id
    )
    client.post(
        f"/api/v1/approvals/{handover['id']}/decision",
        json={"decision": "approve"},
        headers=headers,
    )
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "completed"
    root = tmp_path / "generated" / project_id / run_id
    root.mkdir(parents=True)
    (root / "README.md").write_text("# Generated")
    assert client.get(f"/api/v1/runs/{run_id}/files", headers=headers).json() == ["README.md"]
    assert (
        client.get(
            f"/api/v1/runs/{run_id}/file",
            params={"path": "README.md"},
            headers=headers,
        ).json()["content"]
        == "# Generated"
    )
    assert (
        client.get(
            f"/api/v1/runs/{run_id}/file",
            params={"path": "../.env"},
            headers=headers,
        ).status_code
        == 400
    )
    project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    assert project["tokens_used"] == 3000
    assert (
        len(client.get(f"/api/v1/projects/{project_id}/model-usage", headers=headers).json()) == 3
    )
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/budget",
            json={"token_budget": 1000},
            headers=headers,
        ).status_code
        == 409
    )


def test_openai_failed_task_can_resume_and_stale_task_is_recovered(environment, monkeypatch):
    client, sessions = environment

    class OpenAISettings:
        api_key = "test-secret"
        workspace_id = "ws"
        agent_mode = "openai"

    monkeypatch.setattr(main, "get_settings", lambda: OpenAISettings())
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "retry-project"}
    project_id = client.post("/api/v1/projects", json={"name": "Retry"}, headers=headers).json()[
        "id"
    ]
    client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"content": "Build a calculator with tests."},
        headers=headers,
    )
    headers["Idempotency-Key"] = "retry-run"
    run_id = client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers).json()[
        "id"
    ]
    with sessions() as db:
        task = db.scalar(select(Task).where(Task.run_id == run_id))
        task_id = task.id
        event = EventEnvelope.model_validate(
            db.scalar(select(OutboxEvent).where(OutboxEvent.event_key == task_id)).payload
        )

    def fail(*_args):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ai_worker, "_perform", fail)
    assert ai_worker.process_ai_event(event, "pm") is True
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "blocked"
    response = client.post(f"/api/v1/runs/{run_id}/resume", headers=headers)
    assert response.status_code == 200, response.text
    with sessions.begin() as db:
        task = db.get(Task, task_id)
        assert task.attempt == 2 and task.status == "ready"
        task.status = "running"
        task.updated_at = utcnow() - timedelta(minutes=20)
    assert recovery_worker.recover_stale_tasks(max_age_seconds=600) == 1
    with sessions() as db:
        task = db.get(Task, task_id)
        assert task.attempt == 3 and task.status == "ready"
        events = db.scalars(select(OutboxEvent).where(OutboxEvent.event_key == task_id)).all()
        assert [EventEnvelope.model_validate(item.payload).attempt for item in events] == [1, 2, 3]
