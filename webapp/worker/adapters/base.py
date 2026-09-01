"""Skill-adapter contract shared by every per-skill worker module.

The worker container does not ship the platform's ``skills.registry`` package
(its ``/app/skills`` directory holds actual skill content), so each adapter
reads the runner-provided manifest directly. The runner is the authority: it
reads the baked manifest and hands one manifest per job through
``PPTMASTER_SKILL_MANIFEST_JSON``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class AdapterError(RuntimeError):
    """Raised when a job cannot proceed under the current adapter."""


@dataclass
class SkillContext:
    """Everything one adapter invocation needs for a single job."""

    skill_id: str
    manifest: dict | None
    prompt: str
    workspace: Path
    continue_mode: bool
    target_slide: int | None
    template_root: str
    mode: str | None = None
