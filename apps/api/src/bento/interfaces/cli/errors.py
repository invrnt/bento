"""CLI errors and the mapping from API error codes to process exit codes (`product/cli.md` § Exit codes)."""

from __future__ import annotations

from typing import Any

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_UNREACHABLE = 5
EXIT_SETUP_REQUIRED = 6
EXIT_PARTIAL = 7
EXIT_TELEGRAM_WAIT = 8
EXIT_INTERRUPTED = 130

# Setup-required codes and the command that fixes each one (`error.details.next`).
SETUP_NEXT: dict[str, str] = {
    "signed_out": "bento setup",
    "telegram_not_authorized": "bento setup",
    "telegram_login_expired": "bento login",
    "no_vault": "bento setup",
    "vault_not_found": "bento setup",
    "locked": "bento join CODE",
    "vault_locked": "bento join CODE",
    "device_removed": "bento join CODE",
    "telegram_not_available": "bento doctor",
    "telegram_not_configured": "bento doctor",
    "setup_required": "bento setup",
}

_USAGE = frozenset({"validation_failed", "usage_error", "confirmation_required", "request_validation_failed"})
_UNREACHABLE = frozenset(
    {
        "bento_unreachable",
        "desktop_not_running",
        "daemon_start_failed",
        "daemon_not_running",
        "telegram_network",
        "pairing_relay_unavailable",
        "storage_unavailable",
    }
)
_CONFLICT = frozenset(
    {
        "path_ambiguous",
        "path_exists",
        "not_a_folder",
        "duplicate_asset",
        "invalid_folder_move",
        "job_not_retryable",
        "daemon_already_running",
        "album_ambiguous",
        "trash_item_ambiguous",
    }
)


class CliError(Exception):
    """An error rendered as `{"error": {code, message, details, exit_code}}`."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        exit_code: int | None = None,
        *,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})
        self.status = status
        self.exit_code = exit_code if exit_code is not None else exit_code_for(code, status)
        if self.exit_code == EXIT_SETUP_REQUIRED and "next" not in self.details:
            self.details["next"] = SETUP_NEXT.get(code, "bento setup")

    def to_json(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "exit_code": self.exit_code,
            }
        }


def exit_code_for(code: str, status: int | None = None) -> int:
    if code in SETUP_NEXT:
        return EXIT_SETUP_REQUIRED
    if code == "telegram_flood_wait":
        return EXIT_TELEGRAM_WAIT
    if code in _USAGE:
        return EXIT_USAGE
    if code in _UNREACHABLE:
        return EXIT_UNREACHABLE
    if code in _CONFLICT or code.endswith("_conflict") or code.endswith("_ambiguous"):
        return EXIT_CONFLICT
    if code.endswith("_not_found"):
        return EXIT_NOT_FOUND
    if status == 404:
        return EXIT_NOT_FOUND
    if status == 409:
        return EXIT_CONFLICT
    if status in {400, 422}:
        return EXIT_USAGE
    if status == 429:
        return EXIT_TELEGRAM_WAIT
    return EXIT_UNEXPECTED


def usage(message: str, **details: Any) -> CliError:
    return CliError("usage_error", message, details, EXIT_USAGE)


def confirmation_required(command: str) -> CliError:
    return CliError(
        "confirmation_required",
        "This command cannot be undone; pass --yes to confirm",
        {"command": command},
        EXIT_USAGE,
    )
