"""Authenticated HTTP client for the 智创AI专家 platform API."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

import config


class PlatformApiError(RuntimeError):
    """A safe, user-facing error returned by the platform API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PlatformClient:
    def __init__(self) -> None:
        self._base_url = config.PPTMASTER_API_URL
        self._cookies: dict[str, str] = {}
        self._login_lock = asyncio.Lock()

    async def _login(self) -> None:
        async with self._login_lock:
            if self._cookies.get(config.PPTMASTER_SESSION_COOKIE_NAME):
                return
            try:
                async with httpx.AsyncClient(timeout=config.API_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self._base_url}/api/v1/auth/login",
                        json={"username": config.PPTMASTER_USERNAME, "password": config.PPTMASTER_PASSWORD},
                    )
            except httpx.HTTPError as error:
                raise PlatformApiError("无法连接智创AI专家平台") from error
            if response.is_error:
                raise self._error(response, "平台登录失败")
            token = response.cookies.get(config.PPTMASTER_SESSION_COOKIE_NAME)
            if not token:
                raise PlatformApiError("平台登录成功但没有返回会话 Cookie")
            self._cookies = {config.PPTMASTER_SESSION_COOKIE_NAME: token}

    @staticmethod
    def _error(response: httpx.Response, fallback: str) -> PlatformApiError:
        message = fallback
        try:
            payload = response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if isinstance(detail, str) and detail:
                message = detail
            elif isinstance(detail, list) and detail:
                message = "; ".join(str(item.get("msg", item)) for item in detail)
        except (ValueError, TypeError):
            pass
        return PlatformApiError(message, response.status_code)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        await self._login()
        try:
            async with httpx.AsyncClient(
                timeout=config.API_TIMEOUT_SECONDS,
                cookies=self._cookies,
            ) as client:
                response = await client.request(method, f"{self._base_url}{path}", **kwargs)
        except httpx.HTTPError as error:
            raise PlatformApiError("无法连接智创AI专家平台") from error
        if response.status_code == 401:
            self._cookies = {}
            await self._login()
            try:
                async with httpx.AsyncClient(timeout=config.API_TIMEOUT_SECONDS, cookies=self._cookies) as client:
                    response = await client.request(method, f"{self._base_url}{path}", **kwargs)
            except httpx.HTTPError as error:
                raise PlatformApiError("无法连接智创AI专家平台") from error
        if response.is_error:
            raise self._error(response, "平台请求失败")
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise PlatformApiError("平台返回了无法解析的响应") from error

    async def list_skills(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/api/v1/skills")

    async def create_project(self, title: str, skill_id: str = "ppt-master", mode: str | None = None) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v1/projects",
            json={"title": title, "skill_id": skill_id, "mode": mode, "prompt_snippet_id": None},
        )

    async def save_requirements(
        self, project_id: str, requirements: dict[str, Any], stage: str = "requirements"
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/api/v1/projects/{project_id}/creative-state",
            json={"stage": stage, "requirements": requirements, "notes_enabled": bool(requirements.get("notes_enabled", True))},
        )

    async def create_job(self, project_id: str, prompt: str, base_job_id: str | None = None) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/projects/{project_id}/jobs",
            json={"prompt": prompt, "template_id": None, "base_job_id": base_job_id, "resume_from_cancelled": False, "target_slide_number": None},
        )

    async def resume_cancelled_job(self, project_id: str, job_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/projects/{project_id}/jobs/{job_id}/resume")

    async def list_jobs(self, project_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/api/v1/projects/{project_id}/jobs")

    async def list_artifacts(self, project_id: str, job_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/api/v1/projects/{project_id}/jobs/{job_id}/artifacts")

    async def download_artifact(self, project_id: str, job_id: str, artifact_id: str) -> tuple[bytes, str]:
        await self._login()
        try:
            async with httpx.AsyncClient(timeout=max(config.API_TIMEOUT_SECONDS, 120), cookies=self._cookies) as client:
                response = await client.get(f"{self._base_url}/api/v1/projects/{project_id}/jobs/{job_id}/artifacts/{artifact_id}/download")
        except httpx.HTTPError as error:
            raise PlatformApiError("无法连接智创AI专家平台") from error
        if response.is_error:
            raise self._error(response, "产物下载失败")
        return response.content, response.headers.get("content-type", "application/octet-stream")
