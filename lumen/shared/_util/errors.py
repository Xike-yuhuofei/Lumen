"""
Base exception classes for consistent error handling across the application.
Provides a standardized way to distinguish between bugs, recoverable errors,
and configuration issues.

Canonical home: ``lumen/shared/_util`` (migrated from ``lumen/core/errors``).
"""

from typing import Any, Dict, Optional


class LumenError(Exception):
    """Base class for all application errors in Lumen."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ConfigurationError(LumenError):
    """Raised when there's a configuration-related error."""

    pass


class ValidationError(LumenError):
    """Raised when input validation fails."""

    pass


class ServiceError(LumenError):
    """Base class for service layer errors."""

    pass


class LLMServiceError(ServiceError):
    """Base class for LLM service-related errors."""

    pass


class LLMContextError(LLMServiceError):
    """Raised when prompt exceeds model context window."""

    pass


class EnvironmentConfigError(ConfigurationError):
    """Raised when there's an environment-related configuration error."""

    pass


__all__ = [
    "LumenError",
    "ConfigurationError",
    "ValidationError",
    "ServiceError",
    "LLMServiceError",
    "LLMContextError",
    "EnvironmentConfigError",
]
