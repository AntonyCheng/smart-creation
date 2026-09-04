"""Shared helpers for project source materials.

Extension policy, upload-time anydoc extraction, and the workspace-bounded
path resolver live here so both the API upload path (``api.main``) and the
runner's async extraction task (``worker.document.extraction``) can import
them without pulling in the FastAPI application.

The async OCR fallback for scanned PDFs / images is layered on top of this
module in ``worker.document.extraction``; ``_extract_material`` below stays
as the synchronous best-effort path used for raw text and as the degraded
fallback when the job queue is unreachable.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import anydoc

from .config import get_settings
from .models import Project, ProjectMaterial

logger = logging.getLogger(__name__)
_settings = get_settings()

# Every extension the upload endpoint accepts.
_MATERIAL_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".docm",
    ".ppt", ".pps", ".pot", ".pptx", ".pptm", ".ppsx", ".ppsm",
    ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".odt", ".ods", ".odp",
    ".rtf", ".epub", ".csv",
    ".txt", ".md", ".markdown",
    ".png", ".jpg", ".jpeg", ".webp",
}
# Document formats delegated to the bundled anydoc converter. It detects the
# format from file content, so legacy (.doc/.xls/.ppt) and mislabeled office
# files still parse, and PDF/RTF/EPUB/ODF gain upload-time excerpts.
_ANYDOC_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".docm",
    ".ppt", ".pps", ".pot", ".pptx", ".pptm", ".ppsx", ".ppsm",
    ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".odt", ".ods", ".odp",
    ".rtf", ".epub", ".csv",
}
_MATERIAL_RAW_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
_MATERIAL_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_MATERIAL_MAX_BYTES = 100 * 1024 * 1024
_MATERIAL_PREVIEW_LIMIT = 12_000
_MATERIAL_SIDECAR_SUFFIX = ".extracted.md"


def _material_text_preview(text: str) -> tuple[str, int]:
    """Collapse inline whitespace but keep line structure for model context."""

    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    normalized = "\n".join(line for line in lines if line)
    return normalized[:_MATERIAL_PREVIEW_LIMIT], len(normalized)


def _read_material_markdown(path: Path, suffix: str) -> str:
    """Return the full extracted Markdown for one stored material."""

    if suffix in _MATERIAL_RAW_TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    return anydoc.to_markdown(str(path))


def _material_sidecar_path(material_path: Path) -> Path:
    """Resolve the pre-extracted Markdown twin stored beside one material."""

    return material_path.with_suffix(_MATERIAL_SIDECAR_SUFFIX)


def _extract_material(path: Path, suffix: str) -> dict[str, object]:
    """Extract upload-time context via anydoc; extraction never fails an upload.

    A successful document extraction also stores the full Markdown beside the
    original file so generation jobs can read it instead of re-converting.

    Scanned PDFs and images are handled by the async OCR pipeline in
    ``worker.document.extraction``; this synchronous path only covers raw text
    and the anydoc happy path, and degrades to ``parse_status="failed"`` for
    anything that needs OCR.
    """

    if suffix not in _ANYDOC_EXTENSIONS and suffix not in _MATERIAL_RAW_TEXT_EXTENSIONS:
        # Images and unknown reference-only attachments keep the original file.
        return {
            "parse_mode": "deferred",
            "parse_status": "deferred",
            "parse_message": "该格式保留原文件，生成任务启动时解析。",
        }
    try:
        text = _read_material_markdown(path, suffix)
    except Exception as exc:  # noqa: BLE001 - conversion errors degrade to deferred
        logger.warning("Material preview extraction failed for %s: %s", path.name, exc)
        encrypted = "encrypted" in type(exc).__name__.lower()
        return {
            "parse_mode": "deferred",
            "parse_status": "failed",
            "parse_message": (
                "文件已加密或设有打开密码，无法提取内容摘要，生成任务也无法读取该文件。"
                if encrypted
                else "摘要提取未完成，生成任务仍会读取原文件。"
            ),
        }
    preview, extracted_chars = _material_text_preview(text)
    if not preview:
        return {
            "parse_mode": "inline",
            "parse_status": "empty",
            "extracted_chars": 0,
            "parse_message": "未提取到可检索文本，生成任务仍会读取原文件。",
        }
    metadata: dict[str, object] = {
        "parse_mode": "inline",
        "parse_status": "ready",
        "extracted_chars": extracted_chars,
        "text_excerpt": preview,
        "parse_message": "已提取文本摘要，将参与需求、大纲和页面生成。",
    }
    if suffix in _ANYDOC_EXTENSIONS:
        sidecar_path = _material_sidecar_path(path)
        try:
            sidecar_path.write_text(text, encoding="utf-8")
            metadata["extracted_md_path"] = f"materials/{sidecar_path.name}"
        except OSError as exc:
            logger.warning("Material sidecar write failed for %s: %s", path.name, exc)
    return metadata


def _material_path(project: Project, material: ProjectMaterial) -> Path:
    """Resolve a project material while preserving the project workspace boundary."""

    root = _settings.workspace_root.resolve()
    project_root = (root / project.workspace_relpath).resolve()
    if root not in project_root.parents:
        raise RuntimeError("项目工作区越出数据根目录")
    path = (project_root / material.relative_path).resolve()
    if project_root not in path.parents:
        raise RuntimeError("Project material is outside WORKSPACE_ROOT")
    return path
