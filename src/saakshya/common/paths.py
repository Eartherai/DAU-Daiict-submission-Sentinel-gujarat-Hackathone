"""Path formatting that cannot fail.

`Path.relative_to` raises `ValueError` when the path is not under the base — and
a relative path is never under an absolute one. Tools used it to shorten a
filename for a success message, which meant `--out var/reports/run.json` ended a
ten-minute live capture with a traceback *while printing the line saying the
report had been written*, taking the report with it.

Formatting a path for a human to read must never be able to lose the work being
reported on. `display` shortens when it can and returns the path unchanged when
it cannot.
"""
from __future__ import annotations

from pathlib import Path


def display(path: Path | str, base: Path | str | None = None) -> str:
    """Return `path` relative to `base` when that is possible, else as given."""
    p = Path(path)
    if base is None:
        return str(p)
    try:
        return str(p.resolve().relative_to(Path(base).resolve()))
    except (ValueError, OSError):
        return str(p)
