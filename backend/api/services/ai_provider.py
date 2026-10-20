"""Provider selection and text/vision request helpers for AI services."""

import base64
import re

from django.conf import settings


PROVIDER_ALIASES = {
    "gemini": "gemini",
    "claude": "claude",
    "anthropic": "claude",
    "openai": "openai",
    "codex": "openai",
}


class AIProviderConfigurationError(RuntimeError):
    pass


def get_provider_config():
    configured_name = getattr(settings, "AI_PROVIDER", "gemini").strip().lower()
    provider = PROVIDER_ALIASES.get(configured_name)
    if not provider:
        supported = ", ".join(PROVIDER_ALIASES)
        raise AIProviderConfigurationError(
            f"Unknown AI_PROVIDER '{configured_name}'. Choose one of: {supported}."
        )

    config = {
        "gemini": (
            getattr(settings, "GEMINI_API_KEY", ""),
            getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash"),
        ),
        "claude": (
            getattr(settings, "ANTHROPIC_API_KEY", ""),
            getattr(settings, "ANTHROPIC_MODEL", "claude-sonnet-5"),
        ),
        "openai": (
            getattr(settings, "OPENAI_API_KEY", ""),
            getattr(
                settings,
                "CODEX_MODEL" if configured_name == "codex" else "OPENAI_MODEL",
                "gpt-5.1-codex" if configured_name == "codex" else "gpt-5.1",
            ),
        ),
    }
    api_key, model = config[provider]
    return configured_name, provider, api_key.strip(), model.strip()


def provider_has_api_key():
    return bool(get_provider_config()[2])


def generate_text(prompt, image_data_uri=None):
    configured_name, provider, api_key, model = get_provider_config()
    if not api_key:
        key_names = {
            "gemini": "GEMINI_API_KEY",
            "claude": "ANTHROPIC_API_KEY (or CLAUDE_API_KEY)",
            "openai": "OPENAI_API_KEY (or CODEX_API_KEY)",
        }
        raise AIProviderConfigurationError(
            f"AI_PROVIDER is '{configured_name}', but {key_names[provider]} is not set."
        )

    if provider == "claude":
        return _generate_with_claude(api_key, model, prompt, image_data_uri)

    return _generate_with_openai_compatible(
        provider, api_key, model, prompt, image_data_uri
    )


def _generate_with_openai_compatible(provider, api_key, model, prompt, image_data_uri):
    from openai import OpenAI

    client_options = {"api_key": api_key}
    if provider == "gemini":
        client_options["base_url"] = (
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
    client = OpenAI(**client_options)

    content = prompt
    if image_data_uri:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_uri}},
        ]

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
    )
    return response.choices[0].message.content or ""


def _generate_with_claude(api_key, model, prompt, image_data_uri):
    from anthropic import Anthropic

    content = [{"type": "text", "text": prompt}]
    if image_data_uri:
        match = re.fullmatch(
            r"data:(image/[a-zA-Z0-9.+-]+);base64,(.+)",
            image_data_uri,
            flags=re.DOTALL,
        )
        if not match:
            raise ValueError("Claude reference images must be base64 image data.")
        media_type, encoded_image = match.groups()
        try:
            base64.b64decode(encoded_image, validate=True)
        except ValueError as exc:
            raise ValueError("The reference image is not valid base64 data.") from exc
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded_image,
            },
        })

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=getattr(settings, "AI_MAX_TOKENS", 8192),
        messages=[{"role": "user", "content": content}],
    )
    return "\n".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
