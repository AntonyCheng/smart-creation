#!/bin/sh
# Separate Celery consumers share this runtime so neither an agent-assisted
# template import nor a slow OCR material pass blocks the single-concurrency
# generation queue.
set -e
# A killed runner leaves RUNNING jobs without a terminal state; recover them
# before any worker boots (no task can be legitimately active at this point).
python -m runner.reconcile || echo "[start-runner] reconcile skipped"
# Each worker needs a distinct -n/--hostname: without it all three default to
# the same "celery@<container-hostname>" node name, so control broadcasts
# like `inspect().active()` (used by the reconciliation watchdog below) get
# multiple same-named replies that collide in the response dict — whichever
# reply lands last silently overwrites the others, which can make a job the
# jobs-queue worker is genuinely running disappear from the snapshot and get
# reconciled as interrupted even though it is still executing.
PPTMASTER_QUEUE_ROLE=jobs celery -A runner.celery_app:celery_app worker -n jobs@%h --queues pptmaster-jobs --loglevel=INFO --concurrency=1 &
jobs_pid=$!
celery -A runner.celery_app:celery_app worker -n imports@%h --queues pptmaster-template-imports --loglevel=INFO --concurrency=1 &
imports_pid=$!
celery -A runner.celery_app:celery_app worker -n documents@%h --queues pptmaster-documents --loglevel=INFO --concurrency=1 &
documents_pid=$!
trap 'kill "$jobs_pid" "$imports_pid" "$documents_pid" 2>/dev/null || true' TERM INT
wait
