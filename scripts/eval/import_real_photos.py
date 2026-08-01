#!/usr/bin/env python3
"""Import private evaluation photos as normalized, metadata-free JPEG files."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
import warnings
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_heif
except ModuleNotFoundError:
    pillow_heif = None


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMON_PYTHON = REPOSITORY_ROOT / "lambda" / "common" / "python"
if str(COMMON_PYTHON) not in sys.path:
    sys.path.insert(0, str(COMMON_PYTHON))

from whiskey_common.images import ImageNormalizationError, normalize_image  # noqa: E402


SUPPORTED_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}
OUTPUT_MAX_BYTES = 3_670_016
MAX_DECODE_IMAGE_PIXELS = 80_000_000
HEIC_CONVERSION_QUALITY = 0.92
# Keep this in sync with resizeAttempts in frontend/utils/imageResize.ts.
CLIENT_RESIZE_ATTEMPTS = (
    (1600, 0.85),
    (1600, 0.7),
    (1600, 0.55),
    (1280, 0.7),
    (1280, 0.55),
    (1024, 0.55),
)
METADATA_SIGNATURES = {
    "EXIF": b"Exif\x00\x00",
    "XMP": b"http://ns.adobe.com/xap/1.0/\x00",
    "ICC": b"ICC_PROFILE\x00",
}

# Pillow warns above this threshold and raises above twice it. The importer
# rejects at the threshold itself before expanding the full pixel buffer.
Image.MAX_IMAGE_PIXELS = MAX_DECODE_IMAGE_PIXELS


class ImportPhotoError(ValueError):
    """Raised when a private evaluation photo cannot be imported safely."""


if pillow_heif is not None:
    pillow_heif.register_heif_opener()


def collect_images(input_directories: Sequence[Path]) -> list[Path]:
    """Return supported image files from all input directories."""
    images: list[Path] = []
    for directory in input_directories:
        if not directory.is_dir():
            raise ImportPhotoError(f"input is not a directory: {directory}")
        images.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    return sorted(images, key=lambda path: str(path).casefold())


def _source_format(raw: bytes) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                detected = image.format
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImportPhotoError("image exceeds decode pixel limit") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImportPhotoError("unable to identify image format") from exc
    if not isinstance(detected, str) or not detected:
        raise ImportPhotoError("image format is unavailable")
    return detected.lower()


def _dimensions_within(width: int, height: int, max_dimension: int) -> tuple[int, int]:
    scale = min(1.0, max_dimension / max(width, height))
    return (
        max(1, int(width * scale + 0.5)),
        max(1, int(height * scale + 0.5)),
    )


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    has_alpha = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        try:
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        finally:
            rgba.close()
    return image.convert("RGB")


def _encode_client_jpeg(image: Image.Image, quality: float) -> bytes:
    output = BytesIO()
    image.save(output, format="JPEG", quality=round(quality * 100))
    return output.getvalue()


def _resize_for_client(raw: bytes) -> bytes:
    """Mirror client size/quality limits; Pillow and browser canvas bytes may differ."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                source_format = (source.format or "").lower()
                width, height = source.size
                pixel_limit = Image.MAX_IMAGE_PIXELS
                if pixel_limit is not None and width * height > pixel_limit:
                    raise ImportPhotoError("image exceeds decode pixel limit")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                try:
                    oriented.load()
                    image = _flatten_to_rgb(oriented)
                finally:
                    if oriented is not source:
                        oriented.close()
    except ImportPhotoError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImportPhotoError("image exceeds decode pixel limit") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImportPhotoError("unable to decode image") from exc

    if source_format in {"heic", "heif"}:
        try:
            # Match the heic-to JPEG conversion that precedes canvas resizing.
            converted_bytes = _encode_client_jpeg(image, HEIC_CONVERSION_QUALITY)
            with Image.open(BytesIO(converted_bytes)) as converted:
                converted.load()
                converted_image = _flatten_to_rgb(converted)
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            image.close()
            raise ImportPhotoError("unable to convert HEIC image") from exc
        image.close()
        image = converted_image

    try:
        for max_dimension, quality in CLIENT_RESIZE_ATTEMPTS:
            size = _dimensions_within(image.width, image.height, max_dimension)
            candidate = (
                image.resize(size, Image.Resampling.LANCZOS)
                if size != image.size
                else image
            )
            try:
                encoded = _encode_client_jpeg(candidate, quality)
            finally:
                if candidate is not image:
                    candidate.close()
            if len(encoded) <= OUTPUT_MAX_BYTES:
                return encoded
    except (OSError, ValueError) as exc:
        raise ImportPhotoError("unable to encode client JPEG") from exc
    finally:
        image.close()

    raise ImportPhotoError("client resize could not meet byte limit")


def verify_metadata_free_jpeg(path: Path) -> None:
    """Re-read an output JPEG and reject any EXIF, XMP, or ICC metadata."""
    raw = path.read_bytes()
    signatures = [name for name, signature in METADATA_SIGNATURES.items() if signature in raw]
    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if image.format != "JPEG":
                raise ImportPhotoError(f"normalized output is not JPEG: {path.name}")
            if len(image.getexif()) > 0:
                signatures.append("EXIF")
            for key in ("exif", "xmp", "XML:com.adobe.xmp", "icc_profile"):
                value = image.info.get(key)
                if value:
                    signatures.append(key)
    except ImportPhotoError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImportPhotoError(f"unable to verify normalized output: {path.name}") from exc
    if signatures:
        found = ", ".join(sorted(set(signatures)))
        raise ImportPhotoError(f"normalized output contains metadata ({found}): {path.name}")


def _write_atomic(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(contents)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def import_photo(path: Path, output_directory: Path) -> dict[str, Any]:
    """Normalize one photo and return its privacy-safe report entry."""
    if path.suffix.lower() in {".heic", ".heif"} and pillow_heif is None:
        raise ImportPhotoError(
            "HEIC/HEIF import requires pillow-heif from scripts/requirements.txt"
        )
    raw = path.read_bytes()
    source_format = _source_format(raw)
    resized = _resize_for_client(raw)
    try:
        normalized = normalize_image(resized, max_bytes=OUTPUT_MAX_BYTES)
    except ImageNormalizationError as exc:
        raise ImportPhotoError("unable to normalize image") from exc
    digest = hashlib.sha256(normalized).hexdigest()
    output_path = output_directory / f"{digest[:16]}.jpg"
    if output_path.exists() and output_path.read_bytes() != normalized:
        raise ImportPhotoError("sha256 filename collision")
    if not output_path.exists():
        _write_atomic(output_path, normalized)
    try:
        verify_metadata_free_jpeg(output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return {
        "sha256": digest,
        "output_bytes": len(normalized),
        "source_format": source_format,
    }


def _source_format_from_extension(path: Path) -> str:
    extension = path.suffix.lower().lstrip(".")
    return "jpeg" if extension in {"jpg", "jpeg"} else extension or "unknown"


def import_photos(input_directories: Sequence[Path], output_directory: Path) -> dict[str, Any]:
    """Import every supported photo and build a stdout-safe report."""
    paths = collect_images(input_directories)
    if not paths:
        raise ImportPhotoError("no supported images found")
    reports: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for path in paths:
        try:
            reports.append(import_photo(path, output_directory))
        except (ImportPhotoError, OSError) as exc:
            reason = str(exc) if isinstance(exc, ImportPhotoError) else "image I/O failed"
            failures.append(
                {
                    "reason": reason,
                    "source_format": _source_format_from_extension(path),
                }
            )
            print(f"ERROR: {path}: {reason}", file=sys.stderr)
    return {
        "report_version": 1,
        "imported_files": len(reports),
        "failed_files": len(failures),
        "unique_outputs": len({report["sha256"] for report in reports}),
        "images": reports,
        "failures": failures,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize private real photos for local brand evaluation"
    )
    parser.add_argument("input_directories", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True, dest="output_directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = import_photos(args.input_directories, args.output_directory)
    except (ImportPhotoError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["failed_files"] else 0


if __name__ == "__main__":
    sys.exit(main())
