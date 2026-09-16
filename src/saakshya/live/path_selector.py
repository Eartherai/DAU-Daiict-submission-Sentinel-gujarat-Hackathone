"""Evidence-based browser stream path selection.

Keeps the verified managed gateway architecture (RTSP → MediaMTX → WHEP) and
chooses per-camera transport/transcode mode from measured metadata rather than
hard-coding every camera to one path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class StreamPath(str, Enum):
    DIRECT_H264 = "DIRECT_H264"
    HEVC_NATIVE = "HEVC_NATIVE"
    HEVC_TRANSCODED_H264 = "HEVC_TRANSCODED_H264"
    HLS_FALLBACK = "HLS_FALLBACK"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class CameraStreamProfile:
    camera_id: str
    codec: str | None = None
    resolution: str | None = None
    has_b_frames: bool | None = None
    browser_hevc_supported: bool = False
    raw_stable: bool | None = None
    whep_stable: bool | None = None
    preferred: StreamPath | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PathDecision:
    camera_id: str
    path: StreamPath
    transport: str
    reason: str
    needs_transcode: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = self.path.value
        return d


class StreamPathSelector:
    """Select a browser-facing path from measured camera evidence."""

    def select(self, profile: CameraStreamProfile) -> PathDecision:
        if profile.preferred is not None:
            return PathDecision(
                camera_id=profile.camera_id,
                path=profile.preferred,
                transport=self._transport(profile.preferred),
                reason="explicit preferred override",
                needs_transcode=profile.preferred == StreamPath.HEVC_TRANSCODED_H264,
                metadata=self._meta(profile),
            )

        codec = (profile.codec or "").lower()
        if profile.raw_stable is False and profile.whep_stable is False:
            return PathDecision(
                camera_id=profile.camera_id,
                path=StreamPath.DEGRADED,
                transport="none",
                reason="raw and whep both unstable in measured evidence",
                metadata=self._meta(profile),
            )

        if codec in {"hevc", "h265", "h.265"}:
            if profile.browser_hevc_supported and profile.whep_stable is not False:
                return PathDecision(
                    camera_id=profile.camera_id,
                    path=StreamPath.HEVC_NATIVE,
                    transport="whep",
                    reason="HEVC source with measured/assumed browser HEVC support",
                    metadata=self._meta(profile),
                )
            return PathDecision(
                camera_id=profile.camera_id,
                path=StreamPath.HEVC_TRANSCODED_H264,
                transport="whep",
                reason="HEVC source; browser HEVC unsupported or unverified — transcode",
                needs_transcode=True,
                metadata=self._meta(profile),
            )

        if codec in {"h264", "avc", "h.264", ""}:
            if profile.has_b_frames:
                return PathDecision(
                    camera_id=profile.camera_id,
                    path=StreamPath.DIRECT_H264,
                    transport="whep",
                    reason="H.264 with B-frames requires gateway remux/transcode to bf=0",
                    needs_transcode=True,
                    metadata=self._meta(profile),
                )
            if profile.whep_stable is False:
                return PathDecision(
                    camera_id=profile.camera_id,
                    path=StreamPath.HLS_FALLBACK,
                    transport="hls",
                    reason="H.264 WHEP unstable; fall back to HLS",
                    metadata=self._meta(profile),
                )
            return PathDecision(
                camera_id=profile.camera_id,
                path=StreamPath.DIRECT_H264,
                transport="whep",
                reason="H.264 browser-safe path (verified managed gateway)",
                metadata=self._meta(profile),
            )

        return PathDecision(
            camera_id=profile.camera_id,
            path=StreamPath.DEGRADED,
            transport="snapshot",
            reason=f"unsupported/unknown codec {profile.codec!r}",
            metadata=self._meta(profile),
        )

    @staticmethod
    def _transport(path: StreamPath) -> str:
        return {
            StreamPath.DIRECT_H264: "whep",
            StreamPath.HEVC_NATIVE: "whep",
            StreamPath.HEVC_TRANSCODED_H264: "whep",
            StreamPath.HLS_FALLBACK: "hls",
            StreamPath.DEGRADED: "snapshot",
        }[path]

    @staticmethod
    def _meta(profile: CameraStreamProfile) -> dict[str, Any]:
        return {
            "codec": profile.codec,
            "resolution": profile.resolution,
            "has_b_frames": profile.has_b_frames,
            "browser_hevc_supported": profile.browser_hevc_supported,
            "raw_stable": profile.raw_stable,
            "whep_stable": profile.whep_stable,
            "notes": list(profile.notes),
        }
