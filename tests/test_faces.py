import io

import numpy as np
from PIL import Image

from photomanager.faces import crop_thumbnail


def test_crop_thumbnail_produces_expected_size_with_no_margin():
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    jpeg_bytes = crop_thumbnail(frame, (50, 50, 100, 100), margin=0.0)
    img = Image.open(io.BytesIO(jpeg_bytes))
    assert img.format == "JPEG"
    assert img.size == (50, 50)


def test_crop_thumbnail_applies_margin():
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    jpeg_bytes = crop_thumbnail(frame, (50, 50, 100, 100), margin=0.3)
    img = Image.open(io.BytesIO(jpeg_bytes))
    assert img.size == (80, 80)  # 50 * (1 + 2*0.3)


def test_crop_thumbnail_clamps_to_frame_bounds():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    jpeg_bytes = crop_thumbnail(frame, (0, 0, 100, 100), margin=0.5)
    img = Image.open(io.BytesIO(jpeg_bytes))
    assert img.size == (100, 100)


def test_crop_thumbnail_converts_bgr_to_rgb():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[:, :, 0] = 255  # blue channel in BGR (OpenCV/InsightFace convention)
    jpeg_bytes = crop_thumbnail(frame, (0, 0, 10, 10), margin=0.0)
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    r, g, b = img.getpixel((5, 5))
    assert b > 200
    assert r < 50
