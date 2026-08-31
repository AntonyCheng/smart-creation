"""PPT Master MCP facade.

The MCP layer deliberately stays thin: the host model gathers requirements and
asks follow-up questions, while PPT Master remains the source of truth for
authentication, task execution, artifacts, and retry semantics.
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
from pptmaster_client import PptMasterApiError, PptMasterClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("ppt-master-mcp")
config.validate()
client = PptMasterClient()
artifacts = ArtifactStore(Path(__file__).with_name("artifacts"), config.ARTIFACT_TTL_MINUTES)
mcp = FastMCP(
    "ppt-master-mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

REQUIRED_FIELDS = ("topic", "audience", "scenario", "objective")


def _clean(value: str | None, limit: int = 4000) -> str:
    return (value or "").strip()[:limit]


def _questions(missing: list[str]) -> list[str]:
    labels = {
        "topic": "这份 PPT 的主题或核心问题是什么？",
        "audience": "这份 PPT 主要面向哪些人？",
        "scenario": "这份 PPT 会在什么场景下使用，例如汇报、培训或课堂？",
        "objective": "希望观众最终理解什么，或采取什么行动？",
    }
    return [labels[field] for field in missing]


def _generation_prompt(values: dict[str, Any], request: str) -> str:
    page_range = _clean(values.get("page_range"), 100) or "由内容完整性决定，不强制固定页数"
    style = _clean(values.get("style"), 300) or "专业、简洁、结论先行"
    return (
        "请根据以下已确认需求生成一份可编辑 PPT。页数由内容决定，不要为了满足页数范围添加空泛页面；"
        "完成后保留真实生成页数。\n\n"
        f"主题：{values['topic']}\n受众：{values['audience']}\n使用场景：{values['scenario']}\n"
        f"目标：{values['objective']}\n页数偏好：{page_range}\n视觉风格：{style}\n"
        f"备注：{_clean(values.get('notes'), 2000)}\n原始需求：{_clean(request, 4000)}"
    )


def _job_by_id(jobs: list[dict[str, Any]], job_id: str) -> dict[str, Any] | None:
    return next((job for job in jobs if str(job.get("id")) == job_id), None)


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
    """从自然语言需求收集信息；缺字段时返回追问，完整后异步提交 PPT 任务。"""
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
        return {"status": "needs_clarification", "missing_fields": ["topic"], "questions": _questions(["topic"])}
    missing = [field for field in REQUIRED_FIELDS if not values[field]]
    if missing:
        return {
            "status": "needs_clarification",
            "missing_fields": missing,
            "questions": _questions(missing),
            "conversation_id": conversation_id,
            "message": "请补充这些信息后再次调用 create_ppt_task。",
        }
    try:
        project = await client.create_project(values["topic"])
        project_id = str(project["id"])
        await client.save_requirements(project_id, values)
        job = await client.create_job(project_id, _generation_prompt(values, original))
    except (PptMasterApiError, KeyError) as error:
        return {"status": "submission_failed", "error": str(error), "can_retry": True}
    return {
        "status": "submitted",
        "project_id": project_id,
        "job_id": str(job["id"]),
        "job_status": job.get("status", "queued"),
        "message": "PPT 创建任务已异步提交，请使用 get_ppt_task_status 查询。",
        "conversation_id": conversation_id,
    }


@mcp.tool()
async def get_ppt_task_status(project_id: str, job_id: str) -> dict[str, Any]:
    """查询任务状态；成功时生成短时 PPTX 下载链接。"""
    try:
        jobs = await client.list_jobs(project_id)
        job = _job_by_id(jobs, job_id)
        if not job:
            return {"status": "not_found", "error": "未找到该 PPT 任务。"}
        status = str(job.get("status", "unknown"))
        result: dict[str, Any] = {
            "status": status,
            "project_id": project_id,
            "job_id": job_id,
            "error": job.get("error"),
            "created_at": job.get("created_at"),
        }
        if status in {"queued", "running"}:
            result["message"] = "PPT 仍在生成，请稍后使用同一 project_id 和 job_id 查询。"
            return result
        if status in {"failed", "cancelled"}:
            result.update({"can_retry": True, "retry_hint": "调用 retry_ppt_task 创建新的任务；原任务不会被修改。"})
            if status == "cancelled":
                result["message"] = "任务已中止；如果存在检查点，retry_ppt_task 会继续生成，否则请重新提交。"
            else:
                result["message"] = "任务失败；可以重新提交，失败原因已保留在 error 字段。"
            return result
        if status != "succeeded":
            result["message"] = "任务处于未知状态，请稍后重试查询。"
            return result
        listed = await client.list_artifacts(project_id, job_id)
        pptx = next((item for item in listed if str(item.get("kind", "")).lower() == "pptx"), None)
        result["artifact_count"] = len(listed)
        if not pptx:
            result.update({"status": "succeeded_without_pptx", "message": "任务已结束，但暂未检测到 PPTX 产物。", "can_retry": True})
            return result
        content, media_type = await client.download_artifact(project_id, job_id, str(pptx["id"]))
        stored = artifacts.create(str(pptx.get("filename") or "presentation.pptx"), content, media_type)
        result.update({
            "filename": stored.filename,
            "download_url": f"{config.MCP_PUBLIC_BASE_URL}/downloads/{stored.token}",
            "expires_at": stored.expires_at.isoformat(),
            "message": "PPT 已生成，可通过 download_url 下载。",
        })
        return result
    except PptMasterApiError as error:
        return {"status": "query_failed", "project_id": project_id, "job_id": job_id, "error": str(error), "can_retry": False}


@mcp.tool()
async def retry_ppt_task(project_id: str, job_id: str) -> dict[str, Any]:
    """重试失败任务，或从有检查点的取消任务创建新的继续任务。"""
    try:
        jobs = await client.list_jobs(project_id)
        base = _job_by_id(jobs, job_id)
        if not base:
            return {"status": "not_found", "error": "未找到要重试的 PPT 任务。"}
        status = str(base.get("status", ""))
        if status not in {"failed", "cancelled"}:
            return {"status": "not_retryable", "error": "只有 failed 或 cancelled 任务可以重试。", "job_status": status}
        if status == "cancelled":
            new_job = await client.resume_cancelled_job(project_id, job_id)
        else:
            new_job = await client.create_job(project_id, str(base.get("prompt") or ""), base_job_id=job_id)
        return {"status": "submitted", "project_id": project_id, "base_job_id": job_id, "job_id": str(new_job["id"]), "job_status": new_job.get("status", "queued"), "message": "已创建新的重试任务，原任务保持不变。"}
    except PptMasterApiError as error:
        return {"status": "retry_failed", "project_id": project_id, "base_job_id": job_id, "error": str(error), "can_retry": True}


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
            return JSONResponse({"error": "download link is invalid or expired"}, status_code=404)
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
