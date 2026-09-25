"""Which stores must never receive live government observations.

Provenance is never mixed: demonstration and evaluation state is kept apart from
live capture, so a measured result can never be quietly improved by a demo run.

The rule matches the **file name**, not a substring of the database URL. The
substring form refused `var/route_demo.db` — a store that is not the demo store
— and a guard that fires on names it does not mean gets worked around, after
which it protects nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

#: Stores that hold demonstration or evaluation state.
PROTECTED_STORES = frozenset({"demo.db", "saakshya.db"})

#: Query keys that carry a secret. libpq takes `password` and `sslpassword`
#: from the query as readily as from the user part, and SQLAlchemy's psycopg
#: dialect passes them through; `pass` also covers `passwd` and `passphrase`.
_SECRET_KEY = re.compile(r"pass|secret|token", re.IGNORECASE)


def redacted(url: str) -> str:
    """A database URL fit for a log line or a report: every secret masked.

    A SQLite URL has no credentials; a PostgreSQL URL carries the password,
    and the API's start-up log and the performance reports printed it.
    hide_password masks only the user part, so `...?password=S3cret`, a URL
    that connects, came back unchanged; secret query keys are masked too.
    """
    try:
        from sqlalchemy import make_url
        u = make_url(url)
        secret = [k for k in u.query if _SECRET_KEY.search(k)]
        if secret:
            u = u.update_query_dict({k: "***" for k in secret})
        return u.render_as_string(hide_password=True).replace("%2A%2A%2A", "***")
    except Exception:
        # Unparseable: keep the scheme and nothing that could be a secret.
        if "@" in url or _SECRET_KEY.search(url.partition("?")[2]):
            return url.split("://", 1)[0] + "://***"
        return url


def store_name(url: str) -> str:
    """The file name a SQLite URL points at; the database name of any other.

    For a PostgreSQL URL the file-name reading returned whatever followed the
    last slash. A URL with no database path, which libpq accepts, ends in
    `user:password@host:port`, and /config served that to every signed-in
    role and the interface painted it on screen. Only the database name is
    read from such a URL now, and the backend's name stands in when the URL
    names none.
    """
    if url.startswith("sqlite") or "://" not in url:
        return Path(url.replace("sqlite:///", "").split("?")[0]).name
    try:
        from sqlalchemy import make_url
        u = make_url(url)
    except Exception:
        return ""
    dbname = u.query.get("dbname")
    if isinstance(dbname, tuple):
        dbname = dbname[-1] if dbname else None
    return u.database or dbname or u.get_backend_name()


def refuses_live_writes(url: str) -> bool:
    """Whether live observations must be kept out of this store."""
    return store_name(url) in PROTECTED_STORES
