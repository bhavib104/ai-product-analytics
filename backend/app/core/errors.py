"""Application error types with a consistent API envelope."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class DataNotReadyError(AppError):
    def __init__(self, message: str = "Analytical data is not ready. Run the data pipeline first."):
        super().__init__("DATA_NOT_READY", message, 503)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found."):
        super().__init__("NOT_FOUND", message, 404)


class SqlRejectedError(AppError):
    def __init__(self, message: str, details=None):
        super().__init__("SQL_REJECTED", message, 400, details)


class QueryTimeoutError(AppError):
    def __init__(self, message: str = "Query exceeded the execution time limit."):
        super().__init__("QUERY_TIMEOUT", message, 408)


class LlmUnavailableError(AppError):
    def __init__(self, message: str = "No external LLM is configured."):
        super().__init__("LLM_UNAVAILABLE", message, 503)
