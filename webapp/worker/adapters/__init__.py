"""Skill-adapter registry for the worker.

Adapters carry every skill-specific behavior: workspace init, agent steering,
workspace verification, snapshots, artifact emission, and revision validation.
The runner picks the adapter indirectly by sending the job's manifest; this
registry refuses unknown adapters explicitly so an older worker image fails
loudly instead of misbehaving against a newer manifest.
"""

from __future__ import annotations

import importlib

from worker.runtime import emit

# manifest validation_adapter -> adapter module under worker.adapters
VALIDATION_ADAPTERS = {
    "ppt_revision": "ppt_master",
    "gongwen_docx": "gongwen",
}

# manifest agent.prompt_strategy -> adapter module that owns the prompt
PROMPT_STRATEGIES = {
    "ppt_quick_generate": "ppt_master",
    "gongwen_quick": "gongwen",
}

SUPPORTED_SCHEMA_VERSION = 1


def get_adapter(skill_id: str, manifest: dict | None):
    """Return the adapter module for a manifest, or None after emitting an error."""

    if manifest is None:
        # A runner predating the manifest contract: only ppt-master is safe.
        if skill_id == "ppt-master":
            return importlib.import_module("worker.adapters.ppt_master")
        emit(
            "error",
            message=(
                f"Runner 未提供 skill manifest，且 worker 无法为 {skill_id!r} 选择默认适配器；"
                "请升级 runner 镜像后重试。"
            ),
        )
        return None
    schema_version = manifest.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        emit(
            "error",
            message=(
                f"Skill manifest schema_version {schema_version!r} 不受当前 worker 支持"
                f"（支持 {SUPPORTED_SCHEMA_VERSION}）；请重建 worker 镜像。"
            ),
        )
        return None
    validation_adapter = str(manifest.get("validation_adapter") or "")
    prompt_strategy = str((manifest.get("agent") or {}).get("prompt_strategy") or "")
    module_name = VALIDATION_ADAPTERS.get(validation_adapter)
    if module_name is None or PROMPT_STRATEGIES.get(prompt_strategy) != module_name:
        emit(
            "error",
            message=(
                f"当前 worker 镜像不支持 skill {manifest.get('skill_id')!r} 的适配器组合"
                f"（validation_adapter={validation_adapter!r}, prompt_strategy={prompt_strategy!r}）；"
                "请重建 worker 镜像。"
            ),
        )
        return None
    return importlib.import_module(f"worker.adapters.{module_name}")
