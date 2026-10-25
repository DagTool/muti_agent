from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.app import main
from apps.api.app.db.base import Base, OutboxEvent, ProcessedEvent, Project, Task, Workspace
from apps.api.app.db.session import get_db
from packages.communication.contracts import TASK_COMMANDS, TASK_RESULTS, EventEnvelope
from packages.orchestration.graph import build_graph
from workers import agent_worker, dispatcher_worker, outbox_worker


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

    main.app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main, "get_settings", lambda: Settings())
    monkeypatch.setattr(agent_worker, "new_session", sessions)
    monkeypatch.setattr(outbox_worker, "new_session", sessions)
    yield TestClient(main.app), sessions
    main.app.dependency_overrides.clear()
    engine.dispose()


def test_api_outbox_worker_and_duplicate(environment):
    client, sessions = environment
    headers = {"X-API-Key": "test-secret", "Idempotency-Key": "project-1"}
    response = client.post("/api/v1/projects", json={"name": "Demo"}, headers=headers)
    assert response.status_code == 200, response.text
    project_id = response.json()["id"]
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
