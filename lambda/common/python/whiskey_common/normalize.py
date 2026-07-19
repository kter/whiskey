"""Text normalization shared by whiskey search implementations."""

import unicodedata


def normalize_text(text: str) -> str:
    """Normalize case, width, whitespace, and Katakana for Japanese search."""
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = "".join(normalized.split())
    return "".join(
        chr(ord(character) - 0x60)
        if "\u30a1" <= character <= "\u30f6"
        else character
        for character in normalized
    )
