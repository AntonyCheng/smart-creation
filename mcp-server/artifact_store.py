"""Short-lived local storage for PPTX files returned by the MCP service."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class StoredArtifact:
    token: str
    filename: str
    media_type: str
    file_path: Path
    expires_at: datetime


class ArtifactStore:
    def __init__(self, root: Path, ttl_minutes: int) -> None:
        self.root = root
        self.ttl = timedelta(minutes=ttl_minutes)
        self._items: dict[str, StoredArtifact] = {}
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, filename: str, content: bytes, media_type: str) -> StoredArtifact:
        self.purge_expired()
        token = secrets.token_urlsafe(32)
        path = self.root / token
        path.write_bytes(content)
        item = StoredArtifact(token, Path(filename).name or "presentation.pptx", media_type, path, datetime.now(UTC) + self.ttl)
        self._items[token] = item
        return item

    def get(self, token: str) -> StoredArtifact | None:
        if not token or not token.replace("-", "").replace("_", "").isalnum():
            return None
        path = self.root / token
        if not path.is_file():
            return None
        # Expiry is encoded by a sidecar mtime-free index in memory only for this process.
        item = self._items.get(token)
        if not item or item.expires_at <= datetime.now(UTC):
            path.unlink(missing_ok=True)
            self._items.pop(token, None)
            return None
        return item

    def purge_expired(self) -> None:
        now = datetime.now(UTC)
        for token, item in list(self._items.items()):
            if item.expires_at <= now:
                item.file_path.unlink(missing_ok=True)
                self._items.pop(token, None)
