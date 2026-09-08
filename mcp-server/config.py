"""Environment-backed configuration for the 智创AI专家 MCP server."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))

MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1").strip()
MCP_PORT = int(os.getenv("MCP_PORT", "7010"))
MCP_API_KEY = os.getenv("MCP_API_KEY", "").strip()
MCP_PUBLIC_BASE_URL = os.getenv(
    "MCP_PUBLIC_BASE_URL", f"http://{MCP_HOST}:{MCP_PORT}"
).rstrip("/")
PPTMASTER_API_URL = os.getenv("PPTMASTER_API_URL", "http://127.0.0.1:8080").rstrip("/")
PPTMASTER_USERNAME = os.getenv("PPTMASTER_USERNAME", "").strip()
PPTMASTER_PASSWORD = os.getenv("PPTMASTER_PASSWORD", "")
PPTMASTER_SESSION_COOKIE_NAME = os.getenv("PPTMASTER_SESSION_COOKIE_NAME", "pm_session").strip()
ARTIFACT_TTL_MINUTES = int(os.getenv("ARTIFACT_TTL_MINUTES", "15"))
API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "30"))


def validate() -> None:
    if MCP_TRANSPORT not in {"stdio", "streamable-http"}:
        raise ValueError("MCP_TRANSPORT must be stdio or streamable-http")
    if not 1 <= MCP_PORT <= 65535:
        raise ValueError("MCP_PORT must be between 1 and 65535")
    if not PPTMASTER_API_URL.startswith(("http://", "https://")):
        raise ValueError("PPTMASTER_API_URL must use HTTP or HTTPS")
    if not PPTMASTER_USERNAME or not PPTMASTER_PASSWORD:
        raise ValueError("PPTMASTER_USERNAME and PPTMASTER_PASSWORD are required")
    if not MCP_PUBLIC_BASE_URL.startswith(("http://", "https://")):
        raise ValueError("MCP_PUBLIC_BASE_URL must use HTTP or HTTPS")
    if MCP_TRANSPORT == "streamable-http" and not MCP_API_KEY:
        raise ValueError("MCP_API_KEY is required for streamable-http mode")
    if not 1 <= ARTIFACT_TTL_MINUTES <= 1440:
        raise ValueError("ARTIFACT_TTL_MINUTES must be between 1 and 1440")
    if not 1 <= API_TIMEOUT_SECONDS <= 300:
        raise ValueError("API_TIMEOUT_SECONDS must be between 1 and 300")
