"""Grid credentials, injected at connection time and never anywhere else.

The Sentinel grid authenticates every RTSP and WHEP connection with an email and
access password embedded in the URL authority — `rtsp://email:password@host/…`.
That is the grid's design, not ours, and it creates an obvious hazard: a URL
that carries a credential will end up wherever URLs end up, which is logs,
exception messages, database rows, exports and screenshots.

So the registry stores the **clean** URL and this module adds the authority in
the moment before the socket opens. A credential in a database is a credential
in every backup of it, every export from it, and every screenshot of a table
showing it.

Two functions, and they are meant to be used together:

    open_url = credentialed(cam["rtsp_url"])   # what you connect with
    log.info("opening %s", redact(open_url))   # what you are allowed to say

`redact` is applied at every exit from this package. A redaction applied at one
exit and not another is the same as no redaction at all.

Configuration, environment only:

    SENTINEL_GRID_EMAIL      the registered email on the approved access list
    SENTINEL_GRID_PASSWORD   the access password, in XXXX-XXXX-XXXX form

Neither is read from a file, written to one, or accepted from a request.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote

#: Anything that looks like a credential in an authority, however it got there.
_AUTHORITY = re.compile(r"(?<=//)[^/@\s]*:[^/@\s]*@")

#: Schemes whose authority the grid authenticates. HLS is served by the CDN
#: behind a session cookie instead, so it is deliberately absent: putting a
#: password in an https URL would send it to a host that does not want it.
_SCHEMES = ("rtsp://", "rtsps://", "http://", "https://")


class MissingCredential(RuntimeError):
    """Raised when a credentialed connection is attempted without one."""


def configured() -> bool:
    """Whether both halves of the grid credential are present."""
    return bool(os.environ.get("SENTINEL_GRID_EMAIL")
                and os.environ.get("SENTINEL_GRID_PASSWORD"))


def needs_grid_credential(url: str) -> bool:
    """Whether this URL is on a grid that authenticates the authority.

    Loopback MediaMTX (the synthetic demonstration) does not. The government
    Sentinel grid does. Against the latter, a missing credential is a 401
    twelve seconds later — unless the caller refuses now.
    """
    if not url or not url.startswith(("rtsp://", "rtsps://")):
        return False
    if _AUTHORITY.search(url):
        return False
    rest = url.split("://", 1)[-1]
    hostport = rest.split("/")[0]
    host = (hostport.split("]")[0].lstrip("[") if hostport.startswith("[")
            else hostport.split(":")[0])
    return host not in {"127.0.0.1", "localhost", "::1"}


def redact(url: str) -> str:
    """A URL safe to log, print, store or show. Always applied at the boundary."""
    return _AUTHORITY.sub("<redacted>@", url or "")


def credentialed(url: str, *, required: bool = False) -> str:
    """The same URL with grid credentials in its authority.

    Returns the URL unchanged when no credential is configured, so a deployment
    against an unauthenticated grid needs no special case. Pass `required=True`
    where a missing credential should be an error rather than a 401 twenty
    seconds later.

    A URL that already carries an authority is left alone: an explicit
    credential in the registry — which we do not put there, but a deployment
    might — is not silently overwritten with a different one.
    """
    if not url or not url.startswith(_SCHEMES):
        return url
    if _AUTHORITY.search(url):
        return url

    email = os.environ.get("SENTINEL_GRID_EMAIL", "")
    password = os.environ.get("SENTINEL_GRID_PASSWORD", "")
    if not (email and password):
        if required:
            raise MissingCredential(
                "This grid authenticates every stream connection, and no "
                "credential is configured. Set SENTINEL_GRID_EMAIL and "
                "SENTINEL_GRID_PASSWORD in the environment. They must not be "
                "written into any file in this repository.")
        return url

    scheme, _, rest = url.partition("//")
    # `safe=""` matters: the email's @ must become %40 or the authority splits
    # at the wrong place and the grid reads a truncated username.
    return f"{scheme}//{quote(email, safe='')}:{quote(password, safe='')}@{rest}"
