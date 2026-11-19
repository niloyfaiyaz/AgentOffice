"""Explicit, validated state machines for projects, runs, tasks and agent visual status."""
from __future__ import annotations


class InvalidTransition(ValueError):
    pass


PROJECT_STATES = {
    "draft", "awaiting_approval", "ready", "running", "pausing", "paused",
    "blocked", "completed", "failed", "cancelled",
}
PROJECT_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"awaiting_approval", "running", "cancelled", "failed", "draft"},
    "awaiting_approval": {"ready", "running", "draft", "cancelled", "failed", "awaiting_approval"},
    "ready": {"running", "cancelled", "draft"},
    "running": {"pausing", "paused", "blocked", "completed", "failed", "cancelled", "awaiting_approval", "running"},
    "pausing": {"paused", "cancelled", "failed", "running", "completed", "blocked"},
    "paused": {"running", "cancelled", "awaiting_approval"},
    "blocked": {"running", "cancelled", "failed", "paused", "pausing", "blocked", "awaiting_approval"},
    # A finished project can start a new revision run.
    "completed": {"awaiting_approval", "running", "draft", "completed"},
    "failed": {"awaiting_approval", "running", "draft"},
    "cancelled": {"awaiting_approval", "running", "draft"},
}

RUN_STATES = {
    "planning", "awaiting_approval", "running", "pausing", "paused", "blocked",
    "completed", "failed", "cancelled",
}
RUN_TERMINAL = {"completed", "failed", "cancelled"}
RUN_TRANSITIONS: dict[str, set[str]] = {
    "planning": {"awaiting_approval", "failed", "cancelled", "planning", "pausing", "paused", "blocked"},
    "awaiting_approval": {"running", "planning", "cancelled", "awaiting_approval"},
    "running": {"pausing", "paused", "blocked", "completed", "failed", "cancelled", "running", "awaiting_approval"},
    "pausing": {"paused", "cancelled", "failed", "completed", "running", "blocked"},
    "paused": {"running", "planning", "cancelled"},
    "blocked": {"running", "planning", "cancelled", "failed", "paused", "pausing", "blocked"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

TASK_STATES = {
    "pending", "ready", "running", "waiting_approval", "waiting_subtask", "paused",
    "completed", "failed", "cancelled", "skipped",
}
TASK_DONE = {"completed", "skipped"}
TASK_TERMINAL = {"completed", "failed", "cancelled", "skipped"}
TASK_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"ready", "running", "cancelled", "skipped"},
    "ready": {"running", "cancelled", "skipped", "pending"},
    "running": {"completed", "failed", "waiting_approval", "waiting_subtask", "paused", "ready", "cancelled"},
    "waiting_approval": {"ready", "running", "failed", "cancelled", "skipped"},
    "waiting_subtask": {"ready", "running", "failed", "cancelled"},
    "paused": {"ready", "running", "cancelled"},
    # A failed task can be retried (targeted recovery) or skipped by the client.
    "failed": {"ready", "skipped", "cancelled"},
    "completed": set(),
    "cancelled": set(),
    "skipped": set(),
}

AGENT_VISUAL_STATES = {
    "idle", "assigned", "walking", "working", "communicating", "reviewing",
    "waiting_for_client", "blocked", "completed", "failed",
}


def _check(kind: str, table: dict[str, set[str]], states: set[str], current: str, new: str) -> None:
    if new not in states:
        raise InvalidTransition(f"Unknown {kind} state '{new}'")
    if current not in table:
        raise InvalidTransition(f"Unknown current {kind} state '{current}'")
    if new == current and new in table[current]:
        return
    if new not in table[current]:
        raise InvalidTransition(f"Invalid {kind} transition {current} -> {new}")


def transition_project(project, new: str) -> None:
    _check("project", PROJECT_TRANSITIONS, PROJECT_STATES, project.status, new)
    project.status = new


def transition_run(run, new: str) -> None:
    if run.status == new:
        return
    _check("run", RUN_TRANSITIONS, RUN_STATES, run.status, new)
    run.status = new


def transition_task(task, new: str) -> None:
    if task.status == new:
        return
    _check("task", TASK_TRANSITIONS, TASK_STATES, task.status, new)
    task.status = new


def project_status_for_run(run_status: str) -> str:
    """The project's displayed status mirrors its latest run."""
    return {
        "planning": "running",
        "awaiting_approval": "awaiting_approval",
        "running": "running",
        "pausing": "pausing",
        "paused": "paused",
        "blocked": "blocked",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }[run_status]


def sync_project_status(project, run) -> None:
    target = project_status_for_run(run.status)
    if project.status == target:
        return
    transition_project(project, target)
