"""Manage the long-lived PaddleOCR subprocess from the Celery worker.

Ported from the kLeagl ``OcrClientService``. One worker process is spawned
lazily and kept alive; it speaks JSON Lines over stdin/stdout. The
``pptmaster-documents`` queue runs at concurrency 1, but a lock still
serialises jobs defensively so a second caller can never interleave frames.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

# Match the Dockerfile.runner layout. A bare interpreter is never assumed:
# "OCR configured" must mean "a real PaddleOCR virtualenv exists".
_DEFAULT_PYTHON = "/opt/ocr-venv/bin/python"
_DEFAULT_WORKER = str(Path(__file__).with_name("ocr_worker.py"))
_DEFAULT_TIMEOUT_MS = 180_000


class OcrError(RuntimeError):
    """OCR failed in a way the caller should surface, carrying a short code."""

    def __init__(self, message: str, code: str = "OCR_FAILED") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class OcrResult:
    page_count: int | None = None
    character_count: int = 0
    average_confidence: float | None = None
    warnings: list[str] = field(default_factory=list)


def _python_path() -> str:
    return (os.environ.get("DOCUMENT_OCR_PYTHON") or "").strip() or _DEFAULT_PYTHON


def _worker_path() -> str:
    return (os.environ.get("DOCUMENT_OCR_WORKER") or "").strip() or _DEFAULT_WORKER


def _timeout_seconds() -> float:
    raw = os.environ.get("DOCUMENT_OCR_TIMEOUT_MS")
    try:
        value = int(raw) if raw else _DEFAULT_TIMEOUT_MS
    except ValueError:
        value = _DEFAULT_TIMEOUT_MS
    return max(value, 10_000) / 1000.0


def ocr_available() -> bool:
    """Whether OCR is enabled and its runtime is present on disk."""

    if (os.environ.get("DOCUMENT_OCR_ENABLED") or "").strip().lower() == "false":
        return False
    return Path(_python_path()).exists() and Path(_worker_path()).is_file()


def server_profile_enabled() -> bool:
    return (os.environ.get("DOCUMENT_OCR_SERVER_PROFILE_ENABLED") or "").strip().lower() == "true"


class _OcrClient:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._lines: "queue.Queue[str | None]" = queue.Queue()
        self._lock = threading.Lock()

    def extract(self, input_path: Path, output_path: Path, profile: str = "mobile") -> OcrResult:
        if not ocr_available():
            raise OcrError("中文 OCR 运行时尚未安装或已被禁用", "OCR_UNAVAILABLE")
        with self._lock:
            return self._run_job(input_path, output_path, profile)

    def shutdown(self) -> None:
        with self._lock:
            self._kill()

    # -- internals ---------------------------------------------------------

    def _run_job(self, input_path: Path, output_path: Path, profile: str) -> OcrResult:
        process = self._ensure_worker()
        job_id = uuid4().hex
        request = {
            "id": job_id,
            "inputPath": str(input_path),
            "outputPath": str(output_path),
            "lang": "ch",
            "profile": profile,
        }
        assert process.stdin is not None
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            self._kill()
            raise OcrError(f"OCR Worker 无法接收任务：{exc}", "OCR_WORKER_EXITED") from exc

        deadline = time.monotonic() + _timeout_seconds()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill()
                raise OcrError(f"OCR 处理超过 {int(_timeout_seconds())} 秒", "OCR_TIMEOUT")
            try:
                line = self._lines.get(timeout=min(remaining, 5.0))
            except queue.Empty:
                if self._process is None or self._process.poll() is not None:
                    self._kill()
                    raise OcrError("OCR Worker 意外退出", "OCR_WORKER_EXITED")
                continue
            if line is None:
                self._kill()
                raise OcrError("OCR Worker 意外退出", "OCR_WORKER_EXITED")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") != job_id:
                continue
            if not message.get("ok"):
                raise OcrError(
                    str(message.get("error") or "OCR 处理失败"),
                    str(message.get("code") or "OCR_FAILED"),
                )
            return OcrResult(
                page_count=message.get("pageCount"),
                character_count=int(message.get("characterCount") or 0),
                average_confidence=message.get("averageConfidence"),
                warnings=list(message.get("warnings") or []),
            )

    def _ensure_worker(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._drain_queue()
        models_dir = (os.environ.get("DOCUMENT_OCR_MODELS_DIR") or "").strip()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": "zh_CN.UTF-8",
            "LC_ALL": "zh_CN.UTF-8",
            "PYTHONUNBUFFERED": "1",
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            "FLAGS_minloglevel": "2",
        }
        if models_dir:
            env["PADDLE_PDX_CACHE_HOME"] = models_dir
            env["PADDLEOCR_HOME"] = models_dir
        if os.environ.get("DOCUMENT_OCR_DEBUG"):
            env["DOCUMENT_OCR_DEBUG"] = os.environ["DOCUMENT_OCR_DEBUG"]
        process = subprocess.Popen(
            [_python_path(), _worker_path()],
            cwd=str(Path(_worker_path()).parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self._process = process
        threading.Thread(target=self._pump_stdout, args=(process,), daemon=True).start()
        threading.Thread(target=self._pump_stderr, args=(process,), daemon=True).start()
        logger.info("Started OCR worker pid=%s", process.pid)
        return process

    def _pump_stdout(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if line:
                self._lines.put(line)
        self._lines.put(None)

    def _pump_stderr(self, process: subprocess.Popen[str]) -> None:
        assert process.stderr is not None
        for raw in process.stderr:
            message = raw.strip()
            if message:
                logger.debug("[ocr-worker] %s", message[:800])

    def _drain_queue(self) -> None:
        try:
            while True:
                self._lines.get_nowait()
        except queue.Empty:
            pass

    def _kill(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self._drain_queue()


_client = _OcrClient()


def extract(input_path: Path, output_path: Path, profile: str = "mobile") -> OcrResult:
    """Run one OCR job through the shared worker."""

    return _client.extract(input_path, output_path, profile)
