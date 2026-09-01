"""Cached skill metadata used to resolve each job's primary deliverable kind."""

from __future__ import annotations

import time

from client import PlatformApiError, PlatformClient

# Fallback priority when the platform skill registry cannot be reached.
FALLBACK_PRIORITY = ("pptx", "docx")
CACHE_TTL_SECONDS = 300.0


class SkillMeta:
    """Process-wide cache of the platform's skill manifests (read-only view)."""

    def __init__(self, client: PlatformClient) -> None:
        self._client = client
        self._by_id: dict[str, dict] = {}
        self._loaded_at: float = 0.0

    async def _ensure(self, *, force: bool = False) -> None:
        if not force and self._by_id and time.monotonic() - self._loaded_at < CACHE_TTL_SECONDS:
            return
        manifests = await self._client.list_skills()
        self._by_id = {str(item.get("id")): item for item in manifests if item.get("id")}
        self._loaded_at = time.monotonic()

    async def primary_kind(self, skill_id: str | None) -> str:
        """Return the skill's primary artifact kind, falling back sensibly."""

        skill_id = (skill_id or "").strip()
        try:
            await self._ensure(force=skill_id not in self._by_id)
        except PlatformApiError:
            return FALLBACK_PRIORITY[0]
        manifest = self._by_id.get(skill_id)
        if manifest:
            return str(manifest.get("primary_artifact_kind") or FALLBACK_PRIORITY[0])
        return FALLBACK_PRIORITY[0]

    async def candidates(self, skill_id: str | None) -> tuple[str, ...]:
        """Primary kind first, then the remaining fallback kinds in order."""

        primary = await self.primary_kind(skill_id)
        return (primary, *(kind for kind in FALLBACK_PRIORITY if kind != primary))
