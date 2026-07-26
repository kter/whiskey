#!/usr/bin/env python3
"""Generate synthetic bottle-front labels as a recognition lower-bound fixture.

These rendered labels are useful only for measuring a bottle_front lower bound.
They do not reproduce real photography, packaging, reflections, occlusion, or
camera artifacts and are not a substitute for an evaluation set of real photos.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "scripts" / "local" / "seed_data" / "whiskeys.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "synthetic"
DISCLAIMER = (
    "合成ラベルによる bottle_front 条件の下限測定用。"
    "実際のボトル写真・撮影条件を再現せず、実写真の代替にはならない。"
)
CANVAS_SIZE = (1200, 1600)
FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
)
SERIF_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"),
)


def load_catalog(path: Path) -> list[dict[str, Any]]:
    """Load catalog records needed to build synthetic labels."""
    with path.open(encoding="utf-8") as catalog_file:
        data = json.load(catalog_file)
    if not isinstance(data, list) or not data:
        raise ValueError("catalog must be a non-empty JSON array")
    required = {"id", "name_en", "name_ja", "distillery_en", "region", "type"}
    for index, item in enumerate(data):
        if not isinstance(item, dict) or any(not item.get(field) for field in required):
            raise ValueError(f"catalog item {index} is missing a required field")
    return data


def _font(candidates: tuple[Path, ...], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
    candidates: tuple[Path, ...],
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for size in range(start_size, 35, -4):
        font = _font(candidates, size)
        bounds = draw.textbbox((0, 0), text, font=font)
        if bounds[2] - bounds[0] <= max_width:
            return font
    return _font(candidates, 36)


def _label_parts(item: dict[str, Any]) -> tuple[str, str | None]:
    name = str(item["name_en"]).strip()
    age_match = re.search(r"\b(\d{1,2})\s*(?:Year(?:\s+Old)?|YO)\b", name, re.IGNORECASE)
    age = age_match.group(1) if age_match else None
    brand = re.sub(
        r"\s*\b\d{1,2}\s*(?:Year(?:\s+Old)?|YO)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    brand = re.sub(r"\s{2,}", " ", brand).strip(" ,-")
    return brand or name, age


def render_label(item: dict[str, Any], output_path: Path) -> None:
    """Render one deliberately clean label-style JPEG."""
    image = Image.new("RGB", CANVAS_SIZE, "#17120d")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (110, 80, 1090, 1520),
        radius=42,
        fill="#eee3c7",
        outline="#b08a45",
        width=12,
    )
    draw.rounded_rectangle(
        (155, 125, 1045, 1475),
        radius=28,
        outline="#5e251d",
        width=5,
    )
    draw.line((230, 330, 970, 330), fill="#b08a45", width=5)
    draw.line((230, 1240, 970, 1240), fill="#b08a45", width=5)

    brand, age = _label_parts(item)
    region = str(item["region"]).upper()
    whiskey_type = str(item["type"]).upper()
    distillery = str(item["distillery_en"]).upper()
    small_font = _font(FONT_CANDIDATES, 42)
    medium_font = _fit_font(draw, whiskey_type, 760, 72, FONT_CANDIDATES)
    brand_font = _fit_font(draw, brand.upper(), 800, 112, SERIF_FONT_CANDIDATES)
    distillery_font = _fit_font(draw, distillery, 760, 48, FONT_CANDIDATES)

    draw.text((600, 225), region, font=small_font, fill="#5e251d", anchor="mm")
    draw.text((600, 475), brand.upper(), font=brand_font, fill="#21160f", anchor="mm")
    draw.text((600, 650), whiskey_type, font=medium_font, fill="#5e251d", anchor="mm")
    if age:
        age_font = _font(SERIF_FONT_CANDIDATES, 230)
        years_font = _font(FONT_CANDIDATES, 42)
        draw.text((600, 900), age, font=age_font, fill="#21160f", anchor="mm")
        draw.text((600, 1055), "YEARS OLD", font=years_font, fill="#5e251d", anchor="mm")
    else:
        ornament_font = _font(SERIF_FONT_CANDIDATES, 130)
        draw.text((600, 920), "EST.", font=ornament_font, fill="#21160f", anchor="mm")
    draw.text((600, 1345), distillery, font=distillery_font, fill="#21160f", anchor="mm")
    image.save(output_path, format="JPEG", quality=92, optimize=True)


def generate(
    catalog_path: Path,
    output_dir: Path,
    manifest_path: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    """Generate images and a colocated manifest, returning the manifest data."""
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be greater than zero")
    items = load_catalog(catalog_path)
    if limit is not None:
        items = items[:limit]
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    cases = []
    for item in items:
        filename = f"{item['id']}.jpg"
        image_path = images_dir / filename
        render_label(item, image_path)
        relative_image = image_path.relative_to(manifest_path.parent).as_posix()
        cases.append(
            {
                "image": relative_image,
                "condition": "bottle_front",
                "expected_whiskey_id": item["id"],
                "expected_canonical_name": item["name_ja"],
                "notes": DISCLAIMER,
            }
        )

    manifest = {"version": 1, "cases": cases}
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Generate synthetic whiskey label images")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="output manifest path (default: <output-dir>/manifest.json)",
    )
    parser.add_argument("--limit", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Generate synthetic labels and their evaluation manifest."""
    args = parse_args(argv)
    manifest_path = args.manifest or args.output_dir / "manifest.json"
    try:
        manifest = generate(args.catalog, args.output_dir, manifest_path, args.limit)
        print(f"Generated {len(manifest['cases'])} synthetic labels")
        print(f"Manifest: {manifest_path}")
        print(DISCLAIMER)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
