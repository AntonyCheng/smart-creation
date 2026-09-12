"""Mark jobs terminal when their runner died before finishing them.

``runner.execute_job`` acknowledges its message before completing, so a runner
that dies mid-job (container restart, host reboot, killed worker child) never
reaches ``_finish_job`` and the row stays RUNNING forever: the UI shows an
endless generating/cancelling spinner and the project rejects new jobs.
Reconciliation compares DB state against the live workers' active-task view
and writes the missing terminal state.
"""

from __future__ import annotations

from datetime import UTC, datetime

from celery.utils.log import get_task_logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api.config import get_settings
from api.models import Job, JobEvent, JobStatus

logger = get_task_logger(__name__)
settings = get_settings()
_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(_engine, expire_on_commit=False)

INTERRUPTED_MESSAGE = "运行器中断导致任务停止，请重新生成或继续"


def active_execute_job_ids(app) -> set[str] | None:
    """Job ids currently executing on live workers; None when unknown.

    Unknown (inspection failure) must abort reconciliation: an empty snapshot
    here would mark every genuinely running job as interrupted.
    """

    try:
        snapshot = app.control.inspect(timeout=10.0).active() or {}
    except Exception:  # noqa: BLE001
        logger.warning("Active-task inspection failed; skipping reconciliation")
        return None
    if not snapshot:
        # No worker replied within the timeout (e.g. all busy): an empty but
        # valid-looking snapshot here would mark genuinely running jobs as
        # interrupted, so treat it as unknown and skip this cycle. A healthy
        # idle cluster replies with per-worker empty task lists instead.
        logger.warning("No worker replied to active-task inspection; skipping reconciliation")
        return None
    ids: set[str] = set()
    for tasks in snapshot.values():
        for task in tasks or []:
            if task.get("name") != "runner.execute_job":
                continue
            args = task.get("args") or []
            if args:
                ids.add(str(args[0]).strip('"'))
    return ids


def reconcile_interrupted_jobs(active_job_ids: set[str] | None, only_job_ids: set[str] | None = None) -> int:
    """Write terminal state for RUNNING jobs absent from the active set.

    ``only_job_ids``, when given, further restricts which missing jobs are
    actually reconciled (used by the periodic watchdog's two-round-confirm
    wrapper below); the startup path (``main()``) leaves it unset since no
    task can be legitimately active before any worker has booted.
    """

    if active_job_ids is None:
        return 0
    from runner.tasks import _record_refinement_result

    recovered = 0
    with SessionLocal() as db:
        jobs = db.execute(select(Job).where(Job.status == JobStatus.RUNNING)).scalars().all()
        for job in jobs:
            job_id = str(job.id)
            if job_id in active_job_ids:
                continue
            if only_job_ids is not None and job_id not in only_job_ids:
                continue
            cancelled = bool(job.cancellation_requested)
            job.status = JobStatus.CANCELLED if cancelled else JobStatus.FAILED
            job.error = None if cancelled else INTERRUPTED_MESSAGE
            job.finished_at = datetime.now(UTC)
            db.add(JobEvent(job_id=job.id, event_type="status", payload={"status": job.status.value}))
            _record_refinement_result(db, job)
            recovered += 1
        db.commit()
    if recovered:
        logger.warning("Marked %d job(s) terminal after runner interruption", recovered)
    return recovered


_suspect_job_ids: set[str] = set()


def reconcile_interrupted_jobs_periodic(active_job_ids: set[str] | None) -> int:
    """Two-round-confirmation wrapper for the periodic in-process watchdog.

    A single "missing from the active snapshot" reading can be a transient
    inspect() hiccup — worker busy, broker latency, or (historically, before
    every celery worker in start-runner.sh got a unique -n hostname) multiple
    same-named nodes' control replies colliding and silently dropping a
    genuinely running job from the snapshot. Only reconcile a job once it is
    missing on two consecutive checks 300s apart, so one bad reading can never
    by itself flip a still-running job to a false "failed".
    """

    global _suspect_job_ids
    if active_job_ids is None:
        _suspect_job_ids = set()
        return 0
    with SessionLocal() as db:
        running_ids = {str(job_id) for (job_id,) in db.execute(select(Job.id).where(Job.status == JobStatus.RUNNING)).all()}
    missing = running_ids - active_job_ids
    confirmed = missing & _suspect_job_ids
    _suspect_job_ids = missing
    if not confirmed:
        return 0
    return reconcile_interrupted_jobs(active_job_ids, only_job_ids=confirmed)


def main() -> int:
    """Entry for start-runner: before workers boot, no job can be active."""

    count = reconcile_interrupted_jobs(set())
    print(f"[reconcile] marked {count} interrupted job(s) terminal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
