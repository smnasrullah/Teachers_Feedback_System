"""Image uploads (avatars, teacher photos): never store what the client sent.

The bytes are sniffed by Pillow (the file name and ``Content-Type`` are ignored), the
picture is decoded, bounded, and written out again as a new WebP file under a random name.
Re-encoding drops EXIF (including GPS), ICC profiles, comments and anything appended to the
original file.
"""

import io
import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 24_000_000
MAX_OUTPUT_SIDE = 512
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
OUTPUT_QUALITY = 85


def _invalid() -> ValidationError:
    return ValidationError(_("Upload a valid JPEG, PNG or WebP image."), code="invalid_image")


def _too_large(max_bytes: int) -> ValidationError:
    return ValidationError(
        _("The image is too large. The limit is %(mb)d MB."),
        code="image_too_large",
        params={"mb": max_bytes // (1024 * 1024)},
    )


def validate_and_reencode_image(
    uploaded_file,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    max_side: int = MAX_OUTPUT_SIDE,
) -> ContentFile:
    """Return a clean, re-encoded copy of ``uploaded_file`` or raise ``ValidationError``."""
    if uploaded_file.size > max_bytes:
        raise _too_large(max_bytes)
    data = uploaded_file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise _invalid()
            if image.width * image.height > MAX_SOURCE_PIXELS:
                raise ValidationError(_("The image dimensions are too large."), code="image_pixels")
            if getattr(image, "is_animated", False):
                raise _invalid()
            image.load()
            picture = ImageOps.exif_transpose(image)
            picture.thumbnail((max_side, max_side))
            has_alpha = "A" in picture.getbands() or "transparency" in picture.info
            clean = Image.new("RGBA" if has_alpha else "RGB", picture.size)
            clean.paste(picture.convert(clean.mode))
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise _invalid() from None
    output = io.BytesIO()
    clean.save(output, format="WEBP", quality=OUTPUT_QUALITY)
    return ContentFile(output.getvalue(), name=f"{uuid.uuid4().hex}.webp")


class SafeImageField(forms.FileField):
    """A form file field whose cleaned value is the re-encoded image."""

    def to_python(self, data):
        upload = super().to_python(data)
        if upload is None:
            return None
        return validate_and_reencode_image(upload)
