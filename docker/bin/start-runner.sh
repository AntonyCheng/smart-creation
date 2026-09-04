#!/bin/sh
# Separate Celery consumers share this runtime so neither an agent-assisted
# template import nor a slow OCR material pass blocks the single-concurrency
# generation queue.
set -e
celery -A runner.celery_app:celery_app worker --queues pptmaster-jobs --loglevel=INFO --concurrency=1 &
jobs_pid=$!
celery -A runner.celery_app:celery_app worker --queues pptmaster-template-imports --loglevel=INFO --concurrency=1 &
imports_pid=$!
celery -A runner.celery_app:celery_app worker --queues pptmaster-documents --loglevel=INFO --concurrency=1 &
documents_pid=$!
trap 'kill "$jobs_pid" "$imports_pid" "$documents_pid" 2>/dev/null || true' TERM INT
wait
