import asyncio
from datetime import timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.app import main
from apps.api.app.db.base import (
    ApiToken,
    Approval,
    Artifact,
    AuditLog,
    Base,
    ModelUsage,
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
from packages.communication.contracts import (
    TASK_COMMANDS,
    TASK_RESULTS,
    TASKS_AI_DEVELOPER,
    EventEnvelope,
)
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
    monkeypatch.setattr(main, "new_session", sessions)
    monkeypatch.setattr(agent_worker, "new_session", sessions)
    monkeypatch.setattr(ai_worker, "new_session", sessions)
    monkeypatch.setattr(outbox_worker, "new_session", sessions)
    monkeypatch.setattr(recovery_worker, "new_session", sessions)
    yield TestClient(main.app), sessions
    main.app.dependency_overrides.clear()
    engine.dispose()


def test_project_event_stream_is_scoped_and_requires_auth(environment):
    client, sessions = environment
    with sessions.begin() as db:
        own = Project(workspace_id="ws", name="Own", description="", request_key="own")
        other = Project(workspace_id="other", name="Other", description="", request_key="other")
        db.add_all([own, other])
        db.flush()
        db.add_all(
            [
                AuditLog(
                    workspace_id="ws",
                    project_id=own.id,
                    action="test.own",
                    resource_id=own.id,
                    correlation_id=str(uuid4()),
                ),
                AuditLog(
                    workspace_id="other",
                    project_id=other.id,
                    action="test.other",
                    resource_id=other.id,
                    correlation_id=str(uuid4()),
                ),
            ]
        )
        own_id, other_id = own.id, other.id
    assert main.activity_revision(own_id, "ws") == 1
    assert main.activity_revision(own_id, "other") == 0
    assert client.get(f"/api/v1/projects/{own_id}/events").status_code == 401
    assert (
        client.get(
            f"/api/v1/projects/{other_id}/events",
            headers={"X-API-Key": "test-secret"},
        ).status_code
        == 404
    )


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


def test_foreign_workspace_resources_are_hidden_across_api(environment):
    client, sessions = environment
    with sessions.begin() as db:
        project = Project(workspace_id="other", name="Foreign", request_key="foreign")
        db.add(project)
        db.flush()
        requirement = Requirement(project_id=project.id, version=1, content="Private scope")
        db.add(requirement)
        db.flush()
        run = WorkflowRun(
            project_id=project.id,
            requirement_id=requirement.id,
            request_key="foreign-run",
            mode="openai",
            status="blocked",
        )
        db.add(run)
        db.flush()
        task = Task(
            project_id=project.id,
            run_id=run.id,
            title="Private task",
            role="pm",
            status="failed",
            correlation_id=str(uuid4()),
            request_key="foreign-task",
        )
        db.add(task)
        db.flush()
        db.add_all(
            [
                Artifact(
                    project_id=project.id,
                    run_id=run.id,
                    task_id=task.id,
                    kind="prd",
                    content="Private artifact",
                ),
                ModelUsage(
                    project_id=project.id,
                    run_id=run.id,
                    task_id=task.id,
                    attempt=1,
                    model="test-model",
                    input_tokens=1,
                    output_tokens=1,
                ),
                AuditLog(
                    workspace_id="other",
                    project_id=project.id,
                    action="private.action",
                    resource_id=run.id,
                    correlation_id=str(uuid4()),
                ),
            ]
        )
        project_id, run_id, task_id = project.id, run.id, task.id

    project_url = f"/api/v1/projects/{project_id}"
    run_url = f"/api/v1/runs/{run_id}"
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "foreign-check"}
    requests = [
        ("get", project_url, None),
        ("post", f"{project_url}/budget", {"token_budget": 600000}),
        ("post", f"{project_url}/tasks", {"title": "Leak?"}),
        ("get", f"{project_url}/tasks", None),
        ("get", f"/api/v1/tasks/{task_id}", None),
        ("post", f"{project_url}/requirements", {"content": "New private scope"}),
        ("get", f"{project_url}/requirements", None),
        ("post", f"{project_url}/runs", {}),
        ("get", f"{project_url}/runs", None),
        ("get", run_url, None),
        ("get", f"{run_url}/files", None),
        ("get", f"{run_url}/file?path=README.md", None),
        ("post", f"{run_url}/cancel", None),
        ("post", f"{run_url}/resume", None),
        ("get", f"{project_url}/artifacts", None),
        ("get", f"{project_url}/activity", None),
        ("get", f"{project_url}/model-usage", None),
    ]
    for method, url, body in requests:
        response = client.request(method, url, json=body, headers=headers)
        assert response.status_code == 404, f"{method.upper()} {url}: {response.text}"

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.stream_project_events(UUID(project_id), x_api_key="test-secret"))
    assert error.value.status_code == 404
    with sessions() as db:
        assert db.get(Project, project_id).token_budget == 500000
        assert db.get(WorkflowRun, run_id).status == "blocked"
        assert db.get(Task, task_id).status == "failed"
        assert len(db.scalars(select(Task).where(Task.project_id == project_id)).all()) == 1


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

    renewed = client.post(f"/api/v1/members/{viewer['id']}/tokens", headers=owner)
    assert renewed.status_code == 200, renewed.text
    replacement = renewed.json()
    assert replacement["api_token"] != viewer["api_token"]
    tokens = client.get(f"/api/v1/members/{viewer['id']}/tokens", headers=owner).json()
    assert {row["id"] for row in tokens} == {viewer["token_id"], replacement["id"]}
    assert all("api_token" not in row for row in tokens)
    assert (
        client.get("/api/v1/projects", headers={"X-API-Key": replacement["api_token"]}).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/members/{viewer['id']}/tokens", headers=viewer_headers).status_code
        == 401
    )


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


def test_cancelling_run_marks_claimed_tasks_cancelled(environment):
    client, sessions = environment
    with sessions.begin() as db:
        project = Project(workspace_id="ws", name="Cancel running", request_key="cancel-running")
        db.add(project)
        db.flush()
        requirement = Requirement(project_id=project.id, version=1, content="Build a test API")
        db.add(requirement)
        db.flush()
        run = WorkflowRun(
            project_id=project.id,
            requirement_id=requirement.id,
            request_key="cancel-running",
            mode="openai",
            status="running",
        )
        db.add(run)
        db.flush()
        for status in ("completed", "running", "ready"):
            db.add(
                Task(
                    project_id=project.id,
                    run_id=run.id,
                    title=f"Task {status}",
                    role="developer",
                    status=status,
                    correlation_id=str(uuid4()),
                    request_key=status,
                )
            )
        run_id = run.id

    headers = {"X-API-Key": "test-secret"}
    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    with sessions() as db:
        statuses = {task.request_key: task.status for task in db.scalars(select(Task)).all()}
        assert statuses == {"completed": "completed", "running": "cancelled", "ready": "cancelled"}
        assert (
            len(db.scalars(select(AuditLog).where(AuditLog.action == "run.cancelled")).all()) == 1
        )

    assert client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers).status_code == 200
    with sessions() as db:
        assert (
            len(db.scalars(select(AuditLog).where(AuditLog.action == "run.cancelled")).all()) == 1
        )


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
        if role == "developer":
            routed = []
            monkeypatch.setattr(
                dispatcher_worker,
                "publish_sync",
                lambda _, topic, key, payload: routed.append(topic),
            )
            dispatcher_worker.dispatch_payload(event.model_dump_json().encode(), object())
            assert routed == [TASKS_AI_DEVELOPER]
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


def test_ai_heartbeat_refreshes_only_the_active_attempt(environment):
    _, sessions = environment
    stale = utcnow() - timedelta(minutes=20)
    with sessions.begin() as db:
        project = Project(workspace_id="ws", name="Heartbeat", request_key="heartbeat")
        db.add(project)
        db.flush()
        requirement = Requirement(project_id=project.id, version=1, content="Build an API")
        db.add(requirement)
        db.flush()
        run = WorkflowRun(
            project_id=project.id,
            requirement_id=requirement.id,
            request_key="heartbeat",
            mode="openai",
            status="running",
        )
        db.add(run)
        db.flush()
        task = Task(
            project_id=project.id,
            run_id=run.id,
            title="Slow model call",
            role="pm",
            status="running",
            attempt=2,
            correlation_id=str(uuid4()),
            request_key="heartbeat",
            updated_at=stale,
        )
        db.add(task)
        db.flush()
        task_id, run_id = task.id, run.id

    assert ai_worker.heartbeat_task(task_id, run_id, 2) is True
    with sessions() as db:
        refreshed = db.get(Task, task_id).updated_at
        assert refreshed.replace(tzinfo=stale.tzinfo) > stale
    assert recovery_worker.recover_stale_tasks(max_age_seconds=600) == 0
    assert ai_worker.heartbeat_task(task_id, run_id, 1) is False
    with sessions() as db:
        assert db.get(Task, task_id).updated_at == refreshed

    with sessions.begin() as db:
        db.get(WorkflowRun, run_id).status = "cancelled"
    assert ai_worker.heartbeat_task(task_id, run_id, 2) is False
    with sessions() as db:
        assert db.get(Task, task_id).updated_at == refreshed


def test_ai_heartbeat_runs_during_work_and_stops_afterward(monkeypatch):
    pulsed = Event()
    monkeypatch.setattr(ai_worker, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(ai_worker, "heartbeat_task", lambda *_args: pulsed.set() or True)
    with ai_worker.keep_task_alive("task", "run", 1):
        assert pulsed.wait(timeout=1)


def test_stale_ai_failure_does_not_block_new_attempt(environment, monkeypatch):
    client, sessions = environment

    class OpenAISettings:
        api_key = "test-secret"
        workspace_id = "ws"
        agent_mode = "openai"

    monkeypatch.setattr(main, "get_settings", lambda: OpenAISettings())
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "stale-project"}
    project_id = client.post("/api/v1/projects", json={"name": "Stale"}, headers=headers).json()[
        "id"
    ]
    client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"content": "Build a calculator."},
        headers=headers,
    )
    headers["Idempotency-Key"] = "stale-run"
    run_id = client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers).json()[
        "id"
    ]
    with sessions() as db:
        task = db.scalar(select(Task).where(Task.run_id == run_id))
        task_id = task.id
        event = EventEnvelope.model_validate(
            db.scalar(select(OutboxEvent).where(OutboxEvent.event_key == task_id)).payload
        )

    def fail_after_retry(*_args):
        with sessions.begin() as db:
            task = db.get(Task, task_id)
            task.attempt = 2
            task.status = "running"
        raise RuntimeError("old attempt failed after retry")

    monkeypatch.setattr(ai_worker, "_perform", fail_after_retry)
    assert ai_worker.process_ai_event(event, "pm") is True
    with sessions() as db:
        task = db.get(Task, task_id)
        run = db.get(WorkflowRun, run_id)
        assert task.attempt == 2
        assert task.status == "running"
        assert run.status == "running"
        assert (
            db.scalar(
                select(AuditLog).where(
                    AuditLog.resource_id == task_id, AuditLog.action == "task.failed"
                )
            )
            is None
        )
        assert (
            db.scalar(select(ProcessedEvent).where(ProcessedEvent.event_id == str(event.event_id)))
            is not None
        )


def test_stale_ai_success_discards_result_and_accounts_usage(environment, monkeypatch):
    client, sessions = environment

    class OpenAISettings:
        api_key = "test-secret"
        workspace_id = "ws"
        agent_mode = "openai"

    monkeypatch.setattr(main, "get_settings", lambda: OpenAISettings())
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "late-project"}
    project_id = client.post(
        "/api/v1/projects", json={"name": "Late result"}, headers=headers
    ).json()["id"]
    client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"content": "Build a calculator with tests."},
        headers=headers,
    )
    headers["Idempotency-Key"] = "late-run"
    run_id = client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers).json()[
        "id"
    ]
    with sessions() as db:
        task = db.scalar(select(Task).where(Task.run_id == run_id))
        task_id = task.id
        event = EventEnvelope.model_validate(
            db.scalar(select(OutboxEvent).where(OutboxEvent.event_key == task_id)).payload
        )

    def complete_after_retry(*_args):
        with sessions.begin() as db:
            task = db.get(Task, task_id)
            task.attempt = 2
            task.status = "ready"
        assert ai_worker.process_ai_event(event, "pm") is False
        with sessions() as db:
            assert (
                db.scalar(
                    select(ProcessedEvent).where(ProcessedEvent.event_id == str(event.event_id))
                )
                is None
            )
        return ai_worker.WorkOutput(
            kind="prd",
            content="Stale PRD",
            summary="Old attempt finished",
            input_tokens=12,
            output_tokens=8,
        )

    monkeypatch.setattr(ai_worker, "_perform", complete_after_retry)
    assert ai_worker.process_ai_event(event, "pm") is False
    assert ai_worker.process_ai_event(event, "pm") is False
    with sessions() as db:
        task = db.get(Task, task_id)
        assert task.attempt == 2 and task.status == "ready"
        assert db.get(WorkflowRun, run_id).status == "running"
        assert db.get(Project, project_id).tokens_used == 20
        usage = db.scalars(select(ModelUsage).where(ModelUsage.task_id == task_id)).all()
        assert len(usage) == 1 and usage[0].attempt == 1
        assert db.scalars(select(Artifact).where(Artifact.task_id == task_id)).all() == []
        assert db.scalars(select(Approval).where(Approval.run_id == run_id)).all() == []
        discarded = db.scalars(
            select(AuditLog).where(AuditLog.action == "task.stale_result_discarded")
        ).all()
        assert len(discarded) == 1
