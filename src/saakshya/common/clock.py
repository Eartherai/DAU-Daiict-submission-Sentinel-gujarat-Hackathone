"""Time handling.

The single most important rule in this codebase: **motion timing never comes
from wall-clock arrival time.** It comes from the stream's presentation
timestamp (PTS).

The organiser's sandbox replays a buffered GOP on connect, so the first ~2s of
frames arrive faster than real time. Any tracker that timestamps by arrival
computes impossible velocities on every connect and every reconnect. This module
provides the normalised timeline used everywhere instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class CameraClock:
    """Maps a camera's stream PTS onto a normalised wall-clock timeline.

    We do not trust the camera's own clock (many CCTV devices drift badly, and
    the challenge's own material warns that departments run heterogeneous
    infrastructure). Instead we anchor the first observed PTS of a segment to
    the ingest wall-clock, then advance purely by PTS delta. Drift between that
    projection and ingest time is *measured and reported* rather than silently
    absorbed — it becomes a registry attribute.
    """

    camera_id: str
    anchor_wall: datetime | None = None
    anchor_pts_s: float | None = None
    last_pts_s: float | None = None
    drift_samples: list[float] = field(default_factory=list)

    def reset(self, wall: datetime, pts_s: float) -> None:
        """Called on connect and on every SEGMENT_BREAK."""
        self.anchor_wall = wall
        self.anchor_pts_s = pts_s
        self.last_pts_s = pts_s

    def project(self, pts_s: float, ingest_wall: datetime) -> datetime:
        if self.anchor_wall is None or self.anchor_pts_s is None:
            self.reset(ingest_wall, pts_s)
            return ingest_wall
        delta = pts_s - self.anchor_pts_s
        projected = self.anchor_wall.timestamp() + delta
        # Measure, don't correct: drift is diagnostic signal for the registry.
        self.drift_samples.append(ingest_wall.timestamp() - projected)
        if len(self.drift_samples) > 512:
            self.drift_samples.pop(0)
        self.last_pts_s = pts_s
        return datetime.fromtimestamp(projected, UTC)

    @property
    def drift_s(self) -> float:
        if not self.drift_samples:
            return 0.0
        s = sorted(self.drift_samples)
        return s[len(s) // 2]
