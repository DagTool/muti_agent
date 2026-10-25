"""Run the safe mock graph; --postgres persists LangGraph checkpoints locally."""

import argparse
import json
import os
from uuid import uuid4

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from apps.api.app.core.config import get_settings
from packages.orchestration.graph import build_graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("requirement", nargs="?", default="Create a task API")
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    config = {"configurable": {"thread_id": str(uuid4())}}

    if args.postgres:
        dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
        if not dsn.startswith("postgresql://"):
            parser.error("--postgres requires an AGENTFORGE_DATABASE_URL for PostgreSQL")
        with PostgresSaver.from_conn_string(dsn) as checkpointer:
            checkpointer.setup()
            result = build_graph(checkpointer).invoke({"requirement": args.requirement}, config)
    else:
        result = build_graph(InMemorySaver()).invoke({"requirement": args.requirement}, config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
