"""Kode kesalahan baku WP-MCP. Setiap kode punya arti tetap yang dibaca skill dan gateway."""

from __future__ import annotations


class WPMCPError(Exception):
    """Kesalahan yang dikembalikan ke pemanggil dalam amplop {ok: false}."""

    code = "INTERNAL"

    def __init__(self, message: str, *, detail: dict | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}
        if code:
            self.code = code


class NotAuthorized(WPMCPError):
    code = "NOT_AUTHORIZED"


class NeedsConfirmation(WPMCPError):
    code = "NEEDS_CONFIRMATION"


class PIIBlocked(WPMCPError):
    code = "PII_BLOCKED"


class WPRejected(WPMCPError):
    code = "WP_REJECTED"


class RateLimited(WPMCPError):
    code = "RATE_LIMITED"


class WorkflowError(WPMCPError):
    """Perpindahan status yang tidak sah, mis. terbitkan draft yang belum siap_tayang."""

    code = "WORKFLOW"


class Expired(WPMCPError):
    code = "EXPIRED"


class ContentChanged(WPMCPError):
    code = "CONTENT_CHANGED"


class NamesUnverified(WPMCPError):
    code = "NAMES_UNVERIFIED"


class NotFound(WPMCPError):
    code = "NOT_FOUND"


class InvalidInput(WPMCPError):
    code = "INVALID_INPUT"


class NotConfigured(WPMCPError):
    code = "NOT_CONFIGURED"


class CommandNotAllowed(WPMCPError):
    code = "COMMAND_NOT_ALLOWED"
