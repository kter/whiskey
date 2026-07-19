"""Structured, redacting logging for Lambda functions."""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


SENSITIVE_PARAMETER_NAMES = {
    "address",
    "authorization",
    "body",
    "brand",
    "email",
    "lat",
    "latitude",
    "lng",
    "longitude",
    "notes",
    "password",
    "query",
    "query_params",
    "store",
    "token",
}


def redact(value: Any, key: str | None = None) -> Any:
    """Remove sensitive values while retaining useful field names."""
    normalized_key = (key or "").lower()
    if normalized_key in {"query_params", "body"} and isinstance(value, Mapping):
        return sorted(str(name) for name in value)
    if normalized_key in SENSITIVE_PARAMETER_NAMES:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(name): redact(item, str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    return value


class LambdaLogger:
    def __init__(
        self,
        function_name: str | None = None,
        log_level: str | LogLevel = LogLevel.INFO,
        correlation_id: str | None = None,
    ):
        self.function_name = function_name or os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
        self.environment = os.environ.get("ENVIRONMENT", "dev")
        self.correlation_id = correlation_id
        self.log_level = LogLevel(log_level.upper()) if isinstance(log_level, str) else log_level
        self.logger = logging.getLogger(self.function_name)
        self.logger.setLevel(getattr(logging, self.log_level.value))
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)

    def _create_log_entry(self, level: LogLevel, message: str, **kwargs: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": level.value,
            "function": self.function_name,
            "environment": self.environment,
            "message": message,
        }
        if self.correlation_id:
            entry["correlation_id"] = self.correlation_id
        if kwargs:
            entry["details"] = redact(kwargs)
        return entry

    def _log(self, level: LogLevel, message: str, **kwargs: Any) -> None:
        priorities = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50,
        }
        if priorities[level] < priorities[self.log_level]:
            return
        self.logger.log(
            getattr(logging, level.value),
            json.dumps(self._create_log_entry(level, message, **kwargs), ensure_ascii=False, default=str),
        )

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.CRITICAL, message, **kwargs)

    def log_api_request(
        self,
        method: str,
        path: str,
        query_params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        user_id: str | None = None,
    ) -> None:
        self.info(
            "API request received",
            method=method,
            path=path,
            query_params=query_params,
            body=body,
            user_id=user_id,
        )

    def log_api_response(
        self,
        status_code: int,
        response_size: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        level = LogLevel.INFO if status_code < 400 else LogLevel.ERROR
        self._log(
            level,
            "API response sent",
            status_code=status_code,
            response_size=response_size,
            duration_ms=duration_ms,
        )

    def log_database_operation(
        self,
        operation: str,
        table_name: str,
        item_count: int | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        level = LogLevel.ERROR if error else LogLevel.INFO
        self._log(
            level,
            f"Database {operation}",
            table_name=table_name,
            item_count=item_count,
            duration_ms=duration_ms,
            error=error,
        )

    def log_search_operation(
        self,
        query: str,
        result_count: int,
        duration_ms: float | None = None,
        search_type: str = "standard",
    ) -> None:
        self.info(
            "Search operation completed",
            query=query,
            result_count=result_count,
            duration_ms=duration_ms,
            search_type=search_type,
        )

    def log_jwt_operation(
        self,
        operation: str,
        user_id: str | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        level = LogLevel.INFO if success else LogLevel.WARNING
        self._log(level, f"JWT {operation}", user_id=user_id, success=success, error=error)

    def set_correlation_id(self, correlation_id: str) -> None:
        self.correlation_id = correlation_id

    def create_child_logger(self, component: str) -> "LambdaLogger":
        return LambdaLogger(
            function_name=f"{self.function_name}.{component}",
            log_level=self.log_level,
            correlation_id=self.correlation_id,
        )


def get_logger(
    function_name: str | None = None,
    log_level: str | None = None,
    correlation_id: str | None = None,
) -> LambdaLogger:
    return LambdaLogger(
        function_name=function_name,
        log_level=log_level or os.environ.get("LOG_LEVEL", "INFO"),
        correlation_id=correlation_id,
    )


def extract_correlation_id(event: Mapping[str, Any]) -> str | None:
    return (event.get("requestContext") or {}).get("requestId") or event.get("correlation_id")
