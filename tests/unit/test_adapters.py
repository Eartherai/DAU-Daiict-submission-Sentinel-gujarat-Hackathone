from __future__ import annotations

import pytest

from saakshya.ingest.adapters import (
    ONVIFAdapter,
    RTSPAdapter,
    adapter_for,
)


def test_rtsp_adapter_validates_and_preserves_source() -> None:
    source = RTSPAdapter().resolve(
        {"camera_id": "cam01", "url": "rtsp://example.test/live"}
    )
    assert source.camera_id == "cam01"
    assert source.protocol == "rtsp"
    assert source.url.startswith("rtsp://")


def test_onvif_requires_resolved_rtsp_source() -> None:
    source = ONVIFAdapter().resolve(
        {"camera_id": "cam01", "url": "rtsps://example.test/live"}
    )
    assert source.options["discovery"] == "onvif"


def test_adapter_rejects_wrong_scheme() -> None:
    with pytest.raises(ValueError, match="cannot resolve"):
        RTSPAdapter().resolve(
            {"camera_id": "cam01", "url": "https://example.test/live"}
        )


def test_unknown_adapter_is_explicit() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        adapter_for("proprietary")
