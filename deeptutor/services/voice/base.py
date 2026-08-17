"""Base abstractions and shared helpers for voice providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging

from deeptutor.services.voice.config import (
    AUTH_API_KEY_HEADER,
    AUTH_TOKEN,
    STTConfig,
    TTSConfig,
)

logger = logging.getLogger(__name__)


class VoiceProviderError(RuntimeError):
    """Raised when a TTS/STT provider request fails or is misconfigured."""


class VoiceProviderHTTPError(VoiceProviderError):
    """Provider returned a non-2xx HTTP response."""

    def __init__(self, message: str, *, status_code: int, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class BaseTTSAdapter(ABC):
    """Abstract text-to-speech adapter."""

    @abstractmethod
    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        """Synthesize ``text`` to audio.

        Returns:
            ``(audio_bytes, content_type)`` — content type is best-effort, e.g.
            ``audio/mpeg`` for mp3.
        """


class BaseSTTAdapter(ABC):
    """Abstract speech-to-text adapter."""

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename: str = "audio.webm",
        content_type: str = "application/octet-stream",
    ) -> str:
        """Transcribe ``audio`` bytes to text."""


def build_auth_headers(auth_style: str, api_key: str) -> dict[str, str]:
    """Map an ``auth_style`` + key onto request headers.

    ``bearer`` (default) → ``Authorization: Bearer``; ``api_key_header`` →
    ``api-key`` (Azure); ``token`` → ``Authorization: Token`` (Deepgram-style).
    """
    if not api_key:
        return {}
    if auth_style == AUTH_API_KEY_HEADER:
        return {"api-key": api_key}
    if auth_style == AUTH_TOKEN:
        return {"Authorization": f"Token {api_key}"}
    return {"Authorization": f"Bearer {api_key}"}


def join_audio_path(base_url: str, suffix: str) -> str:
    """Append an OpenAI audio path to a configured base URL.

    ``base_url`` is the API base (e.g. ``https://api.openai.com/v1``). If the
    admin already pasted a full ``.../audio/...`` endpoint (some gateways /
    Azure deployments), it is used verbatim and the query string preserved.
    """
    base = (base_url or "").strip()
    if not base:
        raise VoiceProviderError("No endpoint URL configured for this provider.")
    head, sep, query = base.partition("?")
    if "/audio/" in head:
        return base
    joined = f"{head.rstrip('/')}/{suffix.lstrip('/')}"
    return f"{joined}?{query}" if sep else joined


# ``strip_markdown_for_speech`` is a pure helper owned by lumen; re-export.
from lumen.shared._util.rendering_text import strip_markdown_for_speech  # noqa: E402

__all__ = [
    "VoiceProviderError",
    "VoiceProviderHTTPError",
    "BaseTTSAdapter",
    "BaseSTTAdapter",
    "build_auth_headers",
    "join_audio_path",
    "strip_markdown_for_speech",
]
