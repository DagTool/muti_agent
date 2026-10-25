"""Exercise the complete local mock workflow against running services."""

import time
from uuid import uuid4

import httpx

from apps.api.app.core.config import get_settings


def main():
    settings = get_settings()
    if settings.agent_mode != "mock":
        raise RuntimeError("This smoke script is for AGENTFORGE_AGENT_MODE=mock")
    if not settings.api_key:
        raise RuntimeError("Set AGENTFORGE_API_KEY")
    headers = {"X-API-Key": settings.api_key, "Idempotency-Key": str(uuid4())}
    with httpx.Client(base_url="http://127.0.0.1:8000", headers=headers, timeout=10) as client:
        response = client.post("/api/v1/projects", json={"name": "Smoke test project"})
        response.raise_for_status()
        project_id = response.json()["id"]
        response = client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"content": "Create a small calculator with tests."},
        )
        response.raise_for_status()
        headers["Idempotency-Key"] = str(uuid4())
        response = client.post(f"/api/v1/projects/{project_id}/runs", json={}, headers=headers)
        response.raise_for_status()
        run = response.json()
        assert run["mode"] == "mock"
        run_id = run["id"]
        scope = next(
            approval
            for approval in client.get("/api/v1/approvals").json()
            if approval["run_id"] == run_id and approval["action"] == "scope"
        )
        response = client.post(
            f"/api/v1/approvals/{scope['id']}/decision", json={"decision": "approve"}
        )
        response.raise_for_status()
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if (
                client.get(f"/api/v1/runs/{run_id}").json()["status"]
                == "awaiting_handover_approval"
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Workers did not reach handover approval")
        handover = next(
            approval
            for approval in client.get("/api/v1/approvals").json()
            if approval["run_id"] == run_id and approval["action"] == "handover"
        )
        response = client.post(
            f"/api/v1/approvals/{handover['id']}/decision", json={"decision": "approve"}
        )
        response.raise_for_status()
        assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "completed"
        print(f"Smoke workflow completed: project={project_id} run={run_id}")


if __name__ == "__main__":
    main()
