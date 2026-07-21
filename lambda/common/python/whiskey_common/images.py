"""Safe image format detection and privacy-preserving JPEG normalization."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 8_000
TARGET_LONG_SIDE = 1_600
JPEG_QUALITIES = (90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35)
MIN_LONG_SIDE = 64


class ImageNormalizationError(ValueError):
    """Base class for terminal image-normalization failures."""


class ImageDecodeError(ImageNormalizationError):
    """Raised when Pillow cannot safely decode an image."""


class ImageTooLargeError(ImageNormalizationError):
    """Raised before pixel decoding when header dimensions exceed the limit."""


class ImageEncodeError(ImageNormalizationError):
    """Raised when an image cannot be encoded within the byte budget."""


def sniff_format(raw: bytes) -> str | None:
    """Return the supported format identified by magic bytes, if any."""
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def _check_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ImageDecodeError("Image dimensions must be positive")
    if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
        raise ImageTooLargeError("Image exceeds the 20 MP or 8000 px dimension limit")


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    has_alpha = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


def _resize_long_side(image: Image.Image, long_side: int) -> Image.Image:
    current = max(image.size)
    if current <= long_side:
        return image
    scale = long_side / current
    size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    resized = image.resize(size, Image.Resampling.LANCZOS)
    image.close()
    return resized


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    output = BytesIO()
    try:
        # Deliberately omit exif and icc_profile. This strips GPS and all other
        # metadata instead of copying privacy-sensitive source fields.
        image.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
    except (OSError, ValueError) as exc:
        raise ImageEncodeError("Unable to encode normalized JPEG") from exc
    return output.getvalue()


def normalize_image(raw: bytes, *, max_bytes: int) -> bytes:
    """Decode, orient, flatten, resize, and encode an image as metadata-free JPEG.

    Header dimensions are checked before ``load()`` so oversized compressed
    images are rejected without expanding their pixel buffers.
    """
    if not isinstance(raw, bytes) or not raw:
        raise ImageDecodeError("Image body is empty")
    if max_bytes <= 0:
        raise ImageEncodeError("Image byte budget must be positive")

    try:
        with Image.open(BytesIO(raw)) as source:
            width, height = source.size
            _check_dimensions(width, height)
            source.load()
            oriented = ImageOps.exif_transpose(source)
            oriented.load()
            image = _flatten_to_rgb(oriented)
            if oriented is not source:
                oriented.close()
    except ImageNormalizationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageDecodeError("Unable to decode image") from exc

    image = _resize_long_side(image, TARGET_LONG_SIDE)
    try:
        while True:
            for quality in JPEG_QUALITIES:
                encoded = _encode_jpeg(image, quality)
                if len(encoded) <= max_bytes:
                    return encoded

            current_long_side = max(image.size)
            if current_long_side <= MIN_LONG_SIDE:
                raise ImageEncodeError("Unable to encode image within byte budget")
            next_long_side = max(MIN_LONG_SIDE, int(current_long_side * 0.8))
            if next_long_side >= current_long_side:
                raise ImageEncodeError("Unable to encode image within byte budget")
            image = _resize_long_side(image, next_long_side)
    finally:
        image.close()
