"""VMS adapter contracts and demonstration connectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from saakshya.common.clock import iso, utc_now
from saakshya.ingest.adapters import ONVIFAdapter as StreamONVIF
from saakshya.ingest.adapters import RTSPAdapter as StreamRTSP
from saakshya.ingest.adapters import VendorAdapter


@dataclass(frozen=True, slots=True)
class VMSHealth:
    system_id: str
    state: str
    cameras: int
    last_sync: datetime
    detail: str
    provenance: str


class VMSAdapter(Protocol):
    """Federation seam. Implementations must not pretend to own the VMS."""

    system_id: str
    department: str
    vendor: str
    protocol: str
    provenance: str

    def discover_cameras(self) -> list[dict[str, Any]]:
        ...

    def get_camera_status(self, camera_id: str) -> dict[str, Any]:
        ...

    def get_stream_url(self, camera_id: str) -> str | None:
        ...

    def get_metadata(self, camera_id: str) -> dict[str, Any]:
        ...

    def subscribe_events(self) -> list[dict[str, Any]]:
        ...

    def health_check(self) -> VMSHealth:
        ...


@dataclass
class _BaseSystem:
    system_id: str
    department: str
    vendor: str
    protocol: str
    provenance: str = "DEMO/TEST"
    cameras: list[dict[str, Any]] = field(default_factory=list)

    def discover_cameras(self) -> list[dict[str, Any]]:
        return list(self.cameras)

    def get_camera_status(self, camera_id: str) -> dict[str, Any]:
        for cam in self.cameras:
            if cam["camera_id"] == camera_id:
                return {"camera_id": camera_id, "state": cam.get("state", "UNKNOWN")}
        return {"camera_id": camera_id, "state": "UNKNOWN"}

    def get_stream_url(self, camera_id: str) -> str | None:
        for cam in self.cameras:
            if cam["camera_id"] == camera_id:
                return cam.get("url")
        return None

    def get_metadata(self, camera_id: str) -> dict[str, Any]:
        for cam in self.cameras:
            if cam["camera_id"] == camera_id:
                return dict(cam)
        return {}

    def subscribe_events(self) -> list[dict[str, Any]]:
        return []

    def health_check(self) -> VMSHealth:
        return VMSHealth(
            system_id=self.system_id,
            state="HEALTHY" if self.cameras else "UNKNOWN",
            cameras=len(self.cameras),
            last_sync=utc_now(),
            detail=f"{len(self.cameras)} cameras advertised by {self.protocol} adapter",
            provenance=self.provenance,
        )


class RTSPAdapter(_BaseSystem):
    """Federation wrapper around the stream-layer RTSP adapter."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(protocol="rtsp", **kwargs)
        self._stream = StreamRTSP()

    def get_stream_url(self, camera_id: str) -> str | None:
        url = super().get_stream_url(camera_id)
        if not url:
            return None
        src = self._stream.resolve({"camera_id": camera_id, "url": url})
        return src.url


class ONVIFAdapter(_BaseSystem):
    """ONVIF discovery seam. Does not perform network ONVIF probing."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(protocol="onvif", **kwargs)
        self._stream = StreamONVIF()

    def get_stream_url(self, camera_id: str) -> str | None:
        url = super().get_stream_url(camera_id)
        if not url:
            return None
        src = self._stream.resolve({"camera_id": camera_id, "url": url})
        return src.url


class GenericVMSAdapter(_BaseSystem):
    """Vendor-API seam. Requires a resolved media URL, never invents one."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(protocol="vendor", **kwargs)
        self._stream = VendorAdapter()


def demo_connected_systems() -> list[dict[str, Any]]:
    """Operator dashboard rows. Provenance is DEMO/TEST, not government VMS."""
    systems = [
        RTSPAdapter(
            system_id="police-rtsp",
            department="Home (Police)",
            vendor="Sentinel / RTSP",
            cameras=[{"camera_id": "cam01", "url": "rtsp://127.0.0.1/stream/cam01",
                      "state": "STREAMING"}],
        ),
        GenericVMSAdapter(
            system_id="transport-vms",
            department="Transport",
            vendor="Generic VMS",
            cameras=[{"camera_id": "T-01", "url": "rtsp://127.0.0.1/stream/t01",
                      "state": "UNKNOWN"}],
        ),
        ONVIFAdapter(
            system_id="municipal-onvif",
            department="Municipal",
            vendor="ONVIF-class",
            cameras=[],
        ),
        GenericVMSAdapter(
            system_id="private-eligible",
            department="Private (eligible)",
            vendor="Generic VMS",
            cameras=[],
        ),
    ]
    rows = []
    for sys in systems:
        h = sys.health_check()
        rows.append({
            "system": sys.system_id,
            "department": sys.department,
            "vendor": sys.vendor,
            "protocol": sys.protocol,
            "cameras": h.cameras,
            "health": h.state,
            "last_sync": iso(h.last_sync),
            "provenance": h.provenance,
            "note": h.detail,
        })
    return rows
