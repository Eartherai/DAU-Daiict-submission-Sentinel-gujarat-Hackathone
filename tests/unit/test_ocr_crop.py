"""Tiny plate crops are stretched before OCR; the pixels are not invented."""
import numpy as np

from saakshya.analytics.anpr import prepare_ocr_crop


def test_a_tall_enough_crop_is_left_alone():
    img = np.zeros((64, 160, 3), dtype=np.uint8)
    out = prepare_ocr_crop(img, min_height=48)
    assert out.shape == img.shape
    assert out is img


def test_a_short_crop_is_scaled_to_the_ocr_minimum():
    img = np.zeros((20, 80, 3), dtype=np.uint8)
    img[10, 40] = (255, 255, 255)
    out = prepare_ocr_crop(img, min_height=48)
    assert out.shape[0] == 48
    assert out.shape[1] == 192
    # Same content, larger — bicubic will smear a one-pixel spike, but
    # energy is still in the crop.
    assert int(out.max()) > 0
