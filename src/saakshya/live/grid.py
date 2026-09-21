"""The Sentinel Camera Grid: catalogue, discovery and endpoints.

This module is the only place that knows how to reach the organiser's live
grid, and it holds three rules that the rest of the system depends on.

**The catalogue is the contract, not the id pattern.** The current Sentinel
portal publishes its authenticated catalogue at `/cameras.json`; a future
deployment can point `SENTINEL_CATALOGUE_URL` at `/api/ingest` without a code
change. Ids are never written into code. Where the catalogue cannot be reached, discovery falls back to
*probing* the documented id pattern and records that it did — a discovered set
is labelled as such and never presented as the authoritative one.

**RTSP over TCP is the analytics transport.** UDP fails across NAT and produces
corrupt frames that look exactly like model bugs; the guide says so and it costs
a day to rediscover. HLS is the fallback for networks where 8554 is blocked.
WebRTC is browser preview and is not used for analytics.

**No credential is ever written down.** The catalogue sits behind a session
login. The credential is read from the environment at call time, never logged,
never echoed into an error, and never persisted. If it is absent, this module
says precisely what is missing rather than trying anything else.
"""
from __future__ import annotations

import contextlib
import base64
import json
import os
from dataclasses import dataclass, field
from typing import Any

#: Documented in the Integrator's Guide. Overridable so a change of host is a
#: configuration change rather than a code change.
# The verified current portal catalogue. Keep the full URL configurable: the
# integration guide describes `/api/ingest`, but this live deployment returns
# 404 for that path and serves the signed-in camera list at `/cameras.json`.
DEFAULT_CATALOGUE_URL = "https://cctv.corp8.cloud/cameras.json"
DEFAULT_HLS_TEMPLATE = "https://cctv.corp8.cloud/{id}/index.m3u8"
DEFAULT_RTSP_TEMPLATE = "rtsp://103.250.160.189:8554/stream/{id}"
DEFAULT_WHEP_TEMPLATE = "http://103.250.160.189:8889/stream/{id}/whep"

#: Only consulted when the catalogue is unreachable. The guide documents the id
#: shape; probing it is using the provided interface, not guessing at a system.
DISCOVERY_PATTERN = "cam{:02d}"
DISCOVERY_RANGE = (1, 60)


class CatalogueUnavailable(RuntimeError):
    """Raised with the specific missing item, never with a credential in it."""


@dataclass
class LiveCamera:
    """One camera as the grid describes it.

    `extra` preserves every field the catalogue supplied that this model does
    not name. Discarding unknown fields loses exactly the information that turns
    out to matter — a department, a junction name, a mounting height — and it
    loses it silently.
    """

    camera_id: str
    name: str | None = None
    rtsp_url: str | None = None
    hls_url: str | None = None
    whep_url: str | None = None
    lat: float | None = None
    lon: float | None = None
    district: str | None = None
    department: str | None = None
    location: str | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    declared_fps: float | None = None
    source: str = "catalogue"          # catalogue | probe
    extra: dict[str, Any] = field(default_factory=dict)

    def to_registry_row(self) -> dict[str, Any]:
        """The row a discovery pass may write.

        Curated fields it does not know are omitted, not sent as None. A probe
        that reports `name=None` and a probe that omits `name` look the same to
        a naive upsert and mean opposite things; omitting says "I have nothing
        to say about this", which is the truth and is what the store honours.
        """
        row: dict[str, Any] = {
            "camera_id": self.camera_id,
            "rtsp_url": self.rtsp_url, "hls_url": self.hls_url,
            "whep_url": self.whep_url,
            "codec": self.codec, "width": self.width, "height": self.height,
            "declared_fps": self.declared_fps,
            # Capability is measured from the stream, never taken from a
            # catalogue. A catalogue records what a camera is; it cannot know
            # what a camera can do.
            "tier": "UNASSIGNED",
            "enabled": True,
            "source_domain": "GOVERNMENT",
        }
        for key, value in (("name", self.name or self.location),
                           ("site", self.location),
                           ("district", self.district),
                           ("department", self.department),
                           ("lat", self.lat), ("lon", self.lon)):
            if value is not None:
                row[key] = value
        return row

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "extra"}
        d["extra"] = self.extra
        return d


@dataclass
class GridConfig:
    catalogue_url: str = DEFAULT_CATALOGUE_URL
    rtsp_template: str = DEFAULT_RTSP_TEMPLATE
    hls_template: str = DEFAULT_HLS_TEMPLATE
    whep_template: str = DEFAULT_WHEP_TEMPLATE
    timeout_s: float = 20.0

    @classmethod
    def from_env(cls) -> GridConfig:
        return cls(
            catalogue_url=os.environ.get("SENTINEL_CATALOGUE_URL",
                                         DEFAULT_CATALOGUE_URL),
            rtsp_template=os.environ.get("SENTINEL_RTSP_TEMPLATE",
                                         DEFAULT_RTSP_TEMPLATE),
            hls_template=os.environ.get("SENTINEL_HLS_TEMPLATE",
                                        DEFAULT_HLS_TEMPLATE),
            whep_template=os.environ.get("SENTINEL_WHEP_TEMPLATE",
                                         DEFAULT_WHEP_TEMPLATE),
        )

    def rtsp(self, cam_id: str) -> str:
        return self.rtsp_template.format(id=cam_id)

    def hls(self, cam_id: str) -> str:
        return self.hls_template.format(id=cam_id)

    def whep(self, cam_id: str) -> str:
        return self.whep_template.format(id=cam_id)


def _credential() -> dict[str, str]:
    """Session material for the CDN host, from the environment only.

    Returns headers, never the raw value to a caller that might log it. Three
    forms are accepted because the portal's mechanism is a session login and a
    team member may hold any of them:

      SENTINEL_GRID_COOKIE   a session cookie captured after signing in
      SENTINEL_GRID_TOKEN    a bearer token, if the portal issues one
      SENTINEL_GRID_BASIC    user:pass for HTTP basic, if that is the mechanism
      SENTINEL_GRID_EMAIL / SENTINEL_GRID_PASSWORD
                             used for an in-memory portal form-login

    Nothing here is written to disk, echoed into an exception, or committed.
    """
    headers: dict[str, str] = {}
    cookie = os.environ.get("SENTINEL_GRID_COOKIE")
    token = os.environ.get("SENTINEL_GRID_TOKEN")
    basic = os.environ.get("SENTINEL_GRID_BASIC")
    if cookie:
        headers["Cookie"] = cookie
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic:
        headers["Authorization"] = "Basic " + base64.b64encode(
            basic.encode()).decode()
    return headers


def has_credential() -> bool:
    return bool(_credential() or (
        os.environ.get("SENTINEL_GRID_EMAIL")
        and os.environ.get("SENTINEL_GRID_PASSWORD")))


def fetch_catalogue(cfg: GridConfig | None = None) -> list[LiveCamera]:
    """Fetch and normalise the authenticated Sentinel catalogue.

    Several plausible JSON shapes are accepted — a bare list, `{"cameras": …}`,
    `{"items": …}` — because an unexpected layout should be a mapping change
    rather than a rewrite on the evening before an evaluation.
    """
    import httpx

    cfg = cfg or GridConfig.from_env()
    headers = _credential()
    email = os.environ.get("SENTINEL_GRID_EMAIL")
    password = os.environ.get("SENTINEL_GRID_PASSWORD")
    try:
        with httpx.Client(headers=headers, timeout=cfg.timeout_s,
                          follow_redirects=True) as client:
            # The current portal uses a regular form login, not HTTP Basic.
            # Keep its resulting cookie only in this client; do not expose it
            # through config, logs, the database, or process environment.
            if email and password and not headers:
                login_url = str(httpx.URL(cfg.catalogue_url).join("/auth/login"))
                login = client.post(login_url, data={
                    "email": email, "password": password,
                })
                if login.status_code >= 400:
                    raise CatalogueUnavailable(
                        f"portal sign-in returned HTTP {login.status_code}")
            r = client.get(cfg.catalogue_url, follow_redirects=False)
    except Exception as exc:
        if isinstance(exc, CatalogueUnavailable):
            raise
        raise CatalogueUnavailable(
            f"catalogue at {cfg.catalogue_url} is unreachable: "
            f"{type(exc).__name__}") from exc

    if r.status_code in (301, 302, 303, 307, 308):
        raise CatalogueUnavailable(
            f"catalogue at {cfg.catalogue_url} redirected to the sign-in page — "
            "the CDN host requires a signed-in session. Provide either the "
            "registered SENTINEL_GRID_EMAIL and SENTINEL_GRID_PASSWORD for an "
            "in-memory sign-in, or a session credential. It must not be written "
            "into any file in this repository.")
    if r.status_code == 401 or r.status_code == 403:
        raise CatalogueUnavailable(
            f"catalogue returned {r.status_code}: the supplied session material "
            "was rejected. Re-capture it; do not retry with variations.")
    if r.status_code >= 400:
        raise CatalogueUnavailable(
            f"catalogue returned HTTP {r.status_code}")

    try:
        payload = r.json()
    except json.JSONDecodeError as exc:
        raise CatalogueUnavailable(
            "catalogue did not return JSON — the session may have expired and "
            "returned a login page") from exc

    return parse_catalogue(payload, cfg)


def parse_catalogue(payload: Any, cfg: GridConfig | None = None
                    ) -> list[LiveCamera]:
    cfg = cfg or GridConfig.from_env()
    if isinstance(payload, dict):
        for key in ("cameras", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            # A mapping of id -> record is also plausible.
            if all(isinstance(v, dict) for v in payload.values()):
                payload = [{"id": k, **v} for k, v in payload.items()]
    if not isinstance(payload, list):
        raise CatalogueUnavailable(
            f"catalogue shape not recognised: {type(payload).__name__}")
    return [normalise(e, cfg) for e in payload]


#: Field names this model claims. Anything else lands in `extra`.
_KNOWN = {
    "id", "camera_id", "cameraId", "name", "title", "label",
    "rtsp", "rtsp_url", "hls", "hls_url", "whep", "whep_url", "urls",
    "lat", "latitude", "lon", "lng", "longitude", "location", "coordinates",
    "district", "department", "dept", "site", "place", "area",
    "codec", "width", "height", "resolution", "fps", "declared_fps",
    "properties",
}


def normalise(entry: dict[str, Any], cfg: GridConfig | None = None) -> LiveCamera:
    """One catalogue record to a `LiveCamera`, preserving what we do not model."""
    cfg = cfg or GridConfig.from_env()
    e = dict(entry)
    raw_props = e.get("properties")
    props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
    raw_urls = e.get("urls")
    urls: dict[str, Any] = raw_urls if isinstance(raw_urls, dict) else {}

    cam_id = str(e.get("id") or e.get("camera_id") or e.get("cameraId") or "").strip()
    loc = e.get("location")
    lat = lon = None
    if isinstance(loc, dict):
        lat = _f(loc.get("lat") or loc.get("latitude"))
        lon = _f(loc.get("lon") or loc.get("lng") or loc.get("longitude"))
        loc_name = loc.get("name") or loc.get("site")
    else:
        loc_name = loc if isinstance(loc, str) else None
    if lat is None:
        lat = _f(e.get("lat") or e.get("latitude"))
    if lon is None:
        lon = _f(e.get("lon") or e.get("lng") or e.get("longitude"))
    coords = e.get("coordinates")
    if lat is None and isinstance(coords, (list, tuple)) and len(coords) == 2:
        # GeoJSON order is [lon, lat] — getting this backwards puts Gujarat in
        # the Indian Ocean, which at least fails visibly.
        lon, lat = _f(coords[0]), _f(coords[1])

    width = _i(e.get("width") or props.get("width"))
    height = _i(e.get("height") or props.get("height"))
    res = e.get("resolution") or props.get("resolution")
    if width is None and isinstance(res, str) and "x" in res.lower():
        parts = res.lower().split("x")
        width, height = _i(parts[0]), _i(parts[1])

    extra = {k: v for k, v in e.items() if k not in _KNOWN}

    return LiveCamera(
        camera_id=cam_id,
        name=e.get("name") or e.get("title") or e.get("label") or loc_name,
        rtsp_url=(e.get("rtsp_url") or e.get("rtsp") or urls.get("rtsp")
                  or (cfg.rtsp(cam_id) if cam_id else None)),
        hls_url=(e.get("hls_url") or e.get("hls") or urls.get("hls")
                 or (cfg.hls(cam_id) if cam_id else None)),
        whep_url=(e.get("whep_url") or e.get("whep") or urls.get("whep")
                  or (cfg.whep(cam_id) if cam_id else None)),
        lat=lat, lon=lon,
        district=e.get("district"),
        department=e.get("department") or e.get("dept"),
        location=loc_name or e.get("site") or e.get("place") or e.get("area"),
        codec=e.get("codec") or props.get("codec"),
        width=width, height=height,
        declared_fps=_f(e.get("declared_fps") or e.get("fps") or props.get("fps")),
        source="catalogue",
        extra=extra)


def discover_by_probe(cfg: GridConfig | None = None, *,
                      first: int = DISCOVERY_RANGE[0],
                      last: int = DISCOVERY_RANGE[1],
                      timeout_s: float = 8.0,
                      workers: int = 6) -> list[LiveCamera]:
    """Find cameras by opening the documented RTSP id pattern.

    Used only when the catalogue cannot be reached. This is discovery, not
    hard-coding: it enumerates candidates against the documented interface and
    keeps only the ones that actually answer, and every camera it returns is
    marked `source="probe"` so no report can mistake it for the authoritative
    set.

    Nothing outside the documented endpoint is contacted.
    """
    import concurrent.futures as cf

    cfg = cfg or GridConfig.from_env()
    candidates = [DISCOVERY_PATTERN.format(i) for i in range(first, last + 1)]

    def probe(cam_id: str) -> LiveCamera | None:
        info = probe_stream(cfg.rtsp(cam_id), timeout_s=timeout_s)
        if not info.get("reachable"):
            return None
        return LiveCamera(
            camera_id=cam_id, name=None,
            rtsp_url=cfg.rtsp(cam_id), hls_url=cfg.hls(cam_id),
            whep_url=cfg.whep(cam_id),
            codec=info.get("codec"), width=info.get("width"),
            height=info.get("height"),
            declared_fps=info.get("declared_fps"),
            source="probe")

    found: list[LiveCamera] = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for cam in pool.map(probe, candidates):
            if cam is not None:
                found.append(cam)
    found.sort(key=lambda c: c.camera_id)
    return found


def probe_stream(url: str, *, timeout_s: float = 8.0) -> dict[str, Any]:
    """Open a stream just far enough to learn what it is, then close it.

    Deliberately cheap and deliberately closed immediately: every client gets
    its own copy of the stream, so a probe that lingers is load the organiser's
    grid has to carry for nothing.

    Credentials are injected here, at the socket, the same way ingest and the
    snapshot service do. A probe that opens the clean URL against a grid that
    authenticates spends its whole timeout on a 401 and reports the estate as
    empty.
    """
    import av

    from saakshya.live.credentials import (
        configured,
        credentialed,
        needs_grid_credential,
        redact,
    )

    av.logging.set_level(av.logging.FATAL)
    out: dict[str, Any] = {"url_scheme": url.split(":", 1)[0], "reachable": False}
    if needs_grid_credential(url) and not configured():
        out["error"] = ("grid credential not configured in this process; "
                        "set SENTINEL_GRID_EMAIL and SENTINEL_GRID_PASSWORD")
        return out
    container = None
    try:
        container = av.open(
            credentialed(url),
            options={"rtsp_transport": "tcp",
                     "stimeout": str(int(timeout_s * 1_000_000))},
            timeout=timeout_s)
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            out["error"] = "no video stream"
            return out
        cc = stream.codec_context
        # Geometry lives on the video stream in PyAV's stubs even though the
        # runtime exposes it on the codec context too. Read it from the stream
        # where the type checker can see it.
        width = getattr(stream, "width", None) or getattr(cc, "width", None)
        height = getattr(stream, "height", None) or getattr(cc, "height", None)
        out.update({
            "reachable": True,
            "codec": cc.name,
            "width": width, "height": height,
            "time_base": str(stream.time_base),
            # Reported, and immediately labelled: the guide is explicit that the
            # declared rate often does not match delivery, and every timing
            # decision in this system uses PTS instead.
            "declared_fps": (float(stream.average_rate)
                             if stream.average_rate else None),
            "declared_fps_note": "reported by the container; not trusted for timing",
        })
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {redact(str(exc))[:160]}"
        return out
    finally:
        if container is not None:
            # Closing must never mask the probe's own result.
            with contextlib.suppress(Exception):
                container.close()


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    try:
        return int(float(v)) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None
