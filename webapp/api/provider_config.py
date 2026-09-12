"""Encryption and OpenCode configuration generation for managed providers."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from .config import get_settings
from .models import ImageProvider, Provider, ProviderModel

# The 14 backends image_gen.py supports (skills/ppt-master/scripts/image_backends/).
# Each follows the same {BACKEND}_API_KEY / _BASE_URL / _MODEL env-var contract,
# confirmed by inspecting every backend_*.py module; no per-backend mapping table
# is needed beyond this allowlist used for admin-input validation.
IMAGE_BACKEND_CHOICES = (
    "gemini", "openai", "qwen", "volcengine", "zhipu",
    "bfl", "ideogram", "stability",
    "fal", "minimax", "modelscope", "openrouter", "replicate", "siliconflow",
)


def _cipher() -> Fernet:
    key = (get_settings().config_encryption_key or "").strip()
    if not key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "未配置 PPTMASTER_CONFIG_ENCRYPTION_KEY")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "PPTMASTER_CONFIG_ENCRYPTION_KEY 无效") from exc


def encrypt_api_key(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_api_key(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Provider API Key 无法解密") from exc


def key_hint(value: str) -> str:
    return "已配置" if len(value) < 8 else f"{value[:3]}...{value[-4:]}"


def _provider_block(provider: Provider, model: ProviderModel) -> dict:
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": provider.display_name,
        "options": {"baseURL": provider.base_url, "apiKey": decrypt_api_key(provider.api_key_ciphertext)},
        "models": {model.model_id: {"name": model.display_name}},
    }


def opencode_config(
    provider: Provider,
    model: ProviderModel,
    vision_provider: Provider | None = None,
    vision_model: ProviderModel | None = None,
) -> dict:
    """Return one least-privilege OpenCode config for a single queued model.

    When a vision model is configured, register it as an independent
    `image-reviewer` subagent (OpenCode's `agent` block supports a per-agent
    `model` override, and the primary agent's built-in `task` tool can
    dispatch to it by name) so image candidate review can use a different
    model than the main generation run without switching the whole job over.
    """

    providers = {provider.slug: _provider_block(provider, model)}
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "disabled_providers": ["opencode"],
        "permission": {
            "edit": "allow",
            "bash": "allow",
            "webfetch": "allow",
            "external_directory": "allow",
        },
        "provider": providers,
        "model": f"{provider.slug}/{model.model_id}",
    }
    if vision_provider is not None and vision_model is not None:
        if vision_provider.slug == provider.slug:
            providers[provider.slug]["models"][vision_model.model_id] = {"name": vision_model.display_name}
        else:
            providers[vision_provider.slug] = _provider_block(vision_provider, vision_model)
        config["agent"] = {
            "image-reviewer": {"model": f"{vision_provider.slug}/{vision_model.model_id}"}
        }
    return config


def image_backend_environment(image_provider: ImageProvider, api_key: str) -> dict[str, str]:
    """Build the env vars image_gen.py expects for one configured backend.

    Every backend module (skills/ppt-master/scripts/image_backends/*.py) reads
    {BACKEND}_API_KEY / _BASE_URL / _MODEL, so this needs no per-backend table.
    """

    prefix = image_provider.backend.upper()
    env = {"IMAGE_BACKEND": image_provider.backend, f"{prefix}_API_KEY": api_key}
    if image_provider.base_url_override:
        env[f"{prefix}_BASE_URL"] = image_provider.base_url_override
    if image_provider.model_override:
        env[f"{prefix}_MODEL"] = image_provider.model_override
    return env
