"""Run the deterministic PPTX-to-template import inside the agent runtime."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from pathlib import Path

from worker.runtime import install_opencode_config, opencode_idle_timeout_seconds, run_command

WORKSPACE = Path(os.environ.get("PPTMASTER_WORKSPACE", "/workspace/template"))
SKILL_ROOT = Path("/app/skills/ppt-master")

# Diagnostic codes emitted by pptx_to_svg's tolerant import. Codes ending in
# "-normalized" record benign auto-corrections; everything else is a fidelity
# loss the user should see in the template detail panel.
_DIAGNOSTIC_LABELS = {
    "animation-not-reconstructed": "动画效果未还原",
    "background-omitted": "页面背景未能还原",
    "chart-series-data-labels-omitted": "图表数据标签未还原",
    "effect-omitted": "阴影等特效未还原",
    "effect-unsupported": "特效不受支持已降级",
    "embedded-fonts-omitted": "嵌入字体未生效",
    "fill-omitted": "填充效果未还原",
    "formula-not-reconstructed": "公式未能还原",
    "group-fill-omitted": "组合填充未还原",
    "hyperlink-omitted": "超链接未保留",
    "image-effect-omitted": "图片特效未还原",
    "image-fill-omitted": "图片填充未还原",
    "linked-image-proxy": "外链图片以降级方式呈现",
    "nested-crop-shape-clip-omitted": "嵌套裁剪未还原",
    "object-replaced": "部分对象以降级形式呈现",
    "preview-omitted": "部分预览内容省略",
    "shape-style-omitted": "形状样式未完整还原",
    "stroke-omitted": "边框样式未还原",
    "text-omitted": "部分文本未还原",
    "theme-background-reference-omitted": "主题背景引用未还原",
    "transition-not-reconstructed": "切换效果未还原",
}
_NORMALIZATION_LABELS = {
    "chart-data-labels-normalized": "图表数据标签已规范化",
    "chart-series-style-normalized": "图表系列样式已规范化",
    "color-structure-normalized": "颜色结构已规范化",
    "combo-series-indices-normalized": "组合图系列索引已规范化",
    "gradient-rotation-normalized": "渐变旋转已规范化",
    "gradient-scaling-normalized": "渐变缩放已规范化",
    "gradient-stop-order-normalized": "渐变停靠点顺序已规范化",
    "gradient-tile-rect-normalized": "渐变平铺矩形已规范化",
    "path-gradient-focus-normalized": "路径渐变焦点已规范化",
    "theme-color-map-normalized": "主题颜色映射已规范化",
    "theme-color-scheme-normalized": "主题配色方案已规范化",
    "vector-custom-geometry-crop-normalized": "自定义几何裁剪已规范化",
}


def _diagnostic_label(code: str) -> str:
    if code in _DIAGNOSTIC_LABELS:
        return _DIAGNOSTIC_LABELS[code]
    if code in _NORMALIZATION_LABELS:
        return _NORMALIZATION_LABELS[code]
    if code.endswith("-normalized"):
        return f"{code}（已自动修正）"
    return code


def _build_import_report(import_root: Path, manifest: dict) -> dict:
    """Summarize tolerant-import diagnostics and placeholders for the UI."""

    report: dict[str, Any] = {}
    report_path = import_root / "validation" / "conversion-report.json"
    try:
        conversion = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        conversion = {}
    except (OSError, json.JSONDecodeError):
        conversion = {}
    diagnostics = conversion.get("diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = []
    losses: dict[str, dict[str, Any]] = {}
    normalizations: dict[str, dict[str, Any]] = {}
    affected_slides: set[int] = set()
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "unknown")
        severity = str(item.get("severity") or "warning").lower()
        bucket = normalizations if code.endswith("-normalized") else losses
        entry = bucket.setdefault(code, {"label": _diagnostic_label(code), "count": 0, "sample": ""})
        entry["count"] += 1
        if not entry["sample"]:
            message = item.get("message")
            if isinstance(message, str) and message:
                entry["sample"] = message
        slide_index = item.get("slide_index")
        if isinstance(slide_index, int) and slide_index >= 0:
            affected_slides.add(slide_index)
    report["warning_count"] = len(diagnostics)
    report["losses"] = dict(sorted(losses.items()))
    report["normalizations"] = dict(sorted(normalizations.items()))
    report["slides_affected"] = sorted(affected_slides)
    placeholders: dict[str, int] = {}
    placeholder_types: dict[str, int] = {}
    pages = manifest.get("slides") or manifest.get("pages") or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        for placeholder in page.get("placeholders") or []:
            if not isinstance(placeholder, dict):
                continue
            role = str(placeholder.get("semanticRole") or "unknown")
            placeholders[role] = placeholders.get(role, 0) + 1
            kind = str(placeholder.get("type") or "unknown")
            placeholder_types[kind] = placeholder_types.get(kind, 0) + 1
    report["placeholders"] = {"total": sum(placeholders.values()), "by_semantic_role": placeholders, "by_type": placeholder_types}
    return report


def _emit_progress(stage: str, message: str) -> None:
    print(json.dumps({"type": "progress", "stage": stage, "message": message}, ensure_ascii=False), flush=True)


def _run_step(stage: str, message: str, command: list[str]) -> None:
    """Run one import step and expose its lifecycle to the trusted runner."""

    _emit_progress(stage, message)
    result = subprocess.run(command, cwd=SKILL_ROOT, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr[-3000:] or result.stdout[-3000:] or "步骤执行失败"
        raise RuntimeError(detail)
    _emit_progress(stage, f"{message}完成")


def _first_color(theme: dict) -> str:
    values = theme.get("colors", theme.get("themeColors", []))
    if isinstance(values, dict):
        values = list(values.values())
    if not isinstance(values, (list, tuple)):
        return "#0F766E"
    for value in values:
        candidate = str(value).lstrip("#")
        if len(candidate) == 6 and all(char in "0123456789abcdefABCDEF" for char in candidate):
            return f"#{candidate.upper()}"
    return "#0F766E"


def _run_render(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=SKILL_ROOT, capture_output=True, text=True)


def _render_preview_pngs(template_root: Path) -> list[str]:
    """Render each materialized template SVG to PNG so browser previews are
    pixel-faithful (SVG references like ../images are not resolvable inside a
    browser <img> tag, but LibreOffice renders them from disk)."""

    svg_dir = template_root / "templates"
    preview_dir = template_root / "preview"
    svg_paths = sorted(
        path for path in svg_dir.glob("*.svg") if re.match(r"^\d{3}_", path.name)
    )
    if not svg_paths:
        return []
    preview_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = Path(tempfile.mkdtemp(prefix="pptmaster-preview-"))
    try:
        result = _run_render(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir)]
            + [str(path) for path in svg_paths]
        )
        if result.returncode != 0:
            detail = result.stderr[-1000:] or result.stdout[-1000:]
            raise RuntimeError(f"预览渲染失败: {detail}")
        rendered: list[str] = []
        for index, svg_path in enumerate(svg_paths, start=1):
            pdf_path = pdf_dir / f"{svg_path.stem}.pdf"
            if not pdf_path.is_file():
                continue
            png_name = svg_path.stem + ".png"
            png_path = preview_dir / png_name
            ppm_result = _run_render(
                ["pdftoppm", "-png", "-r", "96", "-singlefile", str(pdf_path), str(png_path.with_suffix(""))]
            )
            if ppm_result.returncode != 0 or not png_path.is_file():
                continue
            rendered.append((preview_dir / png_name).relative_to(WORKSPACE).as_posix())
        return rendered
    finally:
        shutil.rmtree(pdf_dir, ignore_errors=True)


def _write_template_spec(template_root: Path, manifest: dict, page_count: int) -> None:
    """Create the minimum portable Deck contract without semantic AI inference."""

    theme = manifest.get("theme") if isinstance(manifest.get("theme"), dict) else {}
    primary_color = _first_color(theme)
    roster = "\n".join(
        f"- {index:03d}: imported source slide {index}; preserve its visual structure as a reusable template."
        for index in range(1, page_count + 1)
    ) or "- No slides were recovered from the source PPTX."
    content = f'''---
deck_id: imported-template
kind: deck
category: general
summary: Imported presentation template for personal use
keywords: [imported, presentation, template]
primary_color: "{primary_color}"
canvas_format: ppt169
canvas_width: 1280
canvas_height: 720
canvas_viewbox: "0 0 1280 720"
replication_mode: mirror
native_structure_mode: structured
page_count: {page_count}
---

# Imported Presentation Template - Design Specification

## I. Template Overview

This is a structure-preserving import of the uploaded presentation. The source identity,
page grammar, and native Master/Layout relationships are retained for reuse.

## II. Color Scheme

Primary imported color: `{primary_color}`.

## III. Typography

Typography is retained from the source package for consistent downstream generation.

## IV. Signature Design Elements

Source decorations, imagery, and layout families are preserved in the imported SVG roster.

## V. Page Roster

{roster}
'''
    (template_root / "templates" / "design_spec.md").write_text(content, encoding="utf-8")


def _run_semantic_template_review(template_root: Path, import_root: Path, manifest: dict) -> bool:
    """Ask the bounded agent to turn imported evidence into a reusable Deck spec."""

    spec_path = template_root / "templates" / "design_spec.md"
    authoring_summary = import_root / "authoring-svg" / "authoring_summary.json"
    conversion_report = import_root / "validation" / "conversion-report.json"
    page_candidates = manifest.get("pageTypeCandidates") or {}
    prompt = f"""You are reviewing an imported PowerPoint template workspace.

Read the evidence files at {authoring_summary}, {conversion_report}, and the
source manifest at {import_root / 'manifest.json'}. Read the materialized SVG
prototypes under {template_root / 'templates'} as needed. Do not edit, rename,
copy, or delete any SVG, image, native payload, or machine manifest. Do not
invent visual facts that are not supported by the evidence.

Rewrite only {spec_path} as a complete, reusable Deck Design Specification.
The file must be UTF-8 Markdown with YAML frontmatter and these fields:
deck_id, kind: deck, category: general, summary, keywords, primary_color,
canvas_format, canvas_width, canvas_height, canvas_viewbox, replication_mode:
mirror, native_structure_mode: structured, and page_count: {len(manifest.get('slides') or [])}.
Include sections I. Template Overview, II. Color Scheme, III. Typography,
IV. Signature Design Elements, V. Page Roster, VI. Assets, and VII. Placeholder
Overrides when evidence supports them. Page Roster must contain one entry for
every numbered SVG and describe its source page role, visual grammar, reusable
slots, and capacity without prescribing future content. Include the preserved
Master/Layout relationship and clearly distinguish native objects or
placeholders that were downgraded according to the conversion report. Add
practical placeholder rebuild suggestions in section VII, but label them as
suggestions rather than claiming the import already rebuilt them.

Use Chinese prose for the specification because this platform's template
review UI is Chinese. Keep machine keys and required frontmatter values exact.
The importer classified page candidates as {json.dumps(page_candidates, ensure_ascii=False)}.
After writing the file, stop; do not run export or validation commands.
"""
    if not install_opencode_config():
        return False
    return_code = run_command(
        ["opencode", "run", "--format", "json", prompt],
        idle_timeout_seconds=opencode_idle_timeout_seconds(),
    )
    return return_code == 0 and spec_path.is_file() and spec_path.stat().st_size > 200


def main() -> int:
    source = WORKSPACE / "source.pptx"
    import_root = WORKSPACE / "import"
    template_root = WORKSPACE / "deck"
    if not source.is_file():
        raise RuntimeError("上传的 PPTX 文件不存在")
    if import_root.exists():
        shutil.rmtree(import_root)
    if template_root.exists():
        shutil.rmtree(template_root)
    command = [
        sys.executable,
        str(SKILL_ROOT / "scripts/pptx_template_import.py"),
        str(source),
        "--output",
        str(import_root),
        "--inheritance-mode",
        "both",
    ]
    _run_step("extracting", "正在读取页面、母版和主题信息", command)
    _run_step(
        "authoring_view",
        "正在准备可编辑的模板结构",
        [
            sys.executable,
            str(SKILL_ROOT / "scripts/svg_authoring_view.py"),
            str(import_root / "svg"),
            "-o",
            str(import_root / "authoring-svg"),
            "--projection-kind",
            "layered",
        ],
    )
    # Materialization touches each imported SVG and native payload repeatedly.
    # Work on the container-local tmpfs to avoid Windows bind-mount metadata latency.
    with tempfile.TemporaryDirectory(prefix="pptmaster-template-") as temporary:
        local_root = Path(temporary)
        local_import = local_root / "import"
        local_template = local_root / "deck"
        _emit_progress("materializing", "正在生成可复用模板")
        shutil.copytree(import_root, local_import)
        result = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts/mirror_template_materialize.py"),
                str(local_import),
                str(local_template),
            ],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = result.stderr[-3000:] or result.stdout[-3000:] or "模板物化失败"
            raise RuntimeError(detail)
        shutil.copytree(local_template, template_root)
        _emit_progress("materializing", "正在生成可复用模板完成")
    _emit_progress("summarizing", "正在整理模板页数、配色和字体摘要")
    manifest = json.loads((import_root / "manifest.json").read_text(encoding="utf-8"))
    pages = manifest.get("slides") or manifest.get("pages") or []
    theme = manifest.get("theme") or {}
    fonts = manifest.get("fonts") or []
    _write_template_spec(template_root, manifest, len(pages))
    _emit_progress("semantic_review", "正在根据导入证据整理模板语义规范")
    try:
        reviewed = _run_semantic_template_review(template_root, import_root, manifest)
    except (OSError, RuntimeError, ValueError) as exc:
        reviewed = False
        _emit_progress("semantic_review", f"语义整理失败，保留基础规范: {exc}")
    if not reviewed:
        _emit_progress("semantic_review", "语义整理未完成，已保留基础规范")
    preview_files = sorted(
        str(path.relative_to(WORKSPACE))
        for path in template_root.glob("templates/*.svg")
        if re.match(r"^\d{3}_.*\.svg$", path.name)
    )
    _emit_progress("preview", "正在生成页面预览图")
    try:
        preview_files_png = _render_preview_pngs(template_root)
    except (RuntimeError, OSError) as exc:
        # Previews are an enhancement; a renderer hiccup must not fail the import.
        _emit_progress("preview", f"预览图生成失败，已跳过: {exc}")
        preview_files_png = []
    import_report = _build_import_report(import_root, manifest)
    return_data = {
        "page_count": len(pages),
        "preview_files": preview_files,
        "preview_files_png": preview_files_png,
        "import_report": import_report,
        "template_root": "deck",
        "colors": theme.get("colors", theme.get("themeColors", [])) if isinstance(theme, dict) else [],
        "fonts": fonts,
        "source_manifest": "import/manifest.json",
    }
    print(json.dumps({"type": "result", "summary": return_data}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
