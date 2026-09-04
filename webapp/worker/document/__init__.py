"""Async source-material extraction: anydoc plus a Chinese OCR fallback.

Ported from the ``kLeagl`` document-runtime. ``ocr_worker`` runs PaddleOCR in
its own virtualenv as a long-lived subprocess; ``ocr_client`` manages that
subprocess from the Celery worker; ``extraction`` is the orchestration the
``runner.extract_material`` task calls.
"""
