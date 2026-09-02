#!/bin/sh
# Two Celery consumers share this runtime so an agent-assisted template
# import never blocks the single-concurrency generation queue.
set -e
celery -A runner.celery_app:celery_app worker --queues pptmaster-jobs --loglevel=INFO --concurrency=1 &
jobs_pid=$!
celery -A runner.celery_app:celery_app worker --queues pptmaster-template-imports --loglevel=INFO --concurrency=1 &
imports_pid=$!
trap 'kill "$jobs_pid" "$imports_pid" 2>/dev/null || true' TERM INT
wait
