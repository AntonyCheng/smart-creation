"""Execute one skill generation job inside a restricted container.

This is a manifest-driven driver: the runner picks the skill (and its baked
manifest) per job through ``PPTMASTER_SKILL_ID`` and
``PPTMASTER_SKILL_MANIFEST_JSON``; every skill-specific behavior lives in the
adapter chosen by ``worker.adapters.get_adapter``.
"""

from __future__ import annotations

from datetime import datetime
import json
import os

from worker.adapters import get_adapter
from worker.adapters.base import AdapterError, SkillContext
from worker.adapters.ppt_master import job_project_workspace as ppt_job_project_workspace
from worker.runtime import (
    OPENCODE_IDLE_TIMEOUT_EXIT_CODE,
    WORKSPACE,
    emit,
    install_opencode_config,
    opencode_idle_timeout_seconds,
    run_command,
)


def _target_slide_number() -> int | None:
    raw = os.environ.get("PPTMASTER_TARGET_SLIDE", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _load_skill() -> tuple[str, dict | None] | None:
    """Resolve the runner-selected skill and its manifest."""

    skill_id = os.environ.get("PPTMASTER_SKILL_ID", "").strip() or "ppt-master"
    raw = os.environ.get("PPTMASTER_SKILL_MANIFEST_JSON", "").strip()
    if not raw:
        if skill_id == "ppt-master":
            # A runner predating the manifest contract keeps legacy behavior.
            return skill_id, None
        emit("error", message=f"运行器未提供技能清单（skill {skill_id!r}），请升级 runner 镜像后重试")
        return None
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit("error", message=f"技能清单内容无效：{exc}")
        return None
    if not isinstance(manifest, dict):
        emit("error", message="技能清单必须是 JSON 对象")
        return None
    return skill_id, manifest


def _job_project_workspace(manifest: dict | None, continue_mode: bool):
    if manifest is None:
        return ppt_job_project_workspace(continue_mode)
    workspace_config = manifest.get("workspace") or {}
    seed_dir = str(workspace_config.get("continue_seed_dir") or "project")
    if continue_mode:
        return WORKSPACE / seed_dir
    suffix = str(workspace_config.get("fresh_root_suffix") or "")
    dated = f"{seed_dir}_{datetime.now():%Y%m%d}" if not suffix else f"{seed_dir}_{suffix}_{datetime.now():%Y%m%d}"
    return WORKSPACE / dated


def main() -> int:
    """Initialize the mounted workspace and run OpenCode for one skill job."""

    job_id = os.environ.get("PPTMASTER_JOB_ID", "")
    prompt = os.environ.get("PPTMASTER_JOB_PROMPT", "").strip()
    model = os.environ.get("PPTMASTER_JOB_MODEL", "").strip()
    if not job_id or not prompt:
        emit("error", message="任务环境变量缺失（JOB_ID / JOB_PROMPT）")
        return 2
    skill = _load_skill()
    if skill is None:
        return 2
    skill_id, manifest = skill
    adapter = get_adapter(skill_id, manifest)
    if adapter is None:
        return 2
    continue_mode = os.environ.get("PPTMASTER_CONTINUE") == "1"
    target_slide = _target_slide_number()
    template_root = os.environ.get("PPTMASTER_TEMPLATE_ROOT", "").strip()
    project_workspace = _job_project_workspace(manifest, continue_mode)
    if manifest:
        # Manifest-declared environment (e.g. a skill runtime config path) is
        # resolved against this job's workspace and inherited by OpenCode.
        for key, value in ((manifest.get("agent") or {}).get("env") or {}).items():
            os.environ[str(key)] = str(value).replace("{workspace}", str(project_workspace))
    context = SkillContext(
        skill_id=skill_id,
        manifest=manifest,
        prompt=prompt,
        workspace=project_workspace,
        continue_mode=continue_mode,
        target_slide=target_slide,
        template_root=template_root,
    )
    baseline: dict[str, str] = {}
    emit("status", status="initializing")
    if not install_opencode_config():
        return 1
    if continue_mode:
        if not project_workspace.is_dir() or not any(project_workspace.iterdir()):
            emit("error", message="基线工作区缺失或为空")
            return 1
        emit("status", status="continuing")
        baseline = adapter.baseline_snapshot(context)
        error = adapter.continue_workspace_error(context)
        if error:
            emit("error", message=error)
            return 1
    else:
        init_command = adapter.init_command(context)
        if init_command is not None and run_command(init_command) != 0:
            emit("error", message="项目工作区初始化失败")
            return 1
    try:
        template_instruction = adapter.prepare_template(context)
    except AdapterError as exc:
        emit("error", message=str(exc))
        return 1
    agent_prompt = adapter.build_agent_prompt(context, template_instruction)
    command = ["opencode", "run", "--format", "json"]
    if model:
        command.extend(["--model", model])
    command.append(agent_prompt)
    emit("status", status="running")
    return_code = run_command(command, idle_timeout_seconds=opencode_idle_timeout_seconds())
    if return_code:
        if return_code == OPENCODE_IDLE_TIMEOUT_EXIT_CODE:
            return return_code
        emit("error", message=f"生成引擎异常退出（退出码 {return_code}）")
        return return_code
    if not adapter.verify_project_workspace(context):
        return 1
    adapter.emit_artifacts(context)
    validation = adapter.validate_revision(context, baseline)
    emit("validation", **validation)
    if not validation["passed"]:
        emit("error", message=str(validation["message"]))
        return 1
    finalize = getattr(adapter, "finalize", None)
    if finalize is not None:
        finalize(context)
        adapter.emit_artifacts(context)
    emit("status", status="succeeded")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        emit("error", message=f"任务启动失败：{exc}")
        raise SystemExit(1)
