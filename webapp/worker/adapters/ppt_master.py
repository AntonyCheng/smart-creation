"""PPT-master skill adapter: workspace rules, revision validation, and prompt.

Logic here is migrated verbatim from the pre-manifest worker so ppt-master
behavior stays byte-identical; only the entry points changed shape.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile
from xml.etree import ElementTree

from worker.adapters.base import AdapterError, SkillContext
from worker.runtime import WORKSPACE, emit

AUTHORING_ROOT_NAME = "ppt-project"


def job_project_workspace(continue_mode: bool = False) -> Path:
    """Return the stable authoring root for this Job."""

    if continue_mode:
        return WORKSPACE / AUTHORING_ROOT_NAME
    return WORKSPACE / f"{AUTHORING_ROOT_NAME}_ppt169_{datetime.now():%Y%m%d}"


def init_command(ctx: SkillContext) -> list[str] | None:
    """Scaffold the empty PPT Master project workspace for a fresh job."""

    return [
        sys.executable,
        "skills/ppt-master/scripts/project_manager.py",
        "init",
        ctx.workspace.name,
        "--dir",
        str(WORKSPACE),
        "--format",
        "ppt169",
        "--quick-generate",
    ]


def continue_workspace_error(ctx: SkillContext) -> str | None:
    """Reject continuations whose target slide no longer exists."""

    if ctx.target_slide is not None and not _slide_paths(ctx.workspace, ctx.target_slide):
        return f"目标页面不存在：第 {ctx.target_slide} 页"
    return None


def verify_project_workspace(ctx: SkillContext) -> bool:
    """Reject jobs that moved or duplicated the Worker-initialized project root."""

    project_workspace = ctx.workspace
    if not project_workspace.is_dir() or not (project_workspace / "svg_output").is_dir():
        emit(
            "error",
            message=(
                "OpenCode 改变了受管项目目录，预期工作区不可用："
                f"{project_workspace}"
            ),
        )
        return False
    unexpected_roots = [
        path
        for path in WORKSPACE.iterdir()
        if path.is_dir()
        and path.resolve() != project_workspace.resolve()
        and (path / "svg_output").is_dir()
    ]
    if unexpected_roots:
        emit(
            "error",
            message=(
                "OpenCode 创建了未授权的第二项目目录："
                f"{', '.join(str(path) for path in unexpected_roots)}；"
                "任务产物必须保留在系统指定工作区。"
            ),
        )
        return False
    return True


def _snapshot(project_workspace: Path) -> dict[str, str]:
    """Hash authored SVG and exported PPTX files for deterministic comparison."""

    snapshot: dict[str, str] = {}
    for folder, pattern in (("svg_output", "*.svg"), ("exports", "*.pptx")):
        root = project_workspace / folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob(pattern)):
            # Keep manifest keys portable so local Windows checks match the Linux worker.
            snapshot[path.relative_to(project_workspace).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def baseline_snapshot(ctx: SkillContext) -> dict[str, str]:
    return _snapshot(ctx.workspace)


def emit_artifacts(ctx: SkillContext) -> None:
    project_workspace = ctx.workspace
    for svg in sorted((project_workspace / "svg_output").glob("*.svg")):
        emit("artifact", kind="svg", path=f"svg_output/{svg.name}")
    for pptx in sorted((project_workspace / "exports").glob("*.pptx")):
        emit("artifact", kind="pptx", path=f"exports/{pptx.name}")


def _slide_paths(project_workspace: Path, page_number: int | None) -> list[Path]:
    paths = sorted((project_workspace / "svg_output").glob("*.svg"))
    if page_number is None:
        return paths
    prefix = f"{page_number:02d}_"
    return [path for path in paths if path.name.startswith(prefix)]


def _pptx_slide_texts(project_workspace: Path, page_number: int | None) -> str:
    """Read editable DrawingML text from the latest exported PPTX."""

    exports = sorted((project_workspace / "exports").glob("*.pptx"), key=lambda path: path.stat().st_mtime)
    if not exports:
        return ""
    with zipfile.ZipFile(exports[-1]) as archive:
        if page_number is not None:
            names = [f"ppt/slides/slide{page_number}.xml"]
        else:
            names = [name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
        texts: list[str] = []
        for name in names:
            if name not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(name))
            texts.extend(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
    return "\n".join(texts)


def _replacement_requests(prompt: str) -> list[dict[str, object]]:
    """Extract explicit quoted A-to-B edits that can be checked exactly."""

    pattern = re.compile(
        r"第\s*(?P<page>\d+|一|二|三|四|五|六|七|八|九|十)\s*页.*?"
        r"从[\"“「](?P<old>.+?)[\"”」]\s*(?:修改为|修改|改为|改成|替换为|更改为)\s*"
        r"[\"“「](?P<new>.+?)[\"”」]"
    )
    page_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    requests: list[dict[str, object]] = []
    for match in pattern.finditer(prompt):
        raw_page = match.group("page")
        page = page_map.get(raw_page, int(raw_page) if raw_page.isdigit() else None)
        requests.append({"page": page, "old": match.group("old"), "new": match.group("new")})
    return requests


def _validate_revision(
    project_workspace: Path,
    baseline: dict[str, str],
    prompt: str,
    continue_mode: bool,
    target_slide: int | None,
) -> dict[str, object]:
    """Verify that the generated or continued authoring output is deliverable."""

    current = _snapshot(project_workspace)
    changed = sorted(
        path for path in set(baseline) | set(current) if baseline.get(path) != current.get(path)
    )
    svg_paths = _slide_paths(project_workspace, None)
    baseline_svg = {path for path in baseline if path.startswith("svg_output/")}
    current_svg = {f"svg_output/{path.name}" for path in svg_paths}
    target_svg = {
        f"svg_output/{path.name}"
        for path in _slide_paths(project_workspace, target_slide)
    }
    changed_svg_files = sorted(path for path in changed if path.startswith("svg_output/"))
    unexpected_changed_slides = sorted(
        path for path in changed_svg_files if target_slide is not None and path not in target_svg
    )
    target_changed = sorted(path for path in changed_svg_files if path in target_svg)
    # Exact replacement checks belong to page-scoped refinement jobs. A normal
    # continuation may reuse an unchanged checkpoint while still producing a
    # valid deck, so its prompt must not be interpreted as a revision contract.
    replacements = _replacement_requests(prompt) if target_slide is not None else []
    checks: list[dict[str, object]] = []
    for request in replacements:
        paths = _slide_paths(project_workspace, request["page"])
        content = "\n".join(path.read_text(encoding="utf-8") for path in paths if path.is_file())
        pptx_content = _pptx_slide_texts(project_workspace, request["page"])
        old, new = str(request["old"]), str(request["new"])
        checks.append({
            "page": request["page"],
            "old": old,
            "new": new,
            "passed": bool(paths)
            and new in content
            and old not in content
            and new in pptx_content
            and old not in pptx_content,
        })
    changed_svg = any(path.startswith("svg_output/") for path in changed)
    changed_pptx = any(path.startswith("exports/") for path in changed)
    pptx_paths = sorted((project_workspace / "exports").glob("*.pptx"))
    is_page_refinement = target_slide is not None
    # A resumed ordinary generation job is seeded from an immutable checkpoint.
    # The copied files are already valid output even when the model leaves one
    # or more of them byte-identical, so requiring a hash change causes a false
    # failure after a successful export.
    passed = bool(svg_paths) and bool(pptx_paths)
    if is_page_refinement:
        passed = passed and changed_svg and changed_pptx
        passed = passed and bool(target_svg) and bool(target_changed)
        passed = passed and not unexpected_changed_slides and baseline_svg == current_svg
    if checks:
        passed = passed and all(bool(check["passed"]) for check in checks)
    validation_type = "精修" if is_page_refinement else ("继续生成" if continue_mode else "生成")
    result = {
        "passed": passed,
        "continuation": continue_mode,
        "changed_files": changed,
        "changed_svg": changed_svg,
        "changed_pptx": changed_pptx,
        "target_slide_number": target_slide,
        "changed_target_slides": target_changed,
        "unexpected_changed_slides": unexpected_changed_slides,
        "slide_roster_unchanged": baseline_svg == current_svg if continue_mode else True,
        "checks": checks,
        "message": (
            f"{validation_type}校验通过"
            if passed
            else f"{validation_type}未生效：未检测到符合要求的 SVG/PPTX 产物"
        ),
    }
    (project_workspace / "validation").mkdir(parents=True, exist_ok=True)
    (project_workspace / "validation" / "change_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def validate_revision(ctx: SkillContext, baseline: dict[str, str]) -> dict[str, object]:
    return _validate_revision(ctx.workspace, baseline, ctx.prompt, ctx.continue_mode, ctx.target_slide)


def prepare_template(ctx: SkillContext) -> str:
    """Return the template steering instruction, or raise when it is unusable."""

    if not ctx.template_root:
        return ""
    selected_template = Path(ctx.template_root)
    if not (selected_template / "templates" / "design_spec.md").is_file():
        raise AdapterError("所选模板工作区不可用")
    emit("template", message="正在应用所选模板")
    return (
        f"Use the selected PPT Master template workspace at {selected_template} as the exact "
        "template workspace for this run. Read and apply it while generating. Do not modify, "
        "move, or duplicate that template workspace."
    )


def _manifest_value(ctx: SkillContext, section: str, key: str, default: str) -> str:
    if not ctx.manifest:
        return default
    return str(((ctx.manifest.get(section) or {}).get(key)) or default)


def build_agent_prompt(ctx: SkillContext, template_instruction: str = "") -> str:
    """Compose the autonomous quick-generation steering prompt."""

    project_workspace = ctx.workspace
    conventions_doc = _manifest_value(ctx, "agent", "repo_conventions_doc", "AGENTS.md")
    entry_doc = _manifest_value(ctx, "agent", "entry_doc", "skills/ppt-master/SKILL.md")
    if ctx.continue_mode:
        workspace_instruction = (
            "The workspace contains the last successful revision. Modify that existing PPT Master "
            "project in place and preserve all unaffected slides."
        )
    else:
        workspace_instruction = "The Worker has already initialized the empty project workspace."
    return f"""You are executing one autonomous PPT Master generation job.

Read and follow /app/{conventions_doc} and the Skill entry /app/{entry_doc}. The web request is
explicit quick-generation intent, so use the Skill's Quick Generate runtime without an
interactive confirmation gate. The only project workspace is {project_workspace}; {workspace_instruction}
It is the immutable project root for this job. Do not run project_manager.py init, and do
not move, rename, copy, or create another project directory. Author every project file
directly beneath this exact path.
{template_instruction}
For continuation edits, modify the existing SVG authoring files directly and preserve all
unaffected slides. If a target slide is provided, only that slide's SVG may change; do not
modify any other slide SVG, even if a broader redesign seems helpful. Do not run sudo, inspect /proc, inspect host permissions, or probe the
container environment; those checks are unrelated to the presentation edit. Create a
native editable PPTX, run the required quality checks, and export the final .pptx into
{project_workspace}/exports. Do not access files outside {WORKSPACE} except the installed
PPT Master Skill and its declared tools.

User request:
{ctx.prompt}
"""
