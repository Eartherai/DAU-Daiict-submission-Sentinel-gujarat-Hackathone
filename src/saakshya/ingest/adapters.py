"""Vendor-neutral camera connection adapters.

Adapters normalize connection metadata at the boundary. The stream worker
continues to own decoding, PTS handling, reconnects, and fan-out; an adapter
only resolves the transport URL and its options. This keeps adding ONVIF or a
vendor SDK from duplicating the reliability layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class CameraSource:
    camera_id: str
    url: str
    protocol: str
    options: dict[str, str] = field(default_factory=dict)


class CameraAdapter(Protocol):
    """Resolve a catalogue entry into a stream source."""

    protocol: str

    def resolve(self, entry: dict[str, object]) -> CameraSource:
        """Return a validated source or raise ``ValueError``."""


def _required_text(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"catalogue entry requires non-empty {key!r}")
    return value.strip()


class URLAdapter:
    """Adapter for transports whose catalogue entry already contains a URL."""

    protocol = "url"
    schemes: frozenset[str] = frozenset()

    def resolve(self, entry: dict[str, object]) -> CameraSource:
        camera_id = _required_text(entry, "camera_id")
        url = _required_text(entry, "url")
        parsed = urlparse(url)
        if parsed.scheme.lower() not in self.schemes:
            allowed = ", ".join(sorted(self.schemes))
            raise ValueError(
                f"{self.protocol} adapter cannot resolve {parsed.scheme or 'no'} "
                f"scheme; expected one of {allowed}")
        return CameraSource(camera_id, url, self.protocol)


class RTSPAdapter(URLAdapter):
    protocol = "rtsp"
    schemes = frozenset({"rtsp", "rtsps"})


class HLSAdapter(URLAdapter):
    protocol = "hls"
    schemes = frozenset({"http", "https"})


class WebRTCAdapter(URLAdapter):
    protocol = "webrtc"
    schemes = frozenset({"http", "https", "whep", "webrtc"})


class ONVIFAdapter:
    """Explicit seam for ONVIF discovery without pretending to implement it.

    ONVIF discovery normally needs device credentials and a network exchange.
    The adapter accepts a resolved media URL from a discovery client and
    rejects entries that have not completed that step.
    """

    protocol = "onvif"

    def resolve(self, entry: dict[str, object]) -> CameraSource:
        source = RTSPAdapter().resolve(entry)
        return CameraSource(source.camera_id, source.url, self.protocol,
                            {"discovery": "onvif"})


class VendorAdapter:
    """Generic vendor-API seam; vendor clients provide the resolved URL."""

    protocol = "vendor"

    def resolve(self, entry: dict[str, object]) -> CameraSource:
        camera_id = _required_text(entry, "camera_id")
        url = _required_text(entry, "url")
        parsed = urlparse(url)
        if parsed.scheme not in {"rtsp", "rtsps", "http", "https"}:
            raise ValueError("vendor adapter requires a resolved media URL")
        return CameraSource(camera_id, url, self.protocol,
                            {"vendor": str(entry.get("vendor", "unknown"))})


ADAPTERS: dict[str, CameraAdapter] = {
    "rtsp": RTSPAdapter(),
    "hls": HLSAdapter(),
    "webrtc": WebRTCAdapter(),
    "onvif": ONVIFAdapter(),
    "vendor": VendorAdapter(),
}


def adapter_for(protocol: str) -> CameraAdapter:
    try:
        return ADAPTERS[protocol.lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported camera protocol {protocol!r}") from exc
