import hashlib
import json
from io import BytesIO

import pytest
from PIL import Image

from tests.lambda_module_loader import load_lambda_module


photo_import = load_lambda_module(
    "import_real_photos_script_tests",
    "scripts/eval/import_real_photos.py",
)


def _jpeg_bytes(*, size=(320, 240), exif=None) -> bytes:
    output = BytesIO()
    options = {"format": "JPEG", "quality": 95}
    if exif is not None:
        options["exif"] = exif
    Image.new("RGB", size, (120, 70, 30)).save(output, **options)
    return output.getvalue()


def test_import_strips_gps_exif_and_uses_content_hash_filename(tmp_path):
    source = tmp_path / "private-location-2026-08-01.jpg"
    exif = Image.Exif()
    exif[271] = "secret-camera"
    exif[34853] = {
        1: "N",
        2: (35.0, 0.0, 0.0),
        3: "E",
        4: (139.0, 0.0, 0.0),
    }
    source.write_bytes(_jpeg_bytes(exif=exif))
    output_directory = tmp_path / "images-real"

    report = photo_import.import_photos([tmp_path], output_directory)

    output_files = list(output_directory.glob("*.jpg"))
    assert len(output_files) == 1
    output = output_files[0]
    contents = output.read_bytes()
    digest = hashlib.sha256(contents).hexdigest()
    assert output.name == f"{digest[:16]}.jpg"
    assert "private-location" not in output.name
    assert report["images"] == [
        {
            "sha256": digest,
            "output_bytes": len(contents),
            "source_format": "jpeg",
        }
    ]
    assert report["failed_files"] == 0
    assert report["failures"] == []
    assert b"Exif\x00\x00" not in contents
    assert b"http://ns.adobe.com/xap/1.0/\x00" not in contents
    assert b"ICC_PROFILE\x00" not in contents
    with Image.open(output) as image:
        assert len(image.getexif()) == 0
        assert not any(
            image.info.get(key)
            for key in ("exif", "xmp", "XML:com.adobe.xmp", "icc_profile")
        )


def test_duplicate_content_is_idempotent(tmp_path):
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    contents = _jpeg_bytes()
    (source_directory / "first.jpg").write_bytes(contents)
    (source_directory / "second.jpeg").write_bytes(contents)
    output_directory = tmp_path / "output"

    first_report = photo_import.import_photos([source_directory], output_directory)
    second_report = photo_import.import_photos([source_directory], output_directory)

    output_files = list(output_directory.glob("*.jpg"))
    assert len(output_files) == 1
    assert first_report["unique_outputs"] == 1
    assert second_report["unique_outputs"] == 1
    assert first_report["images"][0]["sha256"] == first_report["images"][1]["sha256"]
    assert first_report == second_report


@pytest.mark.parametrize("preexisting", [False, True])
def test_metadata_verification_failure_removes_output_and_continues(
    tmp_path, monkeypatch, capsys, preexisting
):
    source_directory = tmp_path / "private-source"
    source_directory.mkdir()
    failed_source = source_directory / "01-private-location.jpg"
    failed_source.write_bytes(_jpeg_bytes(size=(321, 240)))
    next_source = source_directory / "02-next.jpg"
    next_source.write_bytes(_jpeg_bytes(size=(322, 240)))
    output_directory = tmp_path / "output"

    failed_report = photo_import.import_photo(failed_source, output_directory)
    failed_output = output_directory / f"{failed_report['sha256'][:16]}.jpg"
    if not preexisting:
        failed_output.unlink()

    original_verify = photo_import.verify_metadata_free_jpeg

    def stub_verify(path):
        if path == failed_output:
            raise photo_import.ImportPhotoError("stub metadata verification failure")
        original_verify(path)

    monkeypatch.setattr(photo_import, "verify_metadata_free_jpeg", stub_verify)

    exit_code = photo_import.main(
        [str(source_directory), "--out", str(output_directory)]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert exit_code == 1
    assert not failed_output.exists()
    assert report["imported_files"] == 1
    assert report["failed_files"] == 1
    assert len(list(output_directory.glob("*.jpg"))) == 1
    assert str(failed_source) in captured.err


def test_output_obeys_byte_limit(tmp_path):
    source = tmp_path / "large.png"
    output = BytesIO()
    Image.effect_noise((2400, 1600), 100).convert("RGB").save(output, format="PNG")
    source.write_bytes(output.getvalue())

    report = photo_import.import_photos([tmp_path], tmp_path / "output")

    assert report["images"][0]["output_bytes"] <= photo_import.OUTPUT_MAX_BYTES


def test_import_resizes_image_over_analyze_pixel_limit(tmp_path):
    source = tmp_path / "iphone-sized.jpg"
    image = Image.new("RGB", (4284, 5712), (80, 110, 140))
    try:
        image.save(source, format="JPEG", quality=95)
    finally:
        image.close()

    output_directory = tmp_path / "output"
    report = photo_import.import_photos([tmp_path], output_directory)

    assert report["imported_files"] == 1
    assert report["failed_files"] == 0
    output = next(output_directory.glob("*.jpg"))
    contents = output.read_bytes()
    assert len(contents) <= photo_import.OUTPUT_MAX_BYTES
    assert not any(
        signature in contents
        for signature in photo_import.METADATA_SIGNATURES.values()
    )
    with Image.open(BytesIO(contents)) as normalized:
        normalized.load()
        assert normalized.format == "JPEG"
        assert max(normalized.size) <= 1600
        assert len(normalized.getexif()) == 0


def test_client_resize_uses_first_attempt_within_byte_limit(monkeypatch):
    raw = _jpeg_bytes(size=(2400, 1200))
    calls = []
    original_encode = photo_import._encode_client_jpeg

    def stub_encode(image, quality):
        calls.append((image.size, quality))
        if len(calls) < 3:
            return b"x" * (photo_import.OUTPUT_MAX_BYTES + 1)
        return original_encode(image, quality)

    monkeypatch.setattr(photo_import, "_encode_client_jpeg", stub_encode)

    resized = photo_import._resize_for_client(raw)

    assert calls == [
        ((1600, 800), 0.85),
        ((1600, 800), 0.7),
        ((1600, 800), 0.55),
    ]
    with Image.open(BytesIO(resized)) as image:
        assert image.size == (1600, 800)


def test_image_over_decode_pixel_limit_is_reported_as_failure(tmp_path, monkeypatch):
    source = tmp_path / "too-many-pixels.jpg"
    source.write_bytes(_jpeg_bytes())
    monkeypatch.setattr(photo_import.Image, "MAX_IMAGE_PIXELS", 10_000)

    report = photo_import.import_photos([tmp_path], tmp_path / "output")

    assert report["imported_files"] == 0
    assert report["failed_files"] == 1
    assert report["failures"] == [
        {"reason": "image exceeds decode pixel limit", "source_format": "jpeg"}
    ]


def test_failure_does_not_stop_other_imports_or_leak_path(tmp_path, capsys):
    source_directory = tmp_path / "private-source"
    source_directory.mkdir()
    successful = source_directory / "safe.jpg"
    successful.write_bytes(_jpeg_bytes())
    failed = source_directory / "secret-location-2026-08-01.png"
    failed.write_bytes(b"not an image")
    output = tmp_path / "output"

    exit_code = photo_import.main([str(source_directory), "--out", str(output)])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    serialized_failures = json.dumps(report["failures"])
    assert exit_code == 1
    assert report["imported_files"] == 1
    assert report["failed_files"] == 1
    assert len(list(output.glob("*.jpg"))) == 1
    assert report["failures"] == [
        {"reason": "unable to identify image format", "source_format": "png"}
    ]
    assert str(failed) not in captured.out
    assert failed.name not in serialized_failures
    assert str(tmp_path) not in serialized_failures
    assert str(failed) in captured.err


def test_unsupported_files_are_ignored(tmp_path, capsys):
    (tmp_path / "clip.mov").write_bytes(b"not a photo")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(_jpeg_bytes())
    output = tmp_path / "output"

    assert photo_import.main([str(tmp_path), "--out", str(output)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["imported_files"] == 1
    assert len(list(output.glob("*.jpg"))) == 1


def test_heif_opener_is_registered():
    if photo_import.pillow_heif is None:
        pytest.skip("pillow-heif is not installed in the test environment")
    registered = Image.registered_extensions()
    assert registered[".heic"] == "HEIF"
    assert registered[".heif"] == "HEIF"
