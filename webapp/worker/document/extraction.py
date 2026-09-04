"""Async source-material extraction with a Chinese OCR fallback.

The ``runner.extract_material`` Celery task calls :func:`extract_material`.
It mirrors the kLeagl ``DocumentExtractionService.extract`` pipeline:

* raw text (.txt/.md/.markdown)  -> read directly, no OCR
* image (.png/.jpg/.jpeg/.webp)  -> OCR; an empty result is not a failure
* everything else                -> ``anydoc.to_markdown``; a scanned PDF
  (``NeedsOcrError``, an unreadable PDF, or a PDF whose text layer is
  essentially empty) falls back to OCR

Extraction never raises out of the task: a material always lands on a
terminal ``status`` so the frontend poll stops.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import anydoc
from anydoc import EncryptedError, NeedsOcrError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.config import get_settings
from api.materials import (
    _MATERIAL_IMAGE_EXTENSIONS,
    _MATERIAL_RAW_TEXT_EXTENSIONS,
    _material_path,
    _material_sidecar_path,
    _material_text_preview,
)
from api.models import Project, ProjectMaterial

from . import ocr_client
from .ocr_client import OcrError, OcrResult

logger = logging.getLogger(__name__)

_settings = get_settings()
_engine = create_engine(_settings.sync_database_url, pool_pre_ping=True)
_Session = sessionmaker(_engine, expire_on_commit=False)

_FALLBACK_MESSAGE = "摘要提取未完成，生成任务仍会读取原文件。"


def extract_material(material_id: str) -> None:
    """Extract one uploaded material and persist its parse result."""

    with _Session() as db:
        material = db.get(ProjectMaterial, UUID(material_id))
        if material is None:
            return
        project = db.get(Project, material.project_id)
        if project is None:
            return

        suffix = Path(material.original_filename).suffix.lower()
        if not suffix:
            suffix = str((material.meta or {}).get("extension") or "").lower()

        # Heartbeat: a fresh updated_at tells the API this parse is live, so a
        # material queued behind others is not mistaken for a stalled job.
        material.updated_at = datetime.now(UTC)
        db.commit()

        try:
            path = _material_path(project, material)
        except RuntimeError:
            _persist(db, material, {
                "parse_mode": "deferred",
                "parse_status": "failed",
                "parse_message": "材料路径无效，无法解析。",
            })
            return
        if not path.is_file():
            _persist(db, material, {
                "parse_mode": "deferred",
                "parse_status": "failed",
                "parse_message": "上传文件不存在，无法解析。",
            })
            return

        try:
            result = _extract(path, suffix)
        except Exception:  # noqa: BLE001 - extraction never fails the task
            logger.exception("Material %s extraction crashed", material.id)
            result = {
                "parse_mode": "deferred",
                "parse_status": "failed",
                "parse_message": _FALLBACK_MESSAGE,
            }
        _persist(db, material, result)


_PARSE_KEYS = (
    "parse_message", "text_excerpt", "extracted_md_path", "extracted_chars",
    "ocr", "ocr_confidence", "page_count", "warnings",
)


def _persist(db, material: ProjectMaterial, result: dict[str, object]) -> None:
    meta = dict(material.meta or {})
    for key in _PARSE_KEYS:
        meta.pop(key, None)
    meta.update(result)
    material.meta = meta
    material.status = "failed" if meta.get("parse_status") in {"failed", "encrypted"} else "ready"
    material.updated_at = datetime.now(UTC)
    db.commit()


def _extract(path: Path, suffix: str) -> dict[str, object]:
    if suffix in _MATERIAL_RAW_TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        return _finalize(text, path, suffix, ocr=False)

    if suffix in _MATERIAL_IMAGE_EXTENSIONS:
        return _extract_image(path, suffix)

    try:
        text = anydoc.to_markdown(str(path))
    except NeedsOcrError:
        if suffix != ".pdf":
            return {
                "parse_mode": "deferred",
                "parse_status": "failed",
                "parse_message": "该文件需要 OCR 识别，暂不支持，生成任务仍会读取原文件。",
            }
        return _pdf_ocr(path, suffix, "PDF 无可用文本层，已使用中文 OCR")
    except EncryptedError:
        return {
            "parse_mode": "deferred",
            "parse_status": "encrypted",
            "parse_message": "文件已加密或设有打开密码，无法提取内容摘要，生成任务也无法读取该文件。",
        }
    except Exception as exc:  # noqa: BLE001 - unreadable container -> try OCR for PDFs
        logger.warning("anydoc failed for %s: %s", path.name, exc)
        if suffix == ".pdf" and ocr_client.ocr_available():
            ocr_meta = _pdf_ocr(path, suffix, "PDF 无可用文本层，已使用中文 OCR", quiet=True)
            if ocr_meta is not None:
                return ocr_meta
        return {
            "parse_mode": "deferred",
            "parse_status": "failed",
            "parse_message": _FALLBACK_MESSAGE,
        }

    if suffix == ".pdf" and _meaningful_len(text) < 50 and ocr_client.ocr_available():
        ocr_meta = _pdf_ocr(
            path, suffix, "PDF 文本层内容不足，已切换中文 OCR", quiet=True, better_than=text
        )
        if ocr_meta is not None:
            return ocr_meta
    return _finalize(text, path, suffix, ocr=False)


def _extract_image(path: Path, suffix: str) -> dict[str, object]:
    reference_meta = {
        "parse_mode": "deferred",
        "parse_status": "deferred",
        "parse_message": "图片保留原文件，生成任务可作为素材使用。",
    }
    if not ocr_client.ocr_available():
        return reference_meta
    try:
        result = _adaptive_ocr(path, _material_sidecar_path(path))
    except OcrError as exc:
        logger.warning("image OCR failed for %s: %s", path.name, exc)
        return {**reference_meta, "parse_message": "图片保留原文件（未识别出文字），生成任务可作为素材使用。"}
    text = _read_sidecar(path)
    if not text.strip():
        _material_sidecar_path(path).unlink(missing_ok=True)
        return {
            "parse_mode": "deferred",
            "parse_status": "empty",
            "extracted_chars": 0,
            "ocr": True,
            "parse_message": "图片未识别出文字，已作为素材保留。",
        }
    return _finalize(text, path, suffix, ocr=True, ocr_result=result, sidecar_written=True)


def _pdf_ocr(
    path: Path,
    suffix: str,
    warning: str,
    *,
    quiet: bool = False,
    better_than: str | None = None,
) -> dict[str, object] | None:
    """Run OCR on a PDF. Returns ``None`` when OCR is unavailable and ``quiet``."""

    try:
        result = _adaptive_ocr(path, _material_sidecar_path(path), warning=warning)
    except OcrError as exc:
        if quiet:
            logger.warning("PDF OCR fallback unavailable for %s: %s", path.name, exc)
            return None
        return _ocr_unavailable_meta(exc)
    text = _read_sidecar(path)
    if better_than is not None and _meaningful_len(text) <= _meaningful_len(better_than):
        # OCR did not beat the thin text layer; keep anydoc's output.
        _material_sidecar_path(path).unlink(missing_ok=True)
        return None
    return _finalize(text, path, suffix, ocr=True, ocr_result=result, sidecar_written=True)


def _adaptive_ocr(input_path: Path, out_path: Path, *, warning: str | None = None) -> OcrResult:
    """mobile -> escalate to server on low confidence -> flag if still low."""

    result = ocr_client.extract(input_path, out_path, "mobile")
    warnings: list[str] = list(result.warnings)
    if warning:
        warnings.insert(0, warning)

    if (
        result.average_confidence is not None
        and result.average_confidence < 0.65
        and ocr_client.server_profile_enabled()
    ):
        try:
            escalated = ocr_client.extract(input_path, out_path, "server")
            warnings = [
                "移动版 OCR 置信度过低，已升级为高精度中文识别模型",
                *warnings,
                *escalated.warnings,
            ]
            result = escalated
        except OcrError as exc:
            logger.warning("server-profile OCR failed for %s: %s", input_path.name, exc)
            warnings.append("高精度 OCR 模型不可用，已保留移动版结果")

    if result.average_confidence is not None and result.average_confidence < 0.75:
        warnings.append(
            f"OCR 平均置信度较低（{round(result.average_confidence * 100)}%），关键内容需对照原件"
        )
    result.warnings = warnings
    return result


def _finalize(
    text: str,
    path: Path,
    suffix: str,
    *,
    ocr: bool,
    ocr_result: OcrResult | None = None,
    sidecar_written: bool = False,
) -> dict[str, object]:
    preview, extracted_chars = _material_text_preview(text)
    if not preview:
        if sidecar_written:
            _material_sidecar_path(path).unlink(missing_ok=True)
        return {
            "parse_mode": "deferred",
            "parse_status": "empty",
            "extracted_chars": 0,
            "parse_message": "未提取到可检索文本，生成任务仍会读取原文件。",
            **({"ocr": True} if ocr else {}),
        }

    meta: dict[str, object] = {
        "parse_mode": "inline",
        "parse_status": "ready",
        "extracted_chars": extracted_chars,
        "text_excerpt": preview,
        "parse_message": "已提取文本摘要，将参与需求、大纲和页面生成。",
    }
    if suffix not in _MATERIAL_RAW_TEXT_EXTENSIONS:
        sidecar = _material_sidecar_path(path)
        try:
            if not sidecar_written:
                sidecar.write_text(text, encoding="utf-8")
            meta["extracted_md_path"] = f"materials/{sidecar.name}"
        except OSError as exc:
            logger.warning("Material sidecar write failed for %s: %s", path.name, exc)

    if ocr:
        meta["ocr"] = True
        if ocr_result is not None:
            if ocr_result.page_count:
                meta["page_count"] = ocr_result.page_count
            if ocr_result.average_confidence is not None:
                meta["ocr_confidence"] = round(ocr_result.average_confidence, 4)
            if ocr_result.warnings:
                meta["warnings"] = list(ocr_result.warnings)
        low_confidence = (
            ocr_result is not None
            and ocr_result.average_confidence is not None
            and ocr_result.average_confidence < 0.75
        )
        if low_confidence:
            meta["parse_status"] = "partial"
            meta["parse_message"] = "已通过 OCR 识别文字，但置信度较低，建议核对原件。"
        else:
            meta["parse_message"] = "已通过 OCR 识别文字，将参与需求、大纲和页面生成。"
    return meta


def _ocr_unavailable_meta(exc: OcrError) -> dict[str, object]:
    if exc.code in {"OCR_UNAVAILABLE", "OCR_DEPENDENCY_MISSING"}:
        message = "该文件需要中文 OCR，但本地 OCR 运行时尚未就绪，生成任务仍会读取原文件。"
    elif exc.code == "OCR_TIMEOUT":
        message = "OCR 处理超时，生成任务仍会读取原文件。"
    else:
        message = "OCR 识别未完成，生成任务仍会读取原文件。"
    return {
        "parse_mode": "deferred",
        "parse_status": "failed",
        "parse_message": message,
        "ocr": True,
    }


def _read_sidecar(path: Path) -> str:
    sidecar = _material_sidecar_path(path)
    try:
        return sidecar.read_text(encoding="utf-8")
    except OSError:
        return ""


def _meaningful_len(value: str) -> int:
    return len(re.sub(r"[^\w]", "", value, flags=re.UNICODE))
