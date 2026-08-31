"""Gongwen (official-document) skill adapter.

Contract with the skill (see webapp/docs/platform/skill-contract.md): the
skill writes its draft through ``scripts/prepare_draft.py`` into
``output_root`` configured via ``GONGWEN_RUNTIME_CONFIG`` (the driver injects
it from the manifest), the platform renders a faithful page preview with
LibreOffice + the skill's bundled GB/T fonts, and validation checks the
deliverable shape. The skill itself owns GB/T formatting rules.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from worker.adapters.base import AdapterError, SkillContext
from worker.runtime import WORKSPACE, emit

AUTHORING_ROOT_NAME = "gongwen-project"
DEFAULT_MIN_CHARS = 200
RUNTIME_CONFIG_NAME = "gongwen-runtime.json"
# Self-generated or host-provisioned files that must never count as a
# continuation change.
_SNAPSHOT_EXCLUDES = {"validation", "font-cache", RUNTIME_CONFIG_NAME, "fontconfig.conf"}


def job_project_workspace(continue_mode: bool = False) -> Path:
    """Legacy naming when the runner predates the manifest contract."""

    return WORKSPACE / AUTHORING_ROOT_NAME


def init_command(ctx: SkillContext) -> list[str] | None:
    """Scaffold the authoring root and write its runtime.json via the skill."""

    bootstrap = f"""import pathlib, runpy, sys
root = pathlib.Path(sys.argv[1])
for name in ('drafts', 'exports', 'preview', 'validation'):
    (root / name).mkdir(parents=True, exist_ok=True)
sys.argv = ['setup_local.py', '--output', str(root / 'exports'), '--config', str(root / {RUNTIME_CONFIG_NAME!r})]
runpy.run_path('skills/gongwen/scripts/setup_local.py', run_name='__main__')
"""
    # Scaffold the authoring root itself (not the job root) so the runner's
    # marker-based authoring-root detection lands on exactly one candidate.
    return [sys.executable, "-c", bootstrap, str(ctx.workspace)]


def continue_workspace_error(ctx: SkillContext) -> str | None:
    return None


def verify_project_workspace(ctx: SkillContext) -> bool:
    """Reject jobs whose authoring root or exports directory vanished."""

    project_workspace = ctx.workspace
    if not project_workspace.is_dir() or not (project_workspace / "exports").is_dir():
        emit("error", message=f"工作区不可用：{project_workspace}")
        return False
    return True


def _snapshot_excluded(relative: Path) -> bool:
    parts = relative.parts
    return any(part in _SNAPSHOT_EXCLUDES for part in parts)


def baseline_snapshot(ctx: SkillContext) -> dict[str, str]:
    import hashlib

    snapshot: dict[str, str] = {}
    for path in sorted(ctx.workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ctx.workspace)
        # validation/ and the rendered-preview cache are written by this
        # adapter or the renderer; including them would make every
        # continuation look "changed" through self-generated files alone.
        if _snapshot_excluded(relative):
            continue
        snapshot[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _latest_docx(workspace: Path) -> Path | None:
    exports = sorted(
        (path for path in (workspace / "exports").rglob("*.docx") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    return exports[-1] if exports else None


def emit_artifacts(ctx: SkillContext) -> None:
    docx = _latest_docx(ctx.workspace)
    if docx is not None:
        emit("artifact", kind="docx", path=docx.relative_to(ctx.workspace).as_posix())
    for pdf in sorted((ctx.workspace / "exports").glob("*.pdf")):
        emit("artifact", kind="pdf", path=f"exports/{pdf.name}")
    preview_root = ctx.workspace / "preview"
    if preview_root.is_dir():
        for png in sorted(preview_root.glob("*.png")):
            emit("artifact", kind="png", path=f"preview/{png.name}")


def validate_revision(ctx: SkillContext, baseline: dict[str, str]) -> dict[str, object]:
    """Check the exported docx opens, carries text, and changed for continuations."""

    docx = _latest_docx(ctx.workspace)
    issues: list[str] = []
    char_count = 0
    if docx is not None:
        char_count = _docx_char_count(docx)
        if char_count <= 0:
            issues.append("DOCX 无法打开或没有可提取的正文文本")
    else:
        issues.append("exports/ 目录下没有生成 .docx 交付文件")
    manifest_validation = (ctx.manifest or {}).get("validation") or {}
    min_chars = int(manifest_validation.get("min_chars") or DEFAULT_MIN_CHARS)
    if docx is not None and char_count < min_chars:
        issues.append(f"正文内容过短（{char_count} 字符，要求不少于 {min_chars}）")
    current = baseline_snapshot(ctx)
    changed = sorted(path for path in set(baseline) | set(current) if baseline.get(path) != current.get(path))
    if ctx.continue_mode and not changed:
        issues.append("继续生成未产生任何文件变化")
    validation_type = "继续生成" if ctx.continue_mode else "生成"
    passed = not issues
    result = {
        "passed": passed,
        "continuation": ctx.continue_mode,
        "changed_files": changed,
        "char_count": char_count,
        "deliverable": docx.relative_to(ctx.workspace).as_posix() if docx else "",
        "checks": [],
        "message": f"{validation_type}校验通过" if passed else f"{validation_type}未生效：{'；'.join(issues)}",
    }
    (ctx.workspace / "validation").mkdir(parents=True, exist_ok=True)
    (ctx.workspace / "validation" / "change_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def finalize(ctx: SkillContext) -> None:
    """Render the deliverable to PDF and per-page PNGs with the skill's fonts."""

    docx = _latest_docx(ctx.workspace)
    if docx is None:
        return
    environment = dict(os.environ)
    fontconfig_file = _runtime_fontconfig(ctx.workspace)
    if fontconfig_file:
        environment["FONTCONFIG_FILE"] = str(fontconfig_file)
    exports = ctx.workspace / "exports"
    emit("log", text="正在渲染排版预览（LibreOffice + 公文字体）")
    convert = subprocess.run(
        [
            "soffice", "--headless", "--norestore", "--convert-to", "pdf",
            "--outdir", str(exports), str(docx),
        ],
        env=environment,
        cwd=str(ctx.workspace),
        capture_output=True,
        text=True,
        timeout=600,
    )
    pdf = exports / f"{docx.stem}.pdf"
    if convert.returncode != 0 or not pdf.is_file():
        emit("log", text=f"PDF 渲染未完成，跳过逐页预览：{(convert.stderr or convert.stdout)[-300:]}")
        return
    preview_root = ctx.workspace / "preview"
    preview_root.mkdir(parents=True, exist_ok=True)
    render = subprocess.run(
        ["pdftoppm", "-png", "-r", "110", str(pdf), str(preview_root / "page")],
        env=environment,
        cwd=str(ctx.workspace),
        capture_output=True,
        text=True,
        timeout=600,
    )
    rendered = len(list(preview_root.glob("*.png"))) if preview_root.is_dir() else 0
    if render.returncode != 0 or rendered == 0:
        emit("log", text=f"逐页预览渲染未完成：{(render.stderr or render.stdout)[-300:]}")
        return
    emit("log", text=f"排版预览已生成：{rendered} 页")


def prepare_template(ctx: SkillContext) -> str:
    if ctx.template_root:
        raise AdapterError("该创作类型不支持选择模板")
    return ""


def build_agent_prompt(ctx: SkillContext, template_instruction: str = "") -> str:
    del template_instruction
    workspace = ctx.workspace
    manifest_agent = (ctx.manifest or {}).get("agent") or {}
    entry_doc = str(manifest_agent.get("entry_doc") or "skills/gongwen/SKILL.md")
    if ctx.continue_mode:
        workspace_instruction = (
            "The workspace contains the last successful revision. Revise that existing document "
            "in place per the requested changes and preserve unaffected content."
        )
    else:
        workspace_instruction = "The Worker has already initialized the empty project workspace."
    return f"""You are executing one autonomous official-document drafting job.

Read and follow /app/{str((ctx.manifest or {}).get("agent", {}).get("repo_conventions_doc") or "AGENTS.md")} and the Skill entry /app/{entry_doc}.
Run fully autonomously: the requester is not available, so never ask questions. When a
required fact is missing, use an explicit placeholder (such as XX或待补) exactly as the
Skill permits, and list it in the review sheet. The runtime config for this job is already
prepared via GONGWEN_RUNTIME_CONFIG; do not create or modify runtime.json elsewhere.
The only project workspace is {workspace}; {workspace_instruction}
It is the immutable project root for this job. Do not move, rename, copy, or create another
project directory. Draft the document by following the Skill workflow and export the final
.docx through the Skill's prepare_draft step into {workspace}/exports.
This platform collects finished files automatically: do not call send_channel_file, do not
invent download links, and do not attempt any file delivery. Your final text (the review
sheet) is delivered to the user as-is.
Do not access files outside {WORKSPACE} except the installed Skill and its declared tools.

User request:
{ctx.prompt}
"""


def _runtime_fontconfig(workspace: Path) -> Path | None:
    config_path = workspace / RUNTIME_CONFIG_NAME
    try:
        settings = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    candidate = str(settings.get("fontconfig_file") or "")
    if candidate and Path(candidate).is_file():
        return Path(candidate)
    return None


def _docx_char_count(path: Path) -> int:
    """Return the visible text length of a docx, or 0 when unreadable."""

    try:
        import zipfile
        from xml.etree import ElementTree

        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        text = "".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
        return len("".join(text.split()))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return 0
