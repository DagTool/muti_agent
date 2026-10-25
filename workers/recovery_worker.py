"""Recover OpenAI tasks left running after a worker interruption."""

import logging
import time
from datetime import timedelta

from sqlalchemy import select

from apps.api.app.db.base import AuditLog, Project, Task, WorkflowRun, utcnow
from apps.api.app.db.session import new_session
from apps.api.app.services.workflow import retry_task

log = logging.getLogger(__name__)


def recover_stale_tasks(max_age_seconds: int = 600) -> int:
    cutoff = utcnow() - timedelta(seconds=max_age_seconds)
    with new_session() as db:
        ids = db.scalars(
            select(Task.id).where(Task.status == "running", Task.updated_at < cutoff).limit(50)
        ).all()
    recovered = 0
    for task_id in ids:
        with new_session() as db:
            task = db.get(Task, task_id)
            if task is None or task.run_id is None:
                continue
            run = db.scalar(
                select(WorkflowRun).where(WorkflowRun.id == task.run_id).with_for_update()
            )
            task = db.scalar(
                select(Task)
                .where(Task.id == task_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            expired = db.scalar(select(Task.id).where(Task.id == task_id, Task.updated_at < cutoff))
            if task.status != "running" or not expired or run.mode != "openai":
                continue
            if run.status == "cancelled":
                task.status = "cancelled"
            elif run.status == "running":
                project = db.get(Project, run.project_id)
                if task.attempt < 3:
                    retry_task(db, project, task)
                else:
                    task.status = "failed"
                    task.result = "Worker interrupted after retry limit"
                    run.status = "blocked"
                    db.add(
                        AuditLog(
                            workspace_id=project.workspace_id,
                            project_id=project.id,
                            action="task.failed",
                            resource_id=task.id,
                            correlation_id=task.correlation_id,
                        )
                    )
            else:
                continue
            db.commit()
            recovered += 1
    return recovered


def main():
    logging.basicConfig(level=logging.INFO)
    try:
        while True:
            try:
                count = recover_stale_tasks()
                if count:
                    log.info("Recovered %s stale tasks", count)
            except Exception:
                log.exception("Recovery sweep failed")
            time.sleep(30)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
