"""Claude API client wrapper — thin layer over the Anthropic SDK."""

from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Minimal wrapper around the Anthropic Messages API.

    Usage::

        client = ClaudeClient()
        reply = await client.chat(
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello"}],
        )
    """

    def __init__(self):
        self._api_key = settings.anthropic_api_key
        self._model = settings.llm_model
        self._client: Any = None

    # ── lazy init ──────────────────────────────────────────────

    async def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )

    # ── public API ─────────────────────────────────────────────

    async def chat(
        self,
        system: str | None = None,
        messages: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: type | None = None,
    ) -> str:
        """Send a chat request and return the text response."""
        await self._ensure_client()
        kwargs = {
            "model": self._model,
            "max_tokens": max_tokens or settings.llm_max_tokens,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
            "messages": messages or [],
        }
        if system:
            kwargs["system"] = system
        if response_format:

            kwargs["extra_headers"] = {
                "anthropic-beta": "output-128k-2025-05-02"
            }

        resp = await self._client.messages.create(**kwargs)
        return resp.content[0].text if resp.content else ""

    async def chat_structured(
        self,
        system: str | None,
        messages: list[dict],
        response_model: type,
    ) -> Any:
        """Request a structured (JSON) response and parse it."""
        text = await self.chat(
            system=system,
            messages=messages,
        )
        # Try to extract JSON from the response
        text = text.strip()
        if text.startswith("```"):
            # strip markdown fences
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM response was not valid JSON, returning raw text")
            return text
        if response_model is not None and isinstance(data, dict):
            return response_model(**data)
        return data

    async def validate_connection(self) -> bool:
        """Check whether the API key is usable."""
        try:
            await self._ensure_client()
            await self._client.models.list()
            return True
        except Exception as exc:
            logger.warning("LLM connection check failed: %s", exc)
            return False
