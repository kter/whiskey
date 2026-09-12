"""Shared domain errors for Lambda request validation."""

from collections.abc import Mapping


class ValidationError(ValueError):
    """Raised for caller-controlled invalid input."""

    def __init__(self, fields: Mapping[str, str]):
        super().__init__("Validation failed")
        self.fields = dict(fields)
