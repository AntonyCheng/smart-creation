"""Platform-side skill registry.

Manifests describe how the platform drives each skill under ``skills/``.
They are platform-owned assets and deliberately live outside ``skills/`` so
that upstream skill syncs never touch them.
"""

from skills.registry import (
    MANIFEST_FILENAME,
    get_skill_manifest,
    list_skill_manifests,
    skill_manifest_root,
)

__all__ = [
    "MANIFEST_FILENAME",
    "get_skill_manifest",
    "list_skill_manifests",
    "skill_manifest_root",
]
