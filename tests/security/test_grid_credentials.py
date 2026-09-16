"""The grid credential must reach the socket and nothing else.

The Sentinel grid authenticates every stream connection with an email and access
password in the URL authority. That is its design, and it means any code path
that handles a stream URL is a path a credential can escape through — into a
log, an exception, a database row, an export, or a screenshot of a camera table.

These tests pin the two halves of the containment: the credential is added
immediately before the connection, and every exit that can quote a URL redacts
it first.
"""
from __future__ import annotations

import pytest

from saakshya.live.credentials import (
    MissingCredential,
    configured,
    credentialed,
    needs_grid_credential,
    redact,
)

CLEAN = "rtsp://103.250.160.189:8554/stream/cam01"
EMAIL = "officer.name@example.gov.in"
TEST_ACCESS_VALUE = "AAAA-BBBB-CCCC"


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("SENTINEL_GRID_EMAIL", EMAIL)
    monkeypatch.setenv("SENTINEL_GRID_PASSWORD", TEST_ACCESS_VALUE)


@pytest.fixture
def no_creds(monkeypatch):
    monkeypatch.delenv("SENTINEL_GRID_EMAIL", raising=False)
    monkeypatch.delenv("SENTINEL_GRID_PASSWORD", raising=False)


def test_the_at_in_an_email_is_percent_encoded(creds):
    """An unencoded @ splits the authority at the wrong place.

    The grid then reads a truncated username and refuses the connection, which
    surfaces as a 401 that looks like a wrong password rather than a wrong URL.
    """
    url = credentialed(CLEAN)
    assert "officer.name%40example.gov.in" in url
    assert url.count("@") == 1, "exactly one authority separator"
    assert url.endswith("@103.250.160.189:8554/stream/cam01")


def test_redaction_removes_both_halves(creds):
    out = redact(credentialed(CLEAN))
    assert EMAIL not in out and TEST_ACCESS_VALUE not in out
    assert "officer.name%40example.gov.in" not in out
    assert out == "rtsp://<redacted>@103.250.160.189:8554/stream/cam01"


def test_redaction_is_safe_on_a_url_that_never_had_one():
    assert redact(CLEAN) == CLEAN
    assert redact("") == ""


def test_redaction_catches_a_credential_from_anywhere():
    """Not only ones this module added — PyAV echoes the URL into its errors."""
    msg = ("Server returned 401 Unauthorized: "
           "'rtsp://someone%40elsewhere.com:ZZZZ-YYYY-XXXX@host:8554/stream/cam09'")
    out = redact(msg)
    assert "ZZZZ-YYYY-XXXX" not in out
    assert "someone%40elsewhere.com" not in out


def test_without_a_credential_the_url_is_unchanged(no_creds):
    """A deployment against an unauthenticated grid needs no special case."""
    assert configured() is False
    assert credentialed(CLEAN) == CLEAN


def test_required_says_what_is_missing_without_quoting_it(no_creds):
    with pytest.raises(MissingCredential) as e:
        credentialed(CLEAN, required=True)
    assert "SENTINEL_GRID_EMAIL" in str(e.value)
    assert "must not be written into any file" in str(e.value)


def test_the_government_grid_needs_a_credential_and_loopback_does_not(no_creds):
    assert needs_grid_credential(CLEAN) is True
    assert needs_grid_credential("rtsp://127.0.0.1:8554/stream/C-014") is False
    assert needs_grid_credential("file:///var/media/C-014.mp4") is False


def test_a_missing_grid_credential_fails_before_opening_the_socket(
        no_creds, tmp_path, monkeypatch):
    """Thirty tiles each waiting twelve seconds for a 401 is how the live
    wall looked broken when the credential was simply not in the process."""
    import time

    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    svc = SnapshotService()
    t0 = time.perf_counter()
    assert svc.get("cam01", CLEAN) is None
    assert time.perf_counter() - t0 < 0.5
    assert "SENTINEL_GRID_EMAIL" in svc.last_error["cam01"]


def test_an_explicit_authority_is_never_overwritten(creds):
    """A deployment that puts its own credential in the registry keeps it."""
    explicit = "rtsp://someone:else@host:8554/stream/cam01"
    assert credentialed(explicit) == explicit


def test_probe_does_not_open_the_government_grid_without_a_credential(no_creds, monkeypatch):
    """Discovery used to sit on a 401 for every candidate id, then report
    that the estate was empty. The credential was in the environment of the
    ingest workers; the probe never saw it."""
    import av

    from saakshya.live.grid import probe_stream

    def fake_open(*_a, **_k):
        raise AssertionError("must not open the grid without a credential")

    monkeypatch.setattr(av, "open", fake_open)
    info = probe_stream(CLEAN, timeout_s=8)
    assert info["reachable"] is False
    assert "SENTINEL_GRID_EMAIL" in info["error"]


def test_probe_opens_the_credentialed_url_and_redacts_failures(creds, monkeypatch):
    import av

    from saakshya.live.grid import probe_stream

    seen: dict[str, str] = {}

    def fake_open(url, **_k):
        seen["url"] = url
        raise RuntimeError(f"Server returned 401 Unauthorized: '{url}'")

    monkeypatch.setattr(av, "open", fake_open)
    info = probe_stream(CLEAN, timeout_s=1)
    assert EMAIL.replace("@", "%40") in seen["url"]
    assert EMAIL not in info["error"]
    assert TEST_ACCESS_VALUE not in info["error"]
    assert "<redacted>@" in info["error"]
    assert info["reachable"] is False


def test_live_wall_prefers_the_ingest_preview_over_a_second_rtsp_session(
        no_creds, tmp_path, monkeypatch):
    """Thirty ingest sessions plus thirty snapshot sessions is sixty copies.

    The guide says each client gets its own. Serving the frame ingest already
    decoded keeps the wall honest without opening the grid again.
    """
    import numpy as np

    from saakshya.live.preview import write_preview
    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    img[:] = (40, 80, 120)
    write_preview("cam21", img)
    svc = SnapshotService()
    snap = svc.get("cam21", CLEAN)
    assert snap is not None
    assert snap.source == "ingest"
    assert snap.jpeg[:2] == b"\xff\xd8"
    assert svc.stats["served_from_ingest"] == 1


def test_a_stale_ingest_preview_is_served_rather_than_opening_rtsp(
        no_creds, tmp_path, monkeypatch):
    """Sixty seconds old is still the frame ingest already paid for.

    Opening the grid for a fresher copy while thirty sessions are live is how
    the wall stalled. The age is shown on the tile.
    """
    import os
    import time

    import numpy as np

    from saakshya.live.preview import preview_path, write_preview
    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    write_preview("cam01", np.zeros((16, 16, 3), dtype=np.uint8))
    path = preview_path("cam01")
    assert path is not None
    stale = time.time() - 60
    os.utime(path, (stale, stale))
    svc = SnapshotService()
    snap = svc.get("cam01", CLEAN)
    assert snap is not None
    assert snap.source == "ingest-stale"


def test_a_half_hour_ingest_preview_is_served_while_ingest_is_publishing(
        no_creds, tmp_path, monkeypatch):
    """A camera that has not written a JPEG recently still has its last one.

    The 10-minute stale window hid those tiles and the wall reported
    "waiting for ingest" for cameras whose files were on disk.
    """
    import os
    import time

    import av
    import numpy as np

    from saakshya.live.preview import preview_path, write_preview
    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    write_preview("cam02", np.zeros((16, 16, 3), dtype=np.uint8))
    write_preview("cam01", np.zeros((16, 16, 3), dtype=np.uint8))
    path = preview_path("cam01")
    assert path is not None
    stale = time.time() - 1800
    os.utime(path, (stale, stale))

    def fake_open(*_a, **_k):
        raise AssertionError("must not open RTSP for a stale ingest still")

    monkeypatch.setattr(av, "open", fake_open)
    svc = SnapshotService()
    snap = svc.get("cam01", CLEAN)
    assert snap is not None
    assert snap.source == "ingest-stale"
    assert snap.age_s >= 1790


def test_last_ingest_still_is_fallback_when_ingest_dropped_and_capture_fails(
        tmp_path, monkeypatch):
    """Ingest is down and the JPEG is older than the stale window.

    A capture is the live wall. If the grid refuses, the last still is still
    better than a black tile.
    """
    import os
    import time

    import av
    import numpy as np

    from saakshya.live.preview import preview_path, write_preview
    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    monkeypatch.setenv("SENTINEL_GRID_EMAIL", EMAIL)
    monkeypatch.setenv("SENTINEL_GRID_PASSWORD", TEST_ACCESS_VALUE)
    write_preview("cam07", np.zeros((16, 16, 3), dtype=np.uint8))
    path = preview_path("cam07")
    assert path is not None
    stale = time.time() - 900
    os.utime(path, (stale, stale))
    opened = {"n": 0}

    def fake_open(*_a, **_k):
        opened["n"] += 1
        raise RuntimeError("grid refused")

    monkeypatch.setattr(av, "open", fake_open)
    svc = SnapshotService()
    snap = svc.get("cam07", CLEAN)
    assert opened["n"] == 1
    assert snap is not None
    assert snap.source == "ingest-stale"
    assert snap.age_s >= 890


def test_ingest_running_does_not_open_a_second_session_for_a_missing_preview(
        no_creds, tmp_path, monkeypatch):
    import time

    import av
    import numpy as np

    from saakshya.live.preview import write_preview
    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    write_preview("cam02", np.zeros((16, 16, 3), dtype=np.uint8))

    def fake_open(*_a, **_k):
        raise AssertionError("must not open RTSP while ingest is publishing")

    monkeypatch.setattr(av, "open", fake_open)
    svc = SnapshotService()
    t0 = time.perf_counter()
    assert svc.get("cam01", CLEAN) is None
    assert time.perf_counter() - t0 < 0.5
    assert "has not published a still" in svc.last_error["cam01"]


def test_ingest_preview_is_served_when_the_registry_has_no_rtsp(
        no_creds, tmp_path, monkeypatch):
    """Own-feed cameras have no stream URL. The wall must still show ingest stills."""
    import numpy as np

    from saakshya.live.preview import write_preview
    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))
    write_preview("C-014", np.zeros((16, 16, 3), dtype=np.uint8) + 90)
    svc = SnapshotService()
    snap = svc.get("C-014", "")
    assert snap is not None
    assert snap.source == "ingest"
    assert svc.stats["served_from_ingest"] == 1


def test_empty_rtsp_does_not_open_a_decoder(no_creds, tmp_path, monkeypatch):
    import av

    from saakshya.live.snapshot import SnapshotService

    monkeypatch.setenv("SAAKSHYA_EVIDENCE", str(tmp_path))

    def fake_open(*_a, **_k):
        raise AssertionError("must not open a decoder without an RTSP URL")

    monkeypatch.setattr(av, "open", fake_open)
    svc = SnapshotService()
    assert svc.get("C-014", "") is None
    assert "no RTSP source" in svc.last_error["C-014"]


def test_non_stream_urls_are_left_alone(creds):
    """HLS is served by the CDN behind a session cookie.

    Injecting the password into an https URL would send it to a host that does
    not want it, which is how a credential ends up in someone else's access log.
    """
    for url in ("", "file:///var/media/C-014.mp4", "/stream/cam01"):
        assert credentialed(url) == url
