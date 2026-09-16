#!/usr/bin/env python3
"""Conservative, offline pre-demo submission check.

The check inspects repository artifacts and local configuration only.  It does
not turn an absent credential, URL, or running service into a green result.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    category: str
    name: str
    status: str
    detail: str


def _path(root: Path, relative: str, category: str, *, required: bool = True) -> Check:
    path = root / relative
    if path.exists():
        return Check(category, relative, "READY", f"artifact present; runtime not probed ({path})")
    status = "BLOCKER" if required else "WARNING"
    return Check(category, relative, status, "artifact is not present")


def _database(root: Path) -> Check:
    configured = os.environ.get("SAAKSHYA_DB", "sqlite:///var/saakshya.db")
    if not configured.startswith("sqlite:///"):
        return Check("database", "SAAKSHYA_DB", "WARNING",
                     "non-SQLite database configured; connectivity and schema not probed")
    db = root / configured.removeprefix("sqlite:///")
    if not db.exists():
        return Check("database", "SAAKSHYA_DB", "BLOCKER",
                     f"configured SQLite file is missing: {db}")
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
            tables = connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
    except sqlite3.Error as exc:
        return Check("database", "SAAKSHYA_DB", "BLOCKER", f"SQLite read failed: {exc}")
    return Check("database", "SAAKSHYA_DB", "READY",
                 f"SQLite file readable ({tables} tables); live service not probed")


def _stream_gateway() -> Check:
    endpoint = os.environ.get("SAAKSHYA_WHEP_BASE", "").strip()
    credentials = bool(
        os.environ.get("SENTINEL_GRID_EMAIL") and os.environ.get("SENTINEL_GRID_PASSWORD")
    )
    if not endpoint and not credentials:
        return Check("stream gateway", "WHEP/grid", "WARNING",
                     "no WHEP endpoint or Sentinel credentials configured; "
                     "live gateway unavailable")
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return Check("stream gateway", "SAAKSHYA_WHEP_BASE", "BLOCKER",
                         "configured WHEP base is not a valid HTTP(S) URL")
    return Check("stream gateway", "WHEP/grid", "WARNING",
                 "configuration is present; gateway reachability/authentication not probed")


def _path_selector(root: Path) -> Check:
    path = root / "src/saakshya/live/path_selector.py"
    if not path.exists():
        return Check("media path", "StreamPathSelector", "BLOCKER", "module missing")
    return Check("media path", "StreamPathSelector", "READY",
                 "module present; H.264 direct / HEVC transcode rules")


def _demo_cam01(root: Path) -> Check:
    path = root / "config/demo_cam01.yaml"
    if not path.exists():
        return Check("demo", "demo_cam01.yaml", "WARNING", "golden demo config missing")
    return Check("demo", "demo_cam01.yaml", "READY", "golden cam01 config present")


def _overlay(root: Path) -> Check:
    app = root / "ui/app.js"
    if not app.exists():
        return Check("frontend", "overlay", "BLOCKER", "ui/app.js missing")
    text = app.read_text(errors="ignore")
    if "startDetectionOverlay" in text and "requestAnimationFrame" in text:
        return Check("frontend", "overlay", "READY",
                     "canvas/rAF overlay independent of WHEP playback")
    return Check("frontend", "overlay", "WARNING", "overlay helpers not found")


def _mediamtx_binary(root: Path) -> Check:
    binary = root / "var/bin/mediamtx"
    if binary.exists():
        return Check("binaries", "mediamtx", "READY", f"present at {binary}")
    return Check("binaries", "mediamtx", "BLOCKER", "var/bin/mediamtx missing")


def _ai_runtime_report(root: Path) -> Check:
    path = root / "reports/GOV_CAM01_AI_RUNTIME_CERTIFICATION.md"
    if path.exists():
        return Check("evidence", "AI runtime cert", "READY", "report present")
    return Check("evidence", "AI runtime cert", "WARNING",
                 "Phase A AI-off/on report not yet written")


def _phase9_reports(root: Path) -> list[Check]:
    required = [
        ("golden e2e", "reports/GOLDEN_CAM01_END_TO_END_CERTIFICATION.md"),
        ("wall scaling", "reports/GOVERNMENT_WALL_SCALING_CERTIFICATION.md"),
        ("failure isolation", "reports/GOV_FAILURE_ISOLATION_CERTIFICATION.md"),
        ("HEVC path", "reports/GOV_HEVC_PATH_VALIDATION.md"),
    ]
    out = []
    for name, rel in required:
        path = root / rel
        out.append(Check(
            "evidence", name,
            "READY" if path.exists() else "WARNING",
            "report present" if path.exists() else f"{rel} missing",
        ))
    return out


def _environment() -> list[Check]:
    checks = []
    for name in ("SAAKSHYA_DB", "SAAKSHYA_EVIDENCE"):
        checks.append(Check("env vars", name, "READY" if os.environ.get(name) else "WARNING",
                            "set in process environment" if os.environ.get(name)
                            else "not set; documented default will be used"))
    for name in ("SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD"):
        checks.append(Check("env vars", name, "READY" if os.environ.get(name) else "WARNING",
                            "set (value redacted)" if os.environ.get(name)
                            else "not set; live government access is not available"))
    for name in ("SAAKSHYA_MAP_TILES", "SAAKSHYA_WHEP_BASE", "SAAKSHYA_MODELS_OFFLINE"):
        checks.append(Check("env vars", name, "READY" if os.environ.get(name) else "WARNING",
                            "set (value not displayed)" if os.environ.get(name)
                            else "not set; optional capability is not configured"))
    return checks


def check(root: Path = ROOT) -> list[Check]:
    """Return artifact/configuration findings without starting services."""
    checks = [
        _path(root, "src/saakshya/api/app.py", "backend"),
        _path(root, "ui/index.html", "frontend"),
        _database(root),
        _stream_gateway(),
        _mediamtx_binary(root),
        _path_selector(root),
        _overlay(root),
        _demo_cam01(root),
        _ai_runtime_report(root),
        *_phase9_reports(root),
        _path(root, "src/saakshya/analytics", "analytics"),
        _path(root, "src/saakshya/watchlist", "watchlist"),
        _path(root, "src/saakshya/gis", "GIS"),
        _path(root, "src/saakshya/evidence", "evidence"),
        _path(root, "src/saakshya/models", "models"),
        _path(root, "var/submission", "files", required=False),
        _path(root, "reports/FINAL_EVIDENCE_MATRIX.md", "files", required=False),
    ]
    checks.extend(_environment())
    return checks


def summary(checks: list[Check]) -> str:
    counts = {status: sum(c.status == status for c in checks)
              for status in ("READY", "WARNING", "BLOCKER")}
    overall = "BLOCKER" if counts["BLOCKER"] else "WARNING" if counts["WARNING"] else "READY"
    lines = [f"PRE-DEMO CHECK: {overall}",
             f"READY={counts['READY']} WARNING={counts['WARNING']} BLOCKER={counts['BLOCKER']}",
             ""]
    lines.extend(f"{c.status:<7} [{c.category}] {c.name}: {c.detail}" for c in checks)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    checks = check(args.root.resolve())
    print(summary(checks))
    return 2 if any(c.status == "BLOCKER" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
