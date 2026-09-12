"""Shared environment-backed image upload limits."""

from __future__ import annotations

import os


def upload_max_bytes() -> int:
    """Return the maximum accepted temporary-upload size."""
    return int(os.environ.get("UPLOAD_MAX_BYTES", "3670016"))


def image_max_bytes() -> int:
    """Return the maximum normalized image size."""
    return int(os.environ.get("IMAGE_MAX_BYTES", "1572864"))
