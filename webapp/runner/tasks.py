"""Queue consumers that run one skill job in a bounded subprocess."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from celery.utils.log import get_task_logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api.config import get_settings
from api.models import (
    Artifact,
    ArtifactKind,
    Invitation,
    Job,
    JobEvent,
    JobStatus,
    PageRefinementMessage,
    Project,
    ProjectMaterial,
    Provider,
    ProviderModel,
    SystemSetting,
    Template,
    TemplateStatus,
    User,
)
from api.provider_config import opencode_config
from skills.registry import artifact_rules, continue_seed_dir, marker_dir, skill_manifest_for
from .celery_app import celery_app

logger = get_task_logger(__name__)
settings = get_settings()
SKILL_ROOT = Path("/app/skills/ppt-master")
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(_engine, expire_on_commit=False)

# Worker modules run as subprocesses of this runner with bounded resources.
# The bootstrap sets rlimits before importing the module so even import-time
# work stays inside the budget.
_WORKER_BOOTSTRAP = """import resource, runpy, sys
for name, cap in (("AS", 6 << 30), ("NPROC", 512), ("FSIZE", 2 << 30)):
    limit = getattr(resource, "RLIMIT_" + name)
    try:
        resource.setrlimit(limit, (cap, cap))
    except (ValueError, OSError):
        pass
module = sys.argv[1]
sys.argv = [module]
runpy.run_module(module, run_name="__main__", alter_sys=True)
"""


def _template_workspace_path(template: Template) -> Path:
    root = settings.workspace_root.resolve()
    path = (root / template.workspace_relpath).resolve()
    if root not in path.parents:
        raise RuntimeError("模板工作区越出数据根目录")
    return path


def _project_workspace_path(project: Project) -> Path:
    """Resolve the runner-visible workspace used to discover output artifacts."""

    root = settings.workspace_root.resolve()
    path = (root / project.workspace_relpath).resolve()
    if root not in path.parents:
        raise RuntimeError("项目工作区越出数据根目录")
    return path


def _job_workspace_path(project: Project, job: Job) -> Path:
    """Resolve one job's isolated workspace below its authorized project root."""

    project_root = _project_workspace_path(project)
    path = (project_root / "jobs" / str(job.id)).resolve()
    if project_root not in path.parents:
        raise RuntimeError("任务工作区越出项目边界")
    return path


def _job_workspace_path_by_id(project: Project, job_id: UUID) -> Path:
    """Resolve a historical Job workspace under the same authorized project."""

    project_root = _project_workspace_path(project)
    path = (project_root / "jobs" / str(job_id)).resolve()
    if project_root not in path.parents:
        raise RuntimeError("基线任务工作区越出项目边界")
    return path


def _template_snapshot_source_path(job: Job) -> Path:
    """Resolve the immutable template source recorded when a job was created."""

    relpath = (job.template_workspace_relpath or "").replace("\\", "/")
    root_name = (job.template_root or "").replace("\\", "/")
    workspace_relative = PurePosixPath(relpath)
    template_relative = PurePosixPath(root_name)
    if (
        not relpath
        or not root_name
        or workspace_relative.is_absolute()
        or template_relative.is_absolute()
        or ".." in workspace_relative.parts
        or ".." in template_relative.parts
    ):
        raise RuntimeError("任务的模板快照无效")
    workspace_root = settings.workspace_root.resolve()
    template_path = (workspace_root / workspace_relative / template_relative).resolve()
    if workspace_root not in template_path.parents:
        raise RuntimeError("模板快照越出数据根目录")
    return template_path


def _copy_template_snapshot(job: Job, destination: Path) -> Path | None:
    """Copy an optional selected template into the isolated job workspace."""

    if not job.template_name:
        return None
    source = _template_snapshot_source_path(job)
    if not (source / "templates" / "design_spec.md").is_file():
        raise RuntimeError("所选模板工作区不可用")
    if any(item.is_symlink() for item in source.rglob("*")):
        raise RuntimeError("所选模板包含不受支持的符号链接")
    target = destination / "template"
    shutil.copytree(source, target)
    return target


def _prepare_job_workspace(project: Project, job: Job) -> Path:
    """Create one worker workspace and make only that directory worker-writable.

    The runner creates directories as root, while the short-lived worker runs as
    an unprivileged UID. Linux bind mounts can use chown; Docker Desktop bind
    mounts may reject it, so the narrowly scoped job directory falls back to
    mode 0777 instead of weakening the project root.
    """

    path = _job_workspace_path(project, job)
    path.mkdir(parents=True, exist_ok=False)
    worker_uid = settings.worker_uid
    worker_gid = settings.worker_gid
    try:
        if hasattr(os, "chown"):
            os.chown(path, worker_uid, worker_gid)
            path.chmod(0o750)
            return path
    except OSError:
        logger.info("Unable to chown job workspace %s; using writable mode", path)
    try:
        path.chmod(0o777)
    except OSError as exc:
        raise RuntimeError(f"任务工作区不可写：{path}") from exc
    return path


def _source_project_root(source_root: Path, skill_marker: str) -> Path:
    """Find the actual authoring root inside a historical job workspace."""

    if not skill_marker:
        raise RuntimeError("技能清单未声明作者根标记目录")
    if (source_root / skill_marker).is_dir():
        return source_root
    candidates = [
        item
        for item in source_root.iterdir()
        if item.is_dir() and (item / skill_marker).is_dir()
    ]
    if len(candidates) != 1:
        raise RuntimeError("基线工作区中没有唯一的作者根目录")
    return candidates[0]


def _grant_worker_write_access(root: Path) -> None:
    """Make a copied revision writable by exactly the configured worker user."""

    entries = [root, *root.rglob("*")]
    try:
        for entry in entries:
            os.chown(entry, settings.worker_uid, settings.worker_gid)
        return
    except OSError:
        logger.info("Unable to chown copied workspace %s; widening only this job tree", root)
    for entry in entries:
        try:
            if entry.is_dir():
                entry.chmod(0o777)
            else:
                entry.chmod(entry.stat().st_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        except OSError as exc:
            raise RuntimeError(f"复制后的任务工作区不可写：{entry}") from exc


def _grant_editor_write_access(root: Path) -> None:
    """Transfer one completed job workspace to the API user for SVG editing."""

    try:
        web_uid = int(os.environ.get("PPTMASTER_WEB_UID", "10001"))
    except ValueError as exc:
        raise RuntimeError("PPTMASTER_WEB_UID 配置必须是数字") from exc
    entries = [root, *root.rglob("*")]
    try:
        for entry in entries:
            os.chown(entry, web_uid, web_uid)
        return
    except OSError:
        logger.info("Unable to chown editor workspace %s; widening only this job tree", root)
    for entry in entries:
        try:
            if entry.is_dir():
                entry.chmod(0o777)
            else:
                entry.chmod(entry.stat().st_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        except OSError as exc:
            raise RuntimeError(f"完成任务的工作区不可供编辑器写入：{entry}") from exc


def _seed_job_workspace(project: Project, job: Job, destination: Path) -> bool:
    """Copy the last revision into a stable authoring root for this job."""

    if not job.base_job_id:
        return False
    manifest = skill_manifest_for(job.skill_id)
    source_root = _job_workspace_path_by_id(project, job.base_job_id)
    if not source_root.is_dir() or not any(source_root.iterdir()):
        raise RuntimeError(f"基线任务工作区为空：{job.base_job_id}")
    source_root = _source_project_root(source_root, marker_dir(manifest))
    # Never follow links from generated content during a cross-revision copy.
    if any(item.is_symlink() for item in source_root.rglob("*")):
        raise RuntimeError(f"基线任务工作区包含不受支持的符号链接：{job.base_job_id}")
    target_root = destination / continue_seed_dir(manifest)
    target_root.mkdir(parents=True, exist_ok=False)
    for source in source_root.iterdir():
        target = target_root / source.name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return True


def _copy_project_materials(project: Project, destination: Path) -> None:
    """Copy immutable project source materials into the isolated worker mount.

    Stored filenames are random UUIDs (see ProjectMaterial.relative_path), so
    a worker that later globs this directory and sorts by filename (e.g. the
    gongwen typeset adapter's verbatim-content fallback, which concatenates
    every extracted sidecar when no content was pasted) would join multi-part
    uploads in an order unrelated to when the user added them. Prefixing each
    copied file with its zero-padded upload order fixes that without any
    worker-side change, since filename-sort now matches upload order.
    """

    project_root = _project_workspace_path(project)
    materials_root = (project_root / "materials").resolve()
    if project_root not in materials_root.parents or not materials_root.is_dir():
        return
    target_root = (destination / "materials").resolve()
    if destination.resolve() not in target_root.parents:
        raise RuntimeError("材料复制目标越出任务工作区")
    target_root.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        ordered_ids = [
            str(material_id)
            for (material_id,) in db.execute(
                select(ProjectMaterial.id)
                .where(ProjectMaterial.project_id == project.id)
                .order_by(ProjectMaterial.created_at.asc())
            ).all()
        ]
    order_index = {material_id: index for index, material_id in enumerate(ordered_ids)}
    for source in materials_root.iterdir():
        if source.is_symlink() or not source.is_file():
            continue
        stem = source.name.split(".", 1)[0]
        index = order_index.get(stem)
        prefixed_name = f"{index:03d}_{source.name}" if index is not None else source.name
        target = target_root / prefixed_name
        shutil.copy2(source, target)


def _provider_environment() -> dict[str, str]:
    """Forward only explicitly allowlisted provider credentials to a job worker."""

    names = os.environ.get("PPTMASTER_OPENCODE_ENV_ALLOWLIST", "").split(",")
    environment: dict[str, str] = {}
    for raw_name in names:
        name = raw_name.strip()
        if not name or not _ENV_NAME_RE.fullmatch(name):
            continue
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _run_worker_module(
    module: str,
    env: dict[str, str],
    on_line,
) -> tuple[int, list[str]]:
    """Run one worker module as a bounded subprocess and stream its JSONL."""

    process = subprocess.Popen(
        [sys.executable, "-c", _WORKER_BOOTSTRAP, module],
        cwd="/app",
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    assert process.stdout is not None
    lines: list[str] = []
    for raw in process.stdout:
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
        on_line(line)
    return process.wait(), lines


def _terminate_process_group(process: subprocess.Popen, grace_seconds: int = 10) -> None:
    """Stop one worker process group, escalating to SIGKILL after the grace."""

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait()


def _watch_cancellation(
    job_id: UUID,
    process: subprocess.Popen,
    stopped: threading.Event,
    cancelled: threading.Event,
) -> None:
    """Poll the database and stop the worker process once cancellation lands."""

    while not stopped.wait(1.0):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            requested = bool(job and job.cancellation_requested)
        if not requested:
            continue
        cancelled.set()
        _terminate_process_group(process)
        return


def _load_job(job_id: UUID) -> tuple[Job, Project]:
    """Load a queued job, or persist its cancellation before it starts."""

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            raise RuntimeError(f"任务 {job_id} 不存在")
        project = db.get(Project, job.project_id)
        if not project:
            raise RuntimeError(f"项目 {job.project_id} 不存在")
        if job.cancellation_requested or job.status is JobStatus.CANCELLED:
            job.status = JobStatus.CANCELLED
            job.finished_at = datetime.now(UTC)
            db.add(JobEvent(job_id=job.id, event_type="status", payload={"status": "cancelled"}))
            _record_refinement_result(db, job)
            db.commit()
            return job, project
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        db.add(JobEvent(job_id=job.id, event_type="status", payload={"status": "running"}))
        db.commit()
        return job, project


def _record_event(job_id: UUID, event: dict) -> None:
    """Persist one worker event without exposing database credentials to the worker."""

    with SessionLocal() as db:
        db.add(JobEvent(job_id=job_id, event_type=str(event.get("type", "agent")), payload=event))
        db.commit()


def _record_refinement_result(db, job: Job, reply: str = "") -> None:
    """Append one terminal assistant message for a refinement job.

    Page refinement targets one slide (target_slide_number 1..999); document
    refinement (公文) targets the whole document and stores its request under
    slide 0, so both scopes must receive a terminal assistant message.
    """

    slide_number = job.target_slide_number
    if slide_number is None:
        document_scope = (
            db.execute(
                select(PageRefinementMessage.id).where(
                    PageRefinementMessage.job_id == job.id,
                    PageRefinementMessage.slide_number == 0,
                    PageRefinementMessage.role == "user",
                )
            ).first()
            is not None
        )
        if not document_scope:
            return
        slide_number = 0
    if job.status is JobStatus.SUCCEEDED:
        agent_reply = (reply or "").strip()
        # Refinement prompts require a marked Chinese reply; only that marked
        # answer is shown, so stream narration never leaks into the chat.
        if agent_reply:
            content = agent_reply
        elif slide_number == 0:
            content = "已按你的要求完成修改，文档与预览均已更新。如需继续调整，请直接告诉我。"
        else:
            content = "当前页面已修改完成，结果已应用到当前 PPT。你还可以继续告诉我需要调整的地方。"
    elif job.status is JobStatus.CANCELLED:
        content = "这次修改已中止，当前文档没有变化。你可以继续发送新的修改要求。"
    else:
        detail = (job.error or "").strip()
        content = "这次修改没有完成，当前文档没有变化。你可以直接重试，或换一种方式描述修改要求。"
        if detail:
            content += f"失败原因：{detail[:800]}"
    db.add(
        PageRefinementMessage(
            project_id=job.project_id,
            job_id=job.id,
            slide_number=slide_number,
            role="assistant",
            content=content,
        )
    )


def _finish_job(job_id: UUID, succeeded: bool, error: str | None = None, reply: str = "") -> None:
    """Persist terminal state and discover the job's exported artifacts."""

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            return
        project = db.get(Project, job.project_id)
        if not project:
            return
        job.status = JobStatus.SUCCEEDED if succeeded else (JobStatus.CANCELLED if job.cancellation_requested else JobStatus.FAILED)
        job.error = error
        job.finished_at = datetime.now(UTC)
        db.add(JobEvent(job_id=job.id, event_type="status", payload={"status": job.status.value}))
        _record_refinement_result(db, job, reply=reply)
        project_workspace = _project_workspace_path(project)
        job_workspace = _job_workspace_path(project, job)
        _discover_job_artifacts(db, job, project, project_workspace, job_workspace)
        _grant_editor_write_access(job_workspace)
        owner_id = project.owner_id
        db.commit()
    # Account cleanup is deliberately outside the job transaction. A stale
    # runner image, enum mismatch, or filesystem issue must never rewrite a
    # successfully exported job as failed after this commit has completed.
    try:
        _finalize_pending_user_deletion(owner_id)
    except Exception:  # noqa: BLE001
        logger.exception("Post-job user cleanup failed for owner %s", owner_id)


def _discover_job_artifacts(
    db,
    job: Job,
    project: Project,
    project_workspace: Path,
    job_workspace: Path,
) -> None:
    """Register every manifest-declared output file produced by a task."""

    try:
        manifest = skill_manifest_for(job.skill_id)
        authoring_root = _source_project_root(job_workspace, marker_dir(manifest))
        for folder, pattern, kind, content_type in artifact_rules(manifest):
            artifact_dir = authoring_root / folder
            if not artifact_dir.is_dir():
                continue
            for artifact_path in artifact_dir.glob(pattern):
                relative_path = str(artifact_path.relative_to(project_workspace))
                exists = db.execute(
                    select(Artifact).where(
                        Artifact.job_id == job.id,
                        Artifact.relative_path == relative_path,
                    )
                ).scalar_one_or_none()
                if exists:
                    exists.size_bytes = artifact_path.stat().st_size
                    continue
                db.add(
                    Artifact(
                        project_id=project.id,
                        job_id=job.id,
                        kind=ArtifactKind(kind),
                        relative_path=relative_path,
                        content_type=content_type,
                        size_bytes=artifact_path.stat().st_size,
                    )
                )
    except (OSError, KeyError, RuntimeError, ValueError) as exc:
        logger.warning("Skipping artifact discovery for job %s: %s", job.id, exc)


def _finalize_pending_user_deletion(user_id: UUID) -> None:
    """Remove a deactivated account only after every worker has stopped."""
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or user.deletion_requested_at is None:
            return
        active = db.execute(select(Job.id).join(Project).where(Project.owner_id == user.id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))).scalar_one_or_none()
        if active:
            return
        user_root = (settings.workspace_root.resolve() / str(user.id)).resolve()
        root = settings.workspace_root.resolve()
        if root not in user_root.parents:
            raise RuntimeError("用户工作区越出数据根目录")
        invitations = db.execute(
            select(Invitation).where(
                (Invitation.created_by == user.id) | (Invitation.used_by == user.id)
            )
        ).scalars().all()
        projects = db.execute(select(Project).where(Project.owner_id == user.id)).scalars().all()
        for invitation in invitations:
            db.delete(invitation)
        for project in projects:
            db.delete(project)
        db.delete(user)
        db.commit()
    if user_root.exists():
        try:
            shutil.rmtree(user_root)
        except OSError:
            logger.exception("Failed to remove deleted user workspace: %s", user_root)


def _job_opencode_config(job: Job) -> str | None:
    """Build an ephemeral config for a database-managed model."""
    if not job.model:
        return None
    with SessionLocal() as db:
        result = db.execute(select(Provider, ProviderModel).join(ProviderModel, ProviderModel.provider_id == Provider.id).where(Provider.is_active.is_(True), ProviderModel.is_active.is_(True), ProviderModel.is_verified.is_(True)))
        for provider, model in result.all():
            if f"{provider.slug}/{model.model_id}" == job.model:
                return json.dumps(opencode_config(provider, model), ensure_ascii=False)
    return None


def _template_review_opencode_config() -> str | None:
    """Build an ephemeral OpenCode config for the template review agent.

    Reuses the platform default model so template review follows the same
    administrator-managed catalog as generation jobs.
    """

    with SessionLocal() as db:
        setting = db.get(SystemSetting, "default_model_id")
        default_model = setting.value if setting else None
        if not default_model:
            return None
        result = db.execute(select(Provider, ProviderModel).join(ProviderModel, ProviderModel.provider_id == Provider.id).where(Provider.is_active.is_(True), ProviderModel.is_active.is_(True), ProviderModel.is_verified.is_(True)))
        for provider, model in result.all():
            if f"{provider.slug}/{model.model_id}" == default_model:
                return json.dumps(opencode_config(provider, model), ensure_ascii=False)
    return None


@celery_app.task(name="runner.execute_job", bind=True)
def execute_job(self, job_id_text: str) -> None:
    """Run a generation job as a bounded subprocess of this runner."""

    job_id = UUID(job_id_text)
    job, project = _load_job(job_id)
    if job.status is JobStatus.CANCELLED:
        try:
            _finalize_pending_user_deletion(project.owner_id)
        except Exception:  # noqa: BLE001
            logger.exception("Cancelled-job user cleanup failed for owner %s", project.owner_id)
        return
    worker_error: str | None = None
    reply_text = ""
    process: subprocess.Popen | None = None
    stopped, cancelled = threading.Event(), threading.Event()
    try:
        job_workspace = _prepare_job_workspace(project, job)
        template_workspace = _copy_template_snapshot(job, job_workspace)
        is_continuation = _seed_job_workspace(project, job, job_workspace)
        _copy_project_materials(project, job_workspace)
        if is_continuation or template_workspace:
            _grant_worker_write_access(job_workspace)
        generated_config = _job_opencode_config(job)
        skill_manifest = skill_manifest_for(job.skill_id)
        environment = {
            "PPTMASTER_JOB_ID": str(job.id),
            "PPTMASTER_JOB_PROMPT": job.prompt,
            "PPTMASTER_JOB_MODEL": job.model or "",
            "PPTMASTER_SKILL_ID": job.skill_id,
            "PPTMASTER_SKILL_MANIFEST_JSON": json.dumps(skill_manifest, ensure_ascii=False),
            "PPTMASTER_CONTINUE": "1" if is_continuation else "0",
            "PPTMASTER_WORKSPACE": str(job_workspace),
            "HOME": "/home/pptmaster",
            "PPTMASTER_OPENCODE_IDLE_TIMEOUT_SECONDS": str(settings.opencode_idle_timeout_seconds),
            **_provider_environment(),
        }
        if job.mode:
            environment["PPTMASTER_JOB_MODE"] = job.mode
        if job.target_slide_number is not None:
            environment["PPTMASTER_TARGET_SLIDE"] = str(job.target_slide_number)
        if template_workspace:
            environment["PPTMASTER_TEMPLATE_ROOT"] = str(job_workspace / "template")
        if generated_config:
            environment["PPTMASTER_OPENCODE_CONFIG_JSON"] = generated_config

        def record_line(line: str) -> None:
            nonlocal worker_error
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "log", "text": line[:1000]}
            if event.get("type") == "error":
                worker_error = str(event.get("message") or "任务执行失败")
            elif event.get("type") == "agent":
                # Refinement prompts end with a marked user-facing reply; keep
                # the latest marked answer as the chat confirmation.
                agent_text = str(event.get("text") or "")
                if "【回复用户】" in agent_text:
                    reply_text = agent_text.split("【回复用户】", 1)[1].strip()[:2000]
            _record_event(job.id, event)

        process = subprocess.Popen(
            [sys.executable, "-c", _WORKER_BOOTSTRAP, "worker.main"],
            cwd="/app",
            env={**os.environ, **environment},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        monitor = threading.Thread(
            target=_watch_cancellation, args=(job.id, process, stopped, cancelled), daemon=True
        )
        monitor.start()
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            record_line(line)
        return_code = process.wait()
        stopped.set()
        monitor.join(timeout=2)
        if cancelled.is_set():
            _finish_job(job.id, succeeded=False, error="任务已取消")
            return
        if return_code != 0:
            raise RuntimeError(worker_error or f"Worker exited with code {return_code}")
        _finish_job(job.id, succeeded=True, reply=reply_text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s failed", job.id)
        if process is not None and process.poll() is None:
            stopped.set()
            _terminate_process_group(process)
        _finish_job(job.id, succeeded=False, error=str(exc))
        raise


@celery_app.task(name="runner.sync_docx_editor_previews")
def sync_docx_editor_previews(project_id_text: str, job_id_text: str) -> None:
    """Re-render gongwen previews after a manual OnlyOffice edit is saved.

    The workspace preview PNGs only regenerate during AI jobs, so without this
    task the project page kept showing the pre-edit document. Renders with the
    same LibreOffice + GB/T font pipeline the original job used.
    """

    project_id = UUID(project_id_text)
    job_id = UUID(job_id_text)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        project = db.get(Project, project_id)
    if not job or not project:
        return
    try:
        job_workspace = _job_workspace_path(project, job)
        seed_dir = skill_manifest_for(job.skill_id).get("workspace", {}).get("continue_seed_dir") or "gongwen-project"
        authoring = job_workspace / seed_dir
        docx_files = sorted(
            (path for path in (authoring / "exports").rglob("*.docx") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
        )
        if not docx_files:
            return
        docx = docx_files[-1]
        environment = dict(os.environ)
        runtime_config = authoring / "gongwen-runtime.json"
        try:
            fontconfig_file = str(json.loads(runtime_config.read_text(encoding="utf-8")).get("fontconfig_file") or "")
        except (OSError, json.JSONDecodeError):
            fontconfig_file = ""
        if fontconfig_file and Path(fontconfig_file).is_file():
            environment["FONTCONFIG_FILE"] = fontconfig_file
        exports = authoring / "exports"
        convert = subprocess.run(
            ["soffice", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
            env=environment, cwd=str(authoring), capture_output=True, text=True, timeout=600,
        )
        pdf = docx.parent / f"{docx.stem}.pdf"
        if convert.returncode != 0 or not pdf.is_file():
            _record_editor_event(job_id, "预览渲染未完成，文档本体已保存")
            return
        preview_root = authoring / "preview"
        preview_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["pdftoppm", "-png", "-r", "110", str(pdf), str(preview_root / "page")],
            env=environment, cwd=str(authoring), capture_output=True, text=True, timeout=600,
        )
        _record_editor_event(job_id, "手动编辑已保存，预览已同步")
    except Exception:  # noqa: BLE001
        logger.exception("Preview resync failed for job %s", job_id)


def _record_editor_event(job_id: UUID, text: str) -> None:
    with SessionLocal() as db:
        db.add(JobEvent(job_id=job_id, event_type="editor_export", payload={"status": "succeeded", "text": text}))
        db.commit()


@celery_app.task(name="runner.sync_pptx_editor_revision")
def sync_pptx_editor_revision(project_id_text: str, job_id_text: str) -> None:
    """Re-import a manually edited PPTX into the job's SVG authoring source.

    Without this loop the next AI refinement would regenerate from the
    pre-edit SVG pages and silently drop the user's manual edits. The
    roundtrip import rewrites svg_output page-by-page (in slide order) so the
    existing preview/editor artifact records stay valid.
    """

    project_id = UUID(project_id_text)
    job_id = UUID(job_id_text)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        project = db.get(Project, project_id)
    if not job or not project:
        return
    try:
        job_workspace = _job_workspace_path(project, job)
        authoring = next(
            (entry for entry in job_workspace.iterdir() if (entry / "svg_output").is_dir()),
            None,
        )
        if authoring is None:
            _record_editor_event(job_id, "未找到演示文稿编辑源，跳过回写")
            return
        pptx_files = sorted(
            (path for path in (authoring / "exports").rglob("*.pptx") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
        )
        if not pptx_files:
            _record_editor_event(job_id, "未找到手动保存的 PPTX，跳过回写")
            return
        saved_pptx = pptx_files[-1]
        staging = Path("/tmp/pptx-editor-roundtrip")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        convert = subprocess.run(
            [
                sys.executable, str(SKILL_ROOT / "scripts" / "pptx_to_svg.py"),
                str(saved_pptx), "--inheritance-mode", "both", "--roundtrip",
                "-o", str(staging),
            ],
            cwd="/app", capture_output=True, text=True, timeout=600,
        )
        flat = staging / "authoring-svg-flat"
        if convert.returncode != 0 or not flat.is_dir():
            _record_editor_event(job_id, f"PPTX 回写转换未完成：{(convert.stderr or convert.stdout)[-200:]}")
            return
        svg_output = authoring / "svg_output"
        existing = sorted(svg_output.glob("*.svg"))
        imported = sorted(flat.glob("*.svg"))
        for index, page in enumerate(imported):
            if index < len(existing):
                shutil.copyfile(page, existing[index])
            else:
                shutil.copyfile(page, svg_output / f"{index + 1:02d}_slide.svg")
        images_src = staging / "images"
        if images_src.is_dir():
            images_dst = authoring / "images"
            images_dst.mkdir(parents=True, exist_ok=True)
            for image in images_src.iterdir():
                if image.is_file():
                    shutil.copyfile(image, images_dst / image.name)
        note = ""
        if len(imported) != len(existing):
            note = f"（页数由 {len(existing)} 页变为 {len(imported)} 页，超出部分预览暂未同步）"
        _record_editor_event(job_id, f"手动编辑已回写演示文稿源{note}")
    except Exception:  # noqa: BLE001
        logger.exception("PPTX editor resync failed for job %s", job_id)


@celery_app.task(name="runner.import_template")
def import_template(template_id_text: str) -> None:
    """Parse an uploaded PPTX into a deterministic Deck template workspace."""

    template_id = UUID(template_id_text)

    def clean_error(value: str) -> str:
        """Keep worker progress envelopes out of the user-visible error field."""

        lines = [line.strip() for line in value.splitlines() if line.strip()]
        meaningful = [line for line in lines if not line.startswith('{"type":')]
        return (meaningful[-1] if meaningful else (lines[-1] if lines else "模板解析失败"))[-3000:]

    def update_progress(
        *,
        stage: str,
        message: str,
        log_line: str | None = None,
    ) -> None:
        """Persist bounded import progress so the UI can explain long-running work."""

        with SessionLocal() as progress_db:
            current = progress_db.get(Template, template_id)
            if not current:
                return
            metadata = dict(current.meta or {})
            progress = dict(metadata.get("progress") or {})
            logs = list(progress.get("logs") or [])
            entry = log_line or message
            if entry and (not logs or logs[-1] != entry):
                logs.append(entry[-1000:])
            progress.update(
                {
                    "stage": stage,
                    "message": message,
                    "logs": logs[-120:],
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            metadata["progress"] = progress
            current.meta = metadata
            progress_db.commit()

    with SessionLocal() as db:
        template = db.get(Template, template_id)
        if not template:
            return
        template.status = TemplateStatus.ANALYZING.value
        template.error = None
        metadata = dict(template.meta or {})
        metadata["progress"] = {
            "stage": "starting",
            "message": "正在启动模板解析容器",
            "logs": ["任务已进入模板解析队列"],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        template.meta = metadata
        db.commit()
    update_progress(stage="starting", message="正在启动模板解析进程")
    try:
        update_progress(stage="starting", message="正在准备模板工作区")
        template_workspace = _template_workspace_path(template)
        _grant_worker_write_access(template_workspace)

        def record_line(line: str, output_lines: list[str]) -> None:
            output_lines.append(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                update_progress(stage="running", message=line[:240], log_line=line)
                return
            if event.get("type") == "progress":
                update_progress(
                    stage=str(event.get("stage") or "running"),
                    message=str(event.get("message") or "正在分析模板"),
                    log_line=str(event.get("message") or ""),
                )
            elif event.get("type") == "log":
                update_progress(
                    stage="running",
                    message=str(event.get("message") or "正在分析模板")[:240],
                    log_line=str(event.get("message") or ""),
                )

        output_lines: list[str] = []
        import_env = {
            "PPTMASTER_TEMPLATE_ID": str(template_id),
            "PPTMASTER_WORKSPACE": str(template_workspace),
            "HOME": "/home/pptmaster",
        }
        review_config = _template_review_opencode_config()
        if review_config:
            import_env["PPTMASTER_OPENCODE_CONFIG_JSON"] = review_config
            import_env["PPTMASTER_OPENCODE_IDLE_TIMEOUT_SECONDS"] = str(settings.opencode_idle_timeout_seconds)
        code, _ = _run_worker_module(
            "worker.template_import",
            import_env,
            lambda line: record_line(line, output_lines),
        )
        update_progress(stage="running", message="模板解析完成，正在校验结果")
        output = "\n".join(output_lines)
        if code != 0:
            raise RuntimeError(clean_error(output))
        summary_event = next(
            (json.loads(line) for line in reversed(output_lines) if line.startswith("{") and json.loads(line).get("type") == "result"),
            None,
        )
        summary = (summary_event or {}).get("summary") or {}
        if not summary:
            raise RuntimeError("模板解析完成但没有返回结果")
        update_progress(stage="completed", message="模板解析完成，正在保存可用模板")
        with SessionLocal() as db:
            refreshed = db.get(Template, template_id)
            if not refreshed:
                return
            refreshed.status = TemplateStatus.READY.value
            refreshed.page_count = int(summary.get("page_count") or 0) or None
            if refreshed.scope == "system":
                refreshed.is_active = True
            metadata = dict(refreshed.meta or {})
            metadata.update(summary)
            progress = dict(metadata.get("progress") or {})
            progress.update(
                {
                    "stage": "completed",
                    "message": "模板解析完成",
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            metadata["progress"] = progress
            refreshed.meta = metadata
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Template import failed for %s", template_id)
        failure_message = clean_error(str(exc))
        with SessionLocal() as db:
            refreshed = db.get(Template, template_id)
            if refreshed:
                refreshed.status = TemplateStatus.FAILED.value
                refreshed.error = failure_message
                metadata = dict(refreshed.meta or {})
                progress = dict(metadata.get("progress") or {})
                progress.update(
                    {
                        "stage": "failed",
                        "message": "模板解析失败",
                        "logs": list(progress.get("logs") or [])[-119:] + [failure_message],
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
                metadata["progress"] = progress
                refreshed.meta = metadata
                db.commit()


@celery_app.task(name="runner.export_editor_revision")
def export_editor_revision(job_id_text: str) -> None:
    """Run the native export gates after a browser saves SVG source changes."""

    job_id = UUID(job_id_text)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.status is not JobStatus.SUCCEEDED:
            return
        project = db.get(Project, job.project_id)
        if not project:
            return
        job_workspace = _job_workspace_path(project, job)
        if not job_workspace.is_dir():
            logger.warning("Editor export workspace is missing for job %s", job.id)
            return
        _grant_worker_write_access(job_workspace)
        db.add(
            JobEvent(
                job_id=job.id,
                event_type="editor_export",
                payload={
                    "status": "exporting",
                    "text": "正在校验并导出新版演示文稿。",
                },
            )
        )
        db.commit()

    try:
        job_workspace = _job_workspace_path(project, job)
        code, output_lines = _run_worker_module(
            "worker.export",
            {
                "PPTMASTER_WORKSPACE": str(job_workspace),
                "HOME": "/home/pptmaster",
            },
            lambda line: None,
        )
        if code != 0:
            output = "\n".join(output_lines[-20:])
            raise RuntimeError(output[-1800:] or "手动编辑导出失败")
        with SessionLocal() as db:
            refreshed_job = db.get(Job, job_id)
            if not refreshed_job:
                return
            refreshed_project = db.get(Project, refreshed_job.project_id)
            if not refreshed_project:
                return
            _discover_job_artifacts(
                db,
                refreshed_job,
                refreshed_project,
                _project_workspace_path(refreshed_project),
                _job_workspace_path(refreshed_project, refreshed_job),
            )
            newest_pptx = db.execute(
                select(Artifact)
                .where(
                    Artifact.job_id == refreshed_job.id,
                    Artifact.kind == ArtifactKind.PPTX,
                )
                .order_by(Artifact.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if newest_pptx is None:
                raise RuntimeError("未发现导出的新版演示文稿")
            db.add(
                JobEvent(
                    job_id=refreshed_job.id,
                    event_type="artifact",
                    payload={"path": newest_pptx.relative_path},
                )
            )
            db.add(
                JobEvent(
                    job_id=refreshed_job.id,
                    event_type="editor_export",
                    payload={
                        "status": "succeeded",
                        "text": "新版演示文稿已导出，可以下载。",
                    },
                )
            )
            _grant_editor_write_access(_job_workspace_path(refreshed_project, refreshed_job))
            db.commit()
    except Exception:
        logger.exception("Manual editor export failed for job %s", job_id)
        _record_event(
            job_id,
            {
                "type": "editor_export",
                "status": "failed",
                "text": "新版演示文稿导出失败，请检查本页文本或属性后重新保存。",
            },
        )


@celery_app.task(name="runner.extract_material")
def extract_material(material_id_text: str) -> None:
    """Extract one uploaded project material (anydoc + Chinese OCR fallback).

    Runs on the dedicated ``pptmaster-documents`` queue so a slow OCR pass
    never blocks generation. Extraction persists its own terminal status and
    never raises, so a crash here just leaves the material retryable.
    """

    from worker.document.extraction import extract_material as _run

    _run(material_id_text)
