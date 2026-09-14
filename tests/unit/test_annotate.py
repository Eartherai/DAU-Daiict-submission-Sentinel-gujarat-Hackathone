"""Detection boxes on a still. Geometry only — no live grid."""
from saakshya.live.annotate import _scale, annotate_jpeg, crop_plate_jpeg


def test_normalised_boxes_scale_to_the_preview():
    assert _scale((0.1, 0.2, 0.5, 0.6), 100, 200, 1920, 1080) == (10, 40, 50, 120)


def test_pixel_boxes_scale_from_camera_size():
    box = _scale((100, 50, 300, 150), 200, 100, 400, 200)
    assert box == (50, 25, 150, 75)


def test_tiny_or_missing_boxes_are_dropped():
    assert _scale(None, 100, 100, 1920, 1080) is None
    assert _scale((0.0, 0.0, 0.001, 0.001), 100, 100, None, None) is None


def test_annotate_returns_the_original_when_there_is_nothing_to_draw():
    class Fake:
        engine = None
    jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    # Empty JPEG-ish bytes: annotate must not raise.
    out = annotate_jpeg(jpeg, Fake(), "cam01", preview_wh=(64, 36),
                        camera_wh=(1920, 1080))
    assert out == jpeg


def test_crop_plate_jpeg_cuts_the_stored_box():
    import io
    from PIL import Image

    im = Image.new("RGB", (200, 100), (10, 10, 10))
    for x in range(40, 80):
        for y in range(20, 50):
            im.putpixel((x, y), (240, 240, 40))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    crop = crop_plate_jpeg(buf.getvalue(), (40, 20, 80, 50),
                           camera_wh=(200, 100), pad=0.0)
    assert crop
    got = Image.open(io.BytesIO(crop))
    assert got.size == (40, 30)
    assert crop_plate_jpeg(buf.getvalue(), None, camera_wh=(200, 100)) is None
