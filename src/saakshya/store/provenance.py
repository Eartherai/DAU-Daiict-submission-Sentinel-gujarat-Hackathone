"""Which stores must never receive live government observations.

Provenance is never mixed: demonstration and evaluation state is kept apart from
live capture, so a measured result can never be quietly improved by a demo run.

The rule matches the **file name**, not a substring of the database URL. The
substring form refused `var/route_demo.db` — a store that is not the demo store
— and a guard that fires on names it does not mean gets worked around, after
which it protects nothing.
"""
from __future__ import annotations

from pathlib import Path

#: Stores that hold demonstration or evaluation state.
PROTECTED_STORES = frozenset({"demo.db", "saakshya.db"})


def redacted(url: str) -> str:
    """A database URL fit for a log line or a report: the password masked.

    A SQLite URL has no credentials; a PostgreSQL URL carries the password,
    and the API's start-up log and the performance reports printed it.
    """
    try:
        from sqlalchemy import make_url
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return url.split("://", 1)[0] + "://***" if "@" in url else url


def store_name(url: str) -> str:
    """The file name a SQLite URL points at."""
    return Path(url.replace("sqlite:///", "").split("?")[0]).name


def refuses_live_writes(url: str) -> bool:
    """Whether live observations must be kept out of this store."""
    return store_name(url) in PROTECTED_STORES
