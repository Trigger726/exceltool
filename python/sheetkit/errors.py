"""Error model shared by the engine and the desktop bridge.

Every failure that can reach the user is a SheetKitError carrying a stable
`code` (for programmatic handling and tests) and a Chinese `message` (shown
directly in the UI). Unexpected exceptions are wrapped by the bridge so the
frontend never receives a raw traceback.
"""

from __future__ import annotations


class SheetKitError(Exception):
    code = 'E_INTERNAL'

    def __init__(self, message: str, *, detail: str | None = None, **context) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.context = context

    def to_dict(self) -> dict:
        payload = {'code': self.code, 'message': self.message}
        if self.detail:
            payload['detail'] = self.detail
        if self.context:
            payload['context'] = self.context
        return payload


class FileNotFoundError_(SheetKitError):
    code = 'E_FILE_NOT_FOUND'


class FileAccessError(SheetKitError):
    code = 'E_FILE_ACCESS'


class UnsupportedFormatError(SheetKitError):
    code = 'E_UNSUPPORTED_FORMAT'


class CorruptFileError(SheetKitError):
    code = 'E_CORRUPT_FILE'


class ValidationError(SheetKitError):
    code = 'E_VALIDATION'


class SheetNotFoundError(SheetKitError):
    code = 'E_SHEET_NOT_FOUND'


class ColumnNotFoundError(SheetKitError):
    code = 'E_COLUMN_NOT_FOUND'


class OutputConflictError(SheetKitError):
    code = 'E_OUTPUT_CONFLICT'


class ExportError(SheetKitError):
    code = 'E_EXPORT'


class TaskCancelledError(SheetKitError):
    code = 'E_CANCELLED'


class ResultExpiredError(SheetKitError):
    code = 'E_RESULT_EXPIRED'


class ConfirmationRequiredError(SheetKitError):
    code = 'E_CONFIRMATION_REQUIRED'
