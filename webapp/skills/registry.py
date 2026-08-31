"""Manifest loader for platform-registered skills.

Stdlib-only so both the API (FastAPI) and the runner (Celery) can import it.
Manifests live in this package, one directory per skill:

    webapp/skills/<skill_id>/skill.manifest.json

The manifest root is resolved relative to this file, which lands at
``/app/webapp/skills`` inside both the web and runner images (their WORKDIR
is ``/app/webapp``), and at ``webapp/skills`` in a dev checkout. No settings
or environment variables are involved.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "skill.manifest.json"

# Minimal shape contract. Anything deeper (per-feature gates, frontend copy)
# is read defensively by consumers so partially-filled manifests degrade
# gracefully instead of crashing the API.
REQUIRED_KEYS = ("schema_version", "skill_id", "display_name", "enabled")


def skill_manifest_root() -> Path:
    return Path(__file__).resolve().parent


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable skill manifest %s: %s", path, exc)
        return None
    if not isinstance(manifest, dict):
        logger.warning("Ignoring non-object skill manifest %s", path)
        return None
    missing = [key for key in REQUIRED_KEYS if key not in manifest]
    if missing:
        logger.warning("Ignoring skill manifest %s, missing keys: %s", path, missing)
        return None
    if manifest["skill_id"] != path.parent.name:
        logger.warning(
            "Ignoring skill manifest %s: skill_id %r does not match directory name",
            path,
            manifest["skill_id"],
        )
        return None
    return manifest


def list_skill_manifests() -> list[dict[str, Any]]:
    """Return all valid skill manifests, sorted by display name."""
    manifests: list[dict[str, Any]] = []
    for path in sorted(skill_manifest_root().glob(f"*/{MANIFEST_FILENAME}")):
        manifest = _load_manifest(path)
        if manifest is not None:
            manifests.append(manifest)
    manifests.sort(key=lambda item: str(item.get("display_name", "")))
    return manifests


def get_skill_manifest(skill_id: str) -> dict[str, Any] | None:
    """Return the manifest for ``skill_id``, or None when unknown/invalid."""
    if not skill_id or "/" in skill_id or "\\" in skill_id or skill_id in {".", ".."}:
        return None
    path = skill_manifest_root() / skill_id / MANIFEST_FILENAME
    if not path.is_file():
        return None
    return _load_manifest(path)


# Deploy-skew fallback so jobs for the historically only skill keep running
# even while an image without baked manifests is still up.
_LEGACY_PPT_MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "skill_id": "ppt-master",
    "workspace": {
        "continue_seed_dir": "ppt-project",
        "fresh_root_suffix": "ppt169",
        "authoring_root": {"marker_dir": "svg_output"},
    },
    "artifacts": [
        {
            "kind": "svg",
            "glob": "svg_output/*.svg",
            "content_type": "image/svg+xml",
        },
        {
            "kind": "pptx",
            "glob": "exports/*.pptx",
            "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        },
    ],
}


def skill_manifest_for(skill_id: str) -> dict[str, Any]:
    """Resolve a job's manifest, falling back to ppt-master for deploy skew."""

    manifest = get_skill_manifest(skill_id)
    if manifest is not None:
        return manifest
    if skill_id == "ppt-master":
        return _LEGACY_PPT_MANIFEST
    raise KeyError(f"No skill manifest registered for {skill_id!r}")


def marker_dir(manifest: dict[str, Any]) -> str:
    """Directory that identifies a skill's authoring root inside a job workspace."""

    return str(((manifest.get("workspace") or {}).get("authoring_root") or {}).get("marker_dir") or "")


def continue_seed_dir(manifest: dict[str, Any]) -> str:
    """Stable authoring-root name a continuation job is seeded into."""

    return str((manifest.get("workspace") or {}).get("continue_seed_dir") or "")


def artifact_rules(manifest: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Split manifest artifact globs into (directory, pattern, kind, content_type).

    Only the leading path segment is the directory; the remainder (including
    any recursive ``**`` markers) stays part of the pattern handed to pathlib.
    """

    rules: list[tuple[str, str, str, str]] = []
    for entry in manifest.get("artifacts", []):
        parts = str(entry["glob"]).split("/")
        directory, pattern = parts[0], "/".join(parts[1:])
        rules.append((directory, pattern, str(entry["kind"]), str(entry["content_type"])))
    return rules
