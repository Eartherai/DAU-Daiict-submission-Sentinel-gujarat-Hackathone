"""The catalogue is the contract. The integrator guide's JSON shape must parse.

The documented endpoint is `GET /api/ingest`. On this sandbox that path is not
currently served from the RTSP host (MEASURED 404) and the CDN catalogue still
redirects to a login page. The parser still has to accept the documented record
shape, so a session that unblocks the catalogue is a mapping, not a rewrite.
"""
from __future__ import annotations

from saakshya.live.grid import GridConfig, parse_catalogue


def test_official_ingest_record_shape():
    cfg = GridConfig(
        rtsp_template="rtsp://grid.example:8554/stream/{id}",
        hls_template="http://grid.example/live/stream/{id}/index.m3u8",
        whep_template="http://grid.example:8889/stream/{id}/whep",
    )
    cams = parse_catalogue([
        {
            "id": 1,
            "location": {"name": "Paldi Circle", "lat": 23.013, "lon": 72.571},
            "codec": "h264",
            "live": True,
            "properties": {"width": 1920, "height": 1080, "fps": 25},
            "urls": {
                "rtsp": "rtsp://grid.example:8554/stream/1",
                "whep": "http://grid.example:8889/stream/1/whep",
                "hls": "http://grid.example/live/stream/1/index.m3u8",
            },
        }
    ], cfg)
    assert len(cams) == 1
    cam = cams[0]
    assert cam.camera_id == "1"
    assert cam.location == "Paldi Circle"
    assert cam.lat == 23.013 and cam.lon == 72.571
    assert cam.codec == "h264"
    assert cam.width == 1920 and cam.height == 1080
    assert cam.declared_fps == 25.0
    assert cam.rtsp_url.endswith("/stream/1")
    assert cam.whep_url.endswith("/whep")
    assert cam.hls_url.endswith("index.m3u8")
    assert cam.extra.get("live") is True
    assert cam.source == "catalogue"


def test_cameras_wrapper_and_numeric_ids_do_not_invent_urls_over_supplied_ones():
    cfg = GridConfig()
    cams = parse_catalogue({
        "cameras": [
            {"id": "cam06", "urls": {"rtsp": "rtsp://grid.example:8554/stream/cam06"}}
        ]
    }, cfg)
    assert cams[0].camera_id == "cam06"
    assert cams[0].rtsp_url == "rtsp://grid.example:8554/stream/cam06"
