"""Pillow image operations for sheet rectification and answer-area crops.

Pillow is imported inside each function so the tutor runtime does not need an
image library until a photo actually arrives. Every returned image is encoded
JPEG quality 90 and stays in memory; callers never store raw media.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence

DEFAULT_WIDTH = 1536
DEFAULT_HEIGHT = 2048
CROP_MARGIN = 0.01
JPEG_QUALITY = 90

_EPSILON = 1e-9


class ImageError(ValueError):
    """Raised when a photo, quad, or crop cannot be used."""


def rectify_sheet(
    image_bytes: bytes,
    corners,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> bytes:
    """Warp the photographed sheet to an upright image of ``width`` x ``height``.

    ``corners`` is four normalized ``[x, y]`` points in top-left, top-right,
    bottom-right, bottom-left order on the full photo. Pillow's ``QUAD``
    mapping is documented in top-left, bottom-left, bottom-right, top-right
    order, so the points are reordered before the transform.
    """
    points = _validated_corners(corners)
    if not _positive_int(width) or not _positive_int(height):
        raise ImageError("rectified size must be positive integers")
    from PIL import Image

    image = _open(image_bytes)
    pixel_width, pixel_height = image.size
    pixels = [
        (
            x * (pixel_width - 1),
            y * (pixel_height - 1),
        )
        for x, y in points
    ]
    top_left, top_right, bottom_right, bottom_left = pixels
    quad = (
        top_left[0],
        top_left[1],
        bottom_left[0],
        bottom_left[1],
        bottom_right[0],
        bottom_right[1],
        top_right[0],
        top_right[1],
    )
    try:
        rectified = image.transform(
            (width, height),
            Image.Transform.QUAD,
            quad,
            Image.Resampling.BICUBIC,
        )
    except (ValueError, TypeError, OSError) as error:
        raise ImageError("the sheet could not be rectified") from error
    return _encode_jpeg(rectified)


def crop_sheet(image_bytes: bytes, box, margin: float = CROP_MARGIN) -> bytes:
    """Crop an upright sheet at ``box`` expanded by ``margin``.

    ``box`` is normalized ``[x0, y0, x1, y1]``. The margin keeps the printed
    item label and expression inside the crop along with the answer space.
    """
    area = _validated_box(box)
    if not _number(margin) or not 0.0 <= margin <= 0.5:
        raise ImageError("crop margin must be a normalized fraction")
    image = _open(image_bytes)
    pixel_width, pixel_height = image.size
    x0, y0, x1, y1 = area
    left = max(0.0, x0 - margin)
    top = max(0.0, y0 - margin)
    right = min(1.0, x1 + margin)
    bottom = min(1.0, y1 + margin)
    left_px = max(0, int(math.floor(left * pixel_width)))
    top_px = max(0, int(math.floor(top * pixel_height)))
    right_px = min(pixel_width, int(math.ceil(right * pixel_width)))
    bottom_px = min(pixel_height, int(math.ceil(bottom * pixel_height)))
    if right_px <= left_px or bottom_px <= top_px:
        raise ImageError("the crop is empty")
    crop = image.crop((left_px, top_px, right_px, bottom_px))
    return _encode_jpeg(crop)


def sheet_crop(
    image_bytes: bytes,
    corners,
    box,
    margin: float = CROP_MARGIN,
) -> bytes:
    """Rectify the full photo, then crop the selected item's area."""
    return crop_sheet(rectify_sheet(image_bytes, corners), box, margin)


def _open(image_bytes: bytes):
    from PIL import Image, UnidentifiedImageError

    if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
        raise ImageError("image bytes are missing")
    if not image_bytes:
        raise ImageError("image bytes are empty")
    try:
        image = Image.open(io.BytesIO(bytes(image_bytes)))
        image.load()
    except (OSError, ValueError, UnidentifiedImageError) as error:
        raise ImageError("the image could not be decoded") from error
    return image.convert("RGB")


def _encode_jpeg(image) -> bytes:
    buffer = io.BytesIO()
    try:
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    except (OSError, ValueError) as error:
        raise ImageError("the image could not be encoded") from error
    return buffer.getvalue()


def _validated_corners(corners) -> tuple[tuple[float, float], ...]:
    if isinstance(corners, (str, bytes)) or not isinstance(corners, Sequence):
        raise ImageError("corners must be four normalized points")
    points = []
    for point in corners:
        if isinstance(point, (str, bytes)) or not isinstance(point, Sequence):
            raise ImageError("each corner must be an [x, y] point")
        if len(point) != 2 or not all(_number(value) for value in point):
            raise ImageError("each corner must be an [x, y] point")
        x, y = float(point[0]), float(point[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ImageError("corners must be normalized to the photo")
        points.append((x, y))
    if len(points) != 4:
        raise ImageError("corners must be four normalized points")
    if not _is_convex_quad(points):
        raise ImageError("corners must form a non-degenerate convex quad")
    return tuple(points)


def _is_convex_quad(points: list[tuple[float, float]]) -> bool:
    area = abs(
        sum(
            points[index][0] * points[(index + 1) % 4][1]
            - points[(index + 1) % 4][0] * points[index][1]
            for index in range(4)
        )
    )
    if area <= _EPSILON:
        return False
    for index in range(4):
        ax, ay = points[index]
        bx, by = points[(index + 1) % 4]
        cx, cy = points[(index + 2) % 4]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cross <= _EPSILON:
            return False
    return True


def _validated_box(box) -> tuple[float, float, float, float]:
    if isinstance(box, (str, bytes)) or not isinstance(box, Sequence):
        raise ImageError("the crop box must be four normalized numbers")
    if len(box) != 4 or not all(_number(value) for value in box):
        raise ImageError("the crop box must be four normalized numbers")
    x0, y0, x1, y1 = (float(value) for value in box)
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ImageError("the crop box must be an ordered area on the sheet")
    return (x0, y0, x1, y1)


def _number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
