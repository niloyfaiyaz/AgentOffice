"""Persistent execution worker.

Run with ``python -m app.worker``. Claims runnable runs from Postgres with a lease
(SELECT ... FOR UPDATE SKIP LOCKED), executes them through the LangGraph run graph,
heartbeats the lease, and releases it when the run stops (finished, waiting for the
client, paused or cancelled). If the process dies, the lease expires and the next worker
recovers interrupted tasks from their persisted conversations.

Execution never depends on a browser connection or an HTTP request.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import or_, select, text

from .config import settings
from .db import SessionLocal
from .models import ProjectRun, utcnow
from .orchestration import flow, graph

log = logging.getLogger("agentoffice.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
RUNNABLE = ("planning", "running", "pausing")


def claim_one() -> Optional[uuid.UUID]:
    with SessionLocal() as db:
        now = utcnow()
        q = (select(ProjectRun)
             .where(or_(ProjectRun.status.in_(RUNNABLE),
                        (ProjectRun.requested_action == "cancel") & ProjectRun.status.notin_(["completed", "failed", "cancelled"])))
             .where(or_(ProjectRun.lease_expires_at.is_(None), ProjectRun.lease_expires_at < now))
             .order_by(ProjectRun.updated_at)
             .with_for_update(skip_locked=True).limit(1))
        run = db.scalar(q)
        if run is None:
            return None
        run.lease_owner = WORKER_ID
        run.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
        if run.started_at is None and run.status == "running":
            run.started_at = now
        # Holding the lease means no other worker is executing this run, so any task still
        # marked "running" was interrupted (crash or shutdown) and is resumed from its
        # persisted conversation.
        flow.recover_interrupted(db, run)
        db.commit()
        return run.id


def heartbeat(run_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE project_runs SET lease_expires_at = :t WHERE id = :id AND lease_owner = :w"),
                   {"t": utcnow() + timedelta(seconds=settings.lease_seconds), "id": run_id, "w": WORKER_ID})
        db.commit()


def release(run_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE project_runs SET lease_owner = NULL, lease_expires_at = NULL WHERE id = :id AND lease_owner = :w"),
                   {"id": run_id, "w": WORKER_ID})
        db.commit()


async def drive(run_id: uuid.UUID, checkpointer) -> None:
    async def beat():
        while True:
            await asyncio.sleep(settings.lease_seconds / 3)
            await asyncio.to_thread(heartbeat, run_id)

    hb = asyncio.create_task(beat())
    try:
        # A run can become runnable again during the invocation (e.g. the client answers
        # while the graph is finishing). Loop until it rests in a non-runnable state.
        for _ in range(50):
            await graph.invoke(run_id, checkpointer)
            with SessionLocal() as db:
                run = db.get(ProjectRun, run_id)
                if run is None or (run.status not in RUNNABLE and run.requested_action != "cancel"):
                    break
    except Exception:
        log.exception("run %s crashed", run_id)
        with SessionLocal() as db:
            run = db.get(ProjectRun, run_id)
            if run and run.status not in ("completed", "failed", "cancelled"):
                from . import events
                from .state_machine import sync_project_status, transition_run
                from .models import Project

                run.error = "The orchestrator hit an internal error; see the worker log."
                transition_run(run, "failed")
                sync_project_status(db.get(Project, run.project_id), run)
                events.emit(db, run.project_id, "run_failed", run.error, run_id=run.id)
                db.commit()
    finally:
        hb.cancel()
        release(run_id)


async def make_checkpointer():
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        conninfo = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
        pool = AsyncConnectionPool(conninfo, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0}, open=False)
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        return saver, pool
    except Exception:
        log.exception("Postgres checkpointer unavailable; continuing without graph checkpoints")
        return None, None


async def main(stop_after_idle: Optional[float] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("worker %s starting", WORKER_ID)
    checkpointer, pool = await make_checkpointer()
    active: dict[uuid.UUID, asyncio.Task] = {}
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    idle = 0.0
    try:
        while not stop.is_set():
            for rid, t in list(active.items()):
                if t.done():
                    active.pop(rid)
            claimed = None
            if len(active) < settings.max_parallel_runs:
                claimed = await asyncio.to_thread(claim_one)
                if claimed and claimed not in active:
                    log.info("claimed run %s", claimed)
                    active[claimed] = asyncio.create_task(drive(claimed, checkpointer))
            if claimed is None:
                idle = idle + settings.worker_poll_seconds if not active else 0.0
                if stop_after_idle is not None and idle >= stop_after_idle:
                    break
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
                except asyncio.TimeoutError:
                    pass
    finally:
        for t in active.values():
            t.cancel()
        if pool is not None:
            await pool.close()
        log.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
