"""智创AI专家 MCP facade.

The MCP layer deliberately stays thin: the host model gathers requirements and
asks follow-up questions, while the platform remains the source of truth for
authentication, skill selection, task execution, artifacts, and retry
semantics. One submission tool per skill (self-describing fields beat a
generic skill parameter for tool selection), one generic status/retry pair.
"""

from __future__ import annotations

import hmac
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import config
from artifact_store import ArtifactStore
from client import PlatformApiError, PlatformClient
from skills_meta import SkillMeta


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("zhichuang-mcp")
config.validate()
client = PlatformClient()
skill_meta = SkillMeta(client)
artifacts = ArtifactStore(Path(__file__).with_name("artifacts"), config.ARTIFACT_TTL_MINUTES)
mcp = FastMCP(
    "zhichuang-ai-mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

PPT_REQUIRED_FIELDS = ("topic", "audience", "scenario", "objective")
DOC_REQUIRED_FIELDS = ("topic", "doc_type")


def _clean(value: str | None, limit: int = 4000) -> str:
    return (value or "").strip()[:limit]


def _ppt_questions(missing: list[str]) -> list[str]:
    labels = {
        "topic": "这份 PPT 的主题或核心问题是什么？",
        "audience": "这份 PPT 主要面向哪些人？",
        "scenario": "这份 PPT 会在什么场景下使用，例如汇报、培训或课堂？",
        "objective": "希望观众最终理解什么，或采取什么行动？",
    }
    return [labels[field] for field in missing]


def _doc_questions(missing: list[str]) -> list[str]:
    labels = {
        "topic": "这份公文的主题或核心事项是什么？",
        "doc_type": "公文文种是什么？（通知、请示、报告、纪要、函等）",
        "content": "请提供要排版的公文正文内容（可直接粘贴全文）。",
    }
    return [labels[field] for field in missing]


def _ppt_generation_prompt(values: dict[str, Any], request: str) -> str:
    page_range = _clean(values.get("page_range"), 100) or "由内容完整性决定，不强制固定页数"
    style = _clean(values.get("style"), 300) or "专业、简洁、结论先行"
    return (
        "请根据以下已确认需求生成一份可编辑 PPT。页数由内容决定，不要为了满足页数范围添加空泛页面；"
        "完成后保留真实生成页数。\n\n"
        f"主题：{values['topic']}\n受众：{values['audience']}\n使用场景：{values['scenario']}\n"
        f"目标：{values['objective']}\n页数偏好：{page_range}\n视觉风格：{style}\n"
        f"备注：{_clean(values.get('notes'), 2000)}\n原始需求：{_clean(request, 4000)}"
    )


def _doc_generation_prompt(values: dict[str, Any], request: str) -> str:
    style = _clean(values.get("style"), 300) or "规范、庄重、简明"
    lines = [
        "请根据以下需求起草一份规范公文。文种决定体例；"
        "缺失的具体日期、文号、联系方式等事实一律使用XX占位，不得编造；"
        "按 skill 流程完成结构检查并输出对话审核单。\n\n",
        f"主题：{values['topic']}",
        f"文种：{values['doc_type']}",
    ]
    if values.get("issuer"):
        lines.append(f"发文机关：{values['issuer']}")
    if values.get("recipient"):
        lines.append(f"主送机关：{values['recipient']}")
    if values.get("objective"):
        lines.append(f"写作目的：{values['objective']}")
    lines.append(f"语言风格：{style}")
    notes = _clean(values.get("notes"), 2000)
    if notes:
        lines.append(f"备注：{notes}")
    lines.append(f"原始需求：{_clean(request, 4000)}")
    return "\n".join(lines)




def _job_by_id(jobs: list[dict[str, Any]], job_id: str) -> dict[str, Any] | None:
    return next((job for job in jobs if str(job.get("id")) == job_id), None)


async def _submit_task(
    skill_id: str,
    requirements: dict[str, Any],
    prompt: str,
    conversation_id: str | None,
    submitted_message: str,
    mode: str | None = None,
    stage: str = "requirements",
) -> dict[str, Any]:
    """Shared submission path: create project, persist requirements, queue job.

    stage must match a stage the target skill/mode actually declares (gongwen
    typeset has no "requirements" stage at all — it starts at "content") or
    the platform rejects the save with 422 before a job is ever queued.
    """

    try:
        project = await client.create_project(str(requirements["topic"]), skill_id=skill_id, mode=mode)
        project_id = str(project["id"])
        await client.save_requirements(project_id, requirements, stage=stage)
        job = await client.create_job(project_id, prompt)
    except (PlatformApiError, KeyError) as error:
        return {"status": "submission_failed", "error": str(error), "can_retry": True}
    return {
        "status": "submitted",
        "skill_id": skill_id,
        "project_id": project_id,
        "job_id": str(job["id"]),
        "job_status": job.get("status", "queued"),
        "message": submitted_message,
        "conversation_id": conversation_id,
    }


@mcp.tool()
async def create_ppt_task(
    request: str,
    topic: str = "",
    audience: str = "",
    scenario: str = "",
    objective: str = "",
    page_range: str = "",
    style: str = "",
    notes: str = "",
    notes_enabled: bool = True,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """从自然语言需求收集信息；缺字段时返回追问，完整后异步提交 PPT 创作任务。"""
    original = _clean(request)
    values: dict[str, Any] = {
        "topic": _clean(topic, 160),
        "audience": _clean(audience, 500),
        "scenario": _clean(scenario, 500),
        "objective": _clean(objective, 1000),
        "page_range": _clean(page_range, 100),
        "style": _clean(style, 300),
        "notes": _clean(notes, 2000),
        "notes_enabled": notes_enabled,
    }
    if not original and not values["topic"]:
        return {"status": "needs_clarification", "missing_fields": ["topic"], "questions": _ppt_questions(["topic"])}
    missing = [field for field in PPT_REQUIRED_FIELDS if not values[field]]
    if missing:
        return {
            "status": "needs_clarification",
            "missing_fields": missing,
            "questions": _ppt_questions(missing),
            "conversation_id": conversation_id,
            "message": "请补充这些信息后再次调用 create_ppt_task。",
        }
    return await _submit_task(
        "ppt-master",
        values,
        _ppt_generation_prompt(values, original),
        conversation_id,
        "PPT 创作任务已异步提交，请使用 get_task_status 查询。",
    )


@mcp.tool()
async def create_doc_task(
    request: str,
    topic: str = "",
    doc_type: str = "",
    issuer: str = "",
    recipient: str = "",
    objective: str = "",
    style: str = "",
    notes: str = "",
    mode: str = "draft",
    content: str = "",
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """从自然语言需求收集信息；缺文种时返回追问，完整后异步提交公文任务（GB/T 9704 DOCX）。

    mode="draft"（默认）：按主题起草完整公文。mode="typeset"：排版已有内容，
    必须提供 content（公文正文全文，排版时逐字保留），此时 topic/doc_type 仍需提供。
    """
    original = _clean(request)
    doc_mode = "typeset" if str(mode).strip().lower() in {"typeset", "排版", "format"} else "draft"
    values: dict[str, Any] = {
        "topic": _clean(topic, 160),
        "doc_type": _clean(doc_type, 32),
        "issuer": _clean(issuer, 160),
        "recipient": _clean(recipient, 300),
        "objective": _clean(objective, 1000),
        "style": _clean(style, 300),
        "notes": _clean(notes, 2000),
    }
    if not original and not values["topic"]:
        return {"status": "needs_clarification", "missing_fields": ["topic"], "questions": _doc_questions(["topic"])}
    if doc_mode == "typeset":
        # Not capped short: the platform is the source of truth for a
        # verbatim-typesetting document's real length ceiling (its combined
        # job prompt tops out at 20,000 characters). Truncating here would
        # silently drop the tail of a "must reproduce exactly" document
        # instead of surfacing a clear, actionable error.
        body = _clean(content, 100_000)
        if not body:
            return {
                "status": "needs_clarification",
                "missing_fields": ["content"],
                "questions": _doc_questions(["content"]),
                "conversation_id": conversation_id,
                "message": "排版模式需要公文正文内容，请补充后再次调用 create_doc_task。",
            }
        missing = [field for field in DOC_REQUIRED_FIELDS if not values[field]]
        if missing:
            return {
                "status": "needs_clarification",
                "missing_fields": missing,
                "questions": _doc_questions(missing),
                "conversation_id": conversation_id,
                "message": "请补充这些信息后再次调用 create_doc_task。",
            }
        # The platform reconstructs the authoritative typeset job prompt
        # itself from requirements.content (see gongwen typeset handling in
        # create_job): it treats the submitted prompt as a short "用户补充"
        # note, not the document body. content must live in requirements or
        # the platform sees an empty body regardless of what prompt is sent.
        values["content"] = body
        return await _submit_task(
            "gongwen",
            values,
            original,
            conversation_id,
            "公文排版任务已异步提交，正文将逐字排版，请使用 get_task_status 查询。",
            mode=doc_mode,
            stage="content",
        )
    missing = [field for field in DOC_REQUIRED_FIELDS if not values[field]]
    if missing:
        return {
            "status": "needs_clarification",
            "missing_fields": missing,
            "questions": _doc_questions(missing),
            "conversation_id": conversation_id,
            "message": "请补充这些信息后再次调用 create_doc_task。",
        }
    return await _submit_task(
        "gongwen",
        values,
        _doc_generation_prompt(values, original),
        conversation_id,
        "公文写作任务已异步提交，请使用 get_task_status 查询。",
        mode=doc_mode,
    )


async def _task_status(project_id: str, job_id: str) -> dict[str, Any]:
    """Shared status path: generic wording, skill-aware deliverable lookup."""

    jobs = await client.list_jobs(project_id)
    job = _job_by_id(jobs, job_id)
    if not job:
        return {"status": "not_found", "error": "未找到该任务。"}
    status = str(job.get("status", "unknown"))
    result: dict[str, Any] = {
        "status": status,
        "skill_id": job.get("skill_id"),
        "project_id": project_id,
        "job_id": job_id,
        "error": job.get("error"),
        "created_at": job.get("created_at"),
    }
    if status in {"queued", "running"}:
        result["message"] = "任务仍在生成，请稍后使用同一 project_id 和 job_id 查询。"
        return result
    if status in {"failed", "cancelled"}:
        result.update({"can_retry": True, "retry_hint": "调用 retry_task 创建新的任务；原任务不会被修改。"})
        if status == "cancelled":
            result["message"] = "任务已中止；如果存在检查点，retry_task 会继续生成，否则请重新提交。"
        else:
            result["message"] = "任务失败；可以重新提交，失败原因已保留在 error 字段。"
        return result
    if status != "succeeded":
        result["message"] = "任务处于未知状态，请稍后重试查询。"
        return result
    listed = await client.list_artifacts(project_id, job_id)
    result["artifact_count"] = len(listed)
    primary_kind, *fallback_kinds = await skill_meta.candidates(str(job.get("skill_id") or ""))
    deliverable = next(
        (item for kind in (primary_kind, *fallback_kinds) for item in listed if str(item.get("kind", "")).lower() == kind),
        None,
    )
    if not deliverable:
        result.update({"status": "succeeded_without_deliverable", "message": "任务已结束，但暂未检测到交付产物。", "can_retry": True})
        return result
    content, media_type = await client.download_artifact(project_id, job_id, str(deliverable["id"]))
    default_name = "document.docx" if primary_kind == "docx" else "presentation.pptx"
    stored = artifacts.create(str(deliverable.get("filename") or default_name), content, media_type)
    result.update({
        "deliverable_kind": primary_kind,
        "filename": stored.filename,
        "download_url": f"{config.MCP_PUBLIC_BASE_URL}/downloads/{stored.token}",
        "expires_at": stored.expires_at.isoformat(),
        "message": "任务已完成，可通过 download_url 下载交付文件。",
    })
    if primary_kind == "docx":
        pdf = next((item for item in listed if str(item.get("kind", "")).lower() == "pdf"), None)
        if pdf:
            pdf_content, pdf_media_type = await client.download_artifact(project_id, job_id, str(pdf["id"]))
            pdf_stored = artifacts.create(str(pdf.get("filename") or "document.pdf"), pdf_content, pdf_media_type)
            result["pdf_download_url"] = f"{config.MCP_PUBLIC_BASE_URL}/downloads/{pdf_stored.token}"
            result["message"] = "任务已完成；download_url 为 DOCX 交付文件，pdf_download_url 为排版 PDF 版本。"
    return result


@mcp.tool()
async def get_task_status(project_id: str, job_id: str) -> dict[str, Any]:
    """查询创作任务状态（PPT 与公文通用）；成功时生成短时交付文件下载链接。"""
    try:
        return await _task_status(project_id, job_id)
    except PlatformApiError as error:
        if error.status_code == 404:
            return {"status": "not_found", "project_id": project_id, "job_id": job_id, "error": str(error)}
        return {"status": "query_failed", "project_id": project_id, "job_id": job_id, "error": str(error), "can_retry": False}


@mcp.tool()
async def retry_task(project_id: str, job_id: str) -> dict[str, Any]:
    """重试失败任务，或从有检查点的取消任务创建新的继续任务（PPT 与公文通用）。"""
    try:
        jobs = await client.list_jobs(project_id)
        base = _job_by_id(jobs, job_id)
        if not base:
            return {"status": "not_found", "error": "未找到要重试的任务。"}
        status = str(base.get("status", ""))
        if status not in {"failed", "cancelled"}:
            return {"status": "not_retryable", "error": "只有 failed 或 cancelled 任务可以重试。", "job_status": status}
        if status == "cancelled":
            new_job = await client.resume_cancelled_job(project_id, job_id)
        else:
            new_job = await client.create_job(project_id, str(base.get("prompt") or ""), base_job_id=job_id)
        return {"status": "submitted", "project_id": project_id, "base_job_id": job_id, "job_id": str(new_job["id"]), "job_status": new_job.get("status", "queued"), "message": "已创建新的重试任务，原任务保持不变。"}
    except PlatformApiError as error:
        if error.status_code == 404:
            return {"status": "not_found", "project_id": project_id, "job_id": job_id, "error": str(error)}
        return {"status": "retry_failed", "project_id": project_id, "job_id": job_id, "error": str(error), "can_retry": True}


def _run_http() -> None:
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import FileResponse, JSONResponse

    mcp.settings.host = config.MCP_HOST
    mcp.settings.port = config.MCP_PORT
    app = mcp.streamable_http_app()

    class ApiKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any):
            if request.url.path.startswith("/downloads/"):
                return await call_next(request)
            provided = request.query_params.get("api_key", "")
            if not provided:
                provided = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(provided, config.MCP_API_KEY):
                return JSONResponse({"error": "invalid api_key"}, status_code=401)
            return await call_next(request)

    async def download(request: Request):
        artifact = artifacts.get(request.path_params["token"])
        if not artifact:
            return JSONResponse({"error": "下载链接无效或已过期"}, status_code=404)
        return FileResponse(artifact.file_path, media_type=artifact.media_type, filename=artifact.filename)

    app.add_route("/downloads/{token}", download, methods=["GET"])
    app.add_middleware(ApiKeyMiddleware)
    log.info("MCP HTTP listening at %s/mcp", config.MCP_PUBLIC_BASE_URL)
    uvicorn.run(app, host=config.MCP_HOST, port=config.MCP_PORT, access_log=False)


def main() -> None:
    if config.MCP_TRANSPORT == "stdio":
        mcp.run(transport="stdio")
    else:
        _run_http()


if __name__ == "__main__":
    main()
