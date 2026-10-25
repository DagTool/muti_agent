"""Deterministic plan → code → review graph used before real agent integration."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class WorkflowState(TypedDict, total=False):
    requirement: str
    plan: str
    code: str
    review: str


def plan(state: WorkflowState) -> WorkflowState:
    return {"plan": f"Plan for: {state['requirement']}"}


def code(state: WorkflowState) -> WorkflowState:
    return {"code": f"Mock implementation of {state['plan']}"}


def review(state: WorkflowState) -> WorkflowState:
    return {"review": "passed" if state["code"].startswith("Mock implementation") else "failed"}


def build_graph(checkpointer=None):
    builder = StateGraph(WorkflowState)
    builder.add_node("plan", plan)
    builder.add_node("code", code)
    builder.add_node("review", review)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "code")
    builder.add_edge("code", "review")
    builder.add_edge("review", END)
    return builder.compile(checkpointer=checkpointer)
