import io

import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.uploads import (
    MAX_OUTPUT_SIDE,
    MAX_UPLOAD_BYTES,
    SafeImageField,
    validate_and_reencode_image,
)


def image_bytes(fmt="PNG", size=(40, 30), mode="RGB", **save_options):
    buffer = io.BytesIO()
    Image.new(mode, size, "red" if mode == "RGB" else 0).save(buffer, format=fmt, **save_options)
    return buffer.getvalue()


def upload(data, name="photo.png", content_type="image/png"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def reopen(result):
    return Image.open(io.BytesIO(result.read()))


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_valid_images_become_webp(fmt):
    result = validate_and_reencode_image(upload(image_bytes(fmt)))
    image = reopen(result)
    assert image.format == "WEBP"
    assert image.size == (40, 30)


def test_name_is_random_and_ignores_the_client_name():
    names = {
        validate_and_reencode_image(upload(image_bytes(), name="../../evil.php")).name
        for _ in range(3)
    }
    assert len(names) == 3
    for name in names:
        assert name.endswith(".webp") and "evil" not in name and "/" not in name


def test_exif_is_stripped_and_orientation_applied():
    source = Image.new("RGB", (100, 50), "blue")
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    exif[0x0112] = 6  # rotate 90 degrees clockwise when displayed
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif)
    assert b"SecretCameraMaker" in buffer.getvalue()

    result = validate_and_reencode_image(upload(buffer.getvalue(), "a.jpg", "image/jpeg"))
    data = result.read()
    assert b"SecretCameraMaker" not in data
    image = Image.open(io.BytesIO(data))
    assert len(image.getexif()) == 0
    assert image.size == (50, 100)


def test_trailing_payload_after_the_image_is_dropped():
    polyglot = image_bytes() + b"<?php system($_GET['c']); ?>"
    data = validate_and_reencode_image(upload(polyglot)).read()
    assert b"<?php" not in data


def test_large_pictures_are_scaled_down():
    result = validate_and_reencode_image(upload(image_bytes(size=(2000, 1000))))
    assert max(reopen(result).size) == MAX_OUTPUT_SIDE


def test_transparency_is_preserved():
    result = validate_and_reencode_image(upload(image_bytes(mode="RGBA")))
    assert "A" in reopen(result).getbands()


@pytest.mark.parametrize(
    "data",
    [
        b"<html><script>alert(1)</script></html>",
        b"GIF89a" + b"\x00" * 40,
        b"\x89PNG\r\n\x1a\n" + b"junk",
        b"",
        b"%PDF-1.7 fake",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    ],
)
def test_non_images_are_rejected_whatever_they_claim_to_be(data):
    with pytest.raises(ValidationError) as caught:
        validate_and_reencode_image(upload(data, "photo.png", "image/png"))
    assert caught.value.code == "invalid_image"


def test_formats_outside_the_allow_list_are_rejected():
    for fmt in ("GIF", "BMP", "TIFF"):
        with pytest.raises(ValidationError) as caught:
            validate_and_reencode_image(upload(image_bytes(fmt), "photo.png", "image/png"))
        assert caught.value.code == "invalid_image"


def test_animated_images_are_rejected():
    buffer = io.BytesIO()
    frames = [Image.new("RGB", (10, 10), color) for color in ("red", "blue")]
    frames[0].save(buffer, format="WEBP", save_all=True, append_images=frames[1:], duration=50)
    with pytest.raises(ValidationError):
        validate_and_reencode_image(upload(buffer.getvalue(), "a.webp", "image/webp"))


def test_oversized_files_are_rejected():
    big = upload(b"\x00" * (MAX_UPLOAD_BYTES + 1))
    with pytest.raises(ValidationError) as caught:
        validate_and_reencode_image(big)
    assert caught.value.code == "image_too_large"


def test_size_limit_is_checked_on_the_bytes_read_too():
    class LyingUpload(io.BytesIO):
        size = 10  # claims to be small

    with pytest.raises(ValidationError) as caught:
        validate_and_reencode_image(LyingUpload(b"\x00" * 200), max_bytes=100)
    assert caught.value.code == "image_too_large"


def test_images_with_too_many_pixels_are_rejected():
    flat = image_bytes(size=(6000, 6000), mode="L")
    assert len(flat) < MAX_UPLOAD_BYTES  # tiny on disk, huge in memory
    with pytest.raises(ValidationError) as caught:
        validate_and_reencode_image(upload(flat))
    assert caught.value.code == "image_pixels"


def test_form_field_returns_the_clean_copy_and_rejects_text():
    class PhotoForm(forms.Form):
        photo = SafeImageField(required=False)

    good = PhotoForm({}, {"photo": upload(image_bytes())})
    assert good.is_valid()
    assert good.cleaned_data["photo"].name.endswith(".webp")

    bad = PhotoForm({}, {"photo": upload(b"not an image")})
    assert not bad.is_valid()
    assert "photo" in bad.errors

    assert PhotoForm({}, {}).is_valid()
