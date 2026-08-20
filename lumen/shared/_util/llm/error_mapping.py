"""
Error Mapping - Map provider-specific errors to unified exceptions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

# Import unified exceptions from exceptions.py
from .exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    ProviderContextWindowError,
)

logger = logging.getLogger(__name__)


ErrorClassifier = Callable[[Exception], bool]


@dataclass(frozen=True)
class MappingRule:
    classifier: ErrorClassifier
    factory: Callable[[Exception, str | None], LLMError]


def _instance_of(*types: type[BaseException]) -> ErrorClassifier:
    return lambda exc: isinstance(exc, types)


def _message_contains(*needles: str) -> ErrorClassifier:
    def _classifier(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(needle in msg for needle in needles)

    return _classifier


def _class_named(*names: str) -> ErrorClassifier:
    """Match optional SDK exceptions without importing the SDK at startup."""
    expected = set(names)

    def _classifier(exc: Exception) -> bool:
        return any(cls.__name__ in expected for cls in type(exc).__mro__)

    return _classifier


_GLOBAL_RULES: list[MappingRule] = [
    MappingRule(
        classifier=_class_named("AuthenticationError", "AuthenticationStatusError"),
        factory=lambda exc, provider: LLMAuthenticationError(str(exc), provider=provider),
    ),
    MappingRule(
        classifier=_class_named("RateLimitError"),
        factory=lambda exc, provider: LLMRateLimitError(str(exc), provider=provider),
    ),
    MappingRule(
        classifier=_message_contains("rate limit", "429", "quota"),
        factory=lambda exc, provider: LLMRateLimitError(str(exc), provider=provider),
    ),
    MappingRule(
        classifier=_message_contains("context length", "maximum context"),
        factory=lambda exc, provider: ProviderContextWindowError(str(exc), provider=provider),
    ),
    # Gitee AI intermittent 503: the account-serving pool has no idle account for
    # the requested model. Transient — already handled by provider-level retry;
    # if it still fails after the retry budget, surface an actionable message
    # with the correct HTTP status instead of a raw upstream body.
    MappingRule(
        classifier=_message_contains(
            "no_available_account",
            "no available account",
        ),
        factory=lambda exc, provider: LLMAPIError(
            (
                "模型服务暂不可用：供应商（账号服务池）暂时没有可用账号"
                f"〔{provider or 'unknown'}〕，通常是瞬时波动，请稍后重试。"
            ),
            status_code=503,
            provider=provider,
        ),
    ),
]


def _provider_env_hint(provider: str | None) -> str:
    """Return a short, actionable hint naming the env var for *provider*.

    Reads the LLM registry's canonical env key so the message can tell the
    user *where* to re-supply the credential instead of dumping raw JSON.
    Lazy import keeps the mapping module free of configuration imports.
    """
    if not provider:
        return ""
    try:
        from lumen.shared.config.credentials import provider_env_key

        key = provider_env_key(provider)
    except Exception:
        return ""
    if not key:
        return ""
    return f" 需要更新环境变量 {key} 后重启应用。"


def _friendly_auth_message(raw: str, provider: str | None) -> str:
    """Build a clean, actionable message for an upstream 401 without leaking
    the raw provider body to the end user (criterion: never expose a raw
    upstream exception as the *only* feedback)."""
    low = (raw or "").lower()
    # The provider prefix already precedes the message in ``__str__``
    # (``[gitee] HTTP 401 ...``), so do not name the service again here.
    if any(k in low for k in ("token_expired", "token has expired", "已过期", "expired")):
        return (
            f"访问凭证（Token / API Key）已过期，"
            f"请重新生成该服务的凭证并更新后重试。{_provider_env_hint(provider)}"
        )
    if any(
        k in low
        for k in (
            "unauthorized",
            "invalid api key",
            "invalid_key",
            "authentication",
            "not_authenticated",
            "invalid token",
            "missing api key",
        )
    ):
        return (
            f"认证失败：API Key / Token 无效、缺失或已被吊销，"
            f"请核对并更新该服务的凭证后重试。{_provider_env_hint(provider)}"
        )
    return (
        f"认证失败（HTTP 401），请检查 API Key / Token 是否配置正确。{_provider_env_hint(provider)}"
    )


def map_error(exc: Exception, provider: str | None = None) -> LLMError:
    """Map provider-specific errors to unified internal exceptions."""
    # Heuristic check for status codes before rules
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        # Never pass the raw upstream body through as the user-facing message.
        return LLMAuthenticationError(_friendly_auth_message(str(exc), provider), provider=provider)
    if status_code == 429:
        return LLMRateLimitError(str(exc), provider=provider)

    for rule in _GLOBAL_RULES:
        if rule.classifier(exc):
            return rule.factory(exc, provider)

    return LLMAPIError(str(exc), status_code=status_code, provider=provider)
