from __future__ import annotations

from typing import Any

HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_INTERNAL_SERVER_ERROR = 500


class SegEntryError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "seg_entry_error",
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details or {}

    def http_status(self) -> int:
        return resolve_http_status(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


def resolve_http_status(error: SegEntryError) -> int:
    if isinstance(error.status, int) and 400 <= error.status <= 599:
        return error.status
    return infer_http_status_from_code(error.code)


def infer_http_status_from_code(code: str | None) -> int:
    if not code:
        return HTTP_STATUS_INTERNAL_SERVER_ERROR
    if code == "not_found" or code.endswith("_not_found"):
        return HTTP_STATUS_NOT_FOUND
    if code.startswith("invalid_") or code.startswith("unsupported_"):
        return HTTP_STATUS_BAD_REQUEST
    if code.endswith("_required") or code.endswith("_missing") or code.endswith("_empty"):
        return HTTP_STATUS_BAD_REQUEST
    if code in {"missing_field", "invalid_request", "seg_entry_error"}:
        return HTTP_STATUS_BAD_REQUEST
    return HTTP_STATUS_INTERNAL_SERVER_ERROR
