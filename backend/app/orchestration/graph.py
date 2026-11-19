"""LangGraph run graph.

    START -> route -+-> plan -----------------------------> END (awaiting SOW approval)
                    +-> execute -+-> review_gate -+-> execute (rework / QA / consolidation)
                    |            |                +-> finalize -> END
                    |            +-> settle (blocked, waiting for client) -> END
                    |            +-> halt (pause / cancel) -> END
                    +-> halt -> END
                    +-> END (nothing to do)

The database (tasks, executions, approvals) is the authoritative state; graph state only
carries the run id and the last step's outcome. Each invocation is checkpointed in Postgres
(thread_id = run id) so an interrupted invocation can be inspected and resumed.
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..db import SessionLocal
from ..models import ProjectRun
from . import flow, planner


class RunState(TypedDict, total=False):
    run_id: str
    outcome: str


def _run(state: RunState) -> uuid.UUID:
    return uuid.UUID(state["run_id"])


def route(state: RunState) -> RunState:
    return {"outcome": "routed"}


def route_next(state: RunState) -> Literal["plan", "execute", "halt", "__end__"]:
    with SessionLocal() as db:
        run = db.get(ProjectRun, _run(state))
        if run is None:
            return END
        if run.requested_action in ("pause", "cancel"):
            return "halt"
        if run.status == "planning":
            return "plan"
        if run.status == "running":
            return "execute"
        return END


async def plan(state: RunState) -> RunState:
    with SessionLocal() as db:
        outcome = await planner.plan_run(db, _run(state))
    return {"outcome": outcome}


async def execute(state: RunState) -> RunState:
    return {"outcome": await flow.execute(_run(state))}


def after_execute(state: RunState) -> Literal["review_gate", "settle", "halt"]:
    o = state.get("outcome")
    if o == "control":
        return "halt"
    if o == "progress_done":
        return "review_gate"
    return "settle"


def review_gate(state: RunState) -> RunState:
    return {"outcome": flow.review_gate(_run(state))}


def after_review(state: RunState) -> Literal["execute", "finalize"]:
    return "execute" if state.get("outcome") == "more_work" else "finalize"


def settle(state: RunState) -> RunState:
    return {"outcome": flow.settle_waiting(_run(state))}


def finalize(state: RunState) -> RunState:
    flow.finalize(_run(state))
    return {"outcome": "completed"}


def halt(state: RunState) -> RunState:
    flow.halt(_run(state))
    return {"outcome": "halted"}


def build_graph(checkpointer=None):
    g = StateGraph(RunState)
    g.add_node("route", route)
    g.add_node("plan", plan)
    g.add_node("execute", execute)
    g.add_node("review_gate", review_gate)
    g.add_node("settle", settle)
    g.add_node("finalize", finalize)
    g.add_node("halt", halt)
    g.add_edge(START, "route")
    g.add_conditional_edges("route", route_next, ["plan", "execute", "halt", END])
    g.add_edge("plan", END)
    g.add_conditional_edges("execute", after_execute, ["review_gate", "settle", "halt"])
    g.add_conditional_edges("review_gate", after_review, ["execute", "finalize"])
    g.add_edge("settle", END)
    g.add_edge("finalize", END)
    g.add_edge("halt", END)
    return g.compile(checkpointer=checkpointer)


async def invoke(run_id: uuid.UUID, checkpointer=None) -> Optional[str]:
    graph = build_graph(checkpointer)
    cfg = {"configurable": {"thread_id": f"run-{run_id}"}, "recursion_limit": 400}
    out = await graph.ainvoke({"run_id": str(run_id), "outcome": "start"}, cfg)
    return out.get("outcome")
