"""Authentication, authorisation, scope and purpose binding.

Four independent gates, and a request must pass all four:

1. **Authentication** — who is calling. A bearer token, hashed at rest.
2. **Authorisation** — does that role hold the permission at all.
3. **Scope** — is the requested district inside the caller's jurisdiction.
4. **Purpose** — is the request attached to a case and a stated reason.

The fourth is the one that is usually missing from systems like this, and it is
the one that matters most here. A vehicle-movement history is intrusive whether
or not the person requesting it holds a valid login; "authenticated" is not
"entitled". Purpose binding makes the reason for every intrusive query a
mandatory, audited field rather than an institutional convention, which is what
turns the audit log into something an oversight body can actually use.

Deliberate non-goals: this is not an IAM product. There is no federation, no
group hierarchy, no delegation chain, no self-service. A real deployment would
authenticate against the department's existing directory; `Principal` is the
seam where that plugs in, and everything above this module depends only on
`Principal`, never on how it was obtained.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import insert, select, update

from saakshya.store import schema as S
from saakshya.store.repository import Store, now_us, to_us


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #
class AccessError(Exception):
    """Base for every access failure. Carries an HTTP status and a code so the
    API layer never has to guess, and so the *reason* reaches the caller — a
    refusal that does not say which gate closed is unusable in the field."""

    status = 403
    code = "FORBIDDEN"


class NotAuthenticated(AccessError):
    status = 401
    code = "NOT_AUTHENTICATED"


class PermissionDenied(AccessError):
    status = 403
    code = "PERMISSION_DENIED"


class OutOfScope(AccessError):
    status = 403
    code = "OUT_OF_JURISDICTION"


class PurposeRequired(AccessError):
    """Deliberately 400, not 403. The caller is entitled to make this request;
    they have not yet said why. That is a malformed request, not a refusal."""

    status = 400
    code = "PURPOSE_REQUIRED"


# --------------------------------------------------------------------------- #
# Roles and permissions
# --------------------------------------------------------------------------- #
class Role(StrEnum):
    ADMIN = "ADMIN"                 # registry, users, policy
    SUPERVISOR = "SUPERVISOR"       # statewide investigation + watchlist authority
    INVESTIGATOR = "INVESTIGATOR"   # district-scoped investigation
    OPERATOR = "OPERATOR"           # control room: alerts and health, no search
    AUDITOR = "AUDITOR"             # reads the audit log, and camera identity
    SERVICE = "SERVICE"             # edge node sync; machine-to-machine


class Permission(StrEnum):
    CAMERA_READ = "camera:read"
    HEALTH_READ = "health:read"
    CAPABILITY_READ = "capability:read"
    SEARCH_PLATE = "search:plate"
    SEARCH_APPEARANCE = "search:appearance"
    TRAJECTORY_BUILD = "trajectory:build"
    WATCHLIST_READ = "watchlist:read"
    WATCHLIST_WRITE = "watchlist:write"
    ALERT_READ = "alert:read"
    ALERT_ACK = "alert:ack"
    EVIDENCE_READ = "evidence:read"
    EVIDENCE_CREATE = "evidence:create"
    EVIDENCE_EXPORT = "evidence:export"
    CASE_READ = "case:read"
    CASE_WRITE = "case:write"
    AUDIT_READ = "audit:read"
    ADMIN_WRITE = "admin:write"
    EDGE_SYNC = "edge:sync"


#: Purpose-bound permissions. Exercising one of these without a case id and a
#: stated purpose is rejected before any data is read.
#:
#: Watchlist *reads* are on this list on purpose: "is this vehicle of interest"
#: discloses the existence of an investigation, and that disclosure is itself
#: sensitive. Camera and health reads are not — an operator needs to know which
#: cameras are down without opening a case to ask.
PURPOSE_BOUND: frozenset[Permission] = frozenset({
    Permission.SEARCH_PLATE,
    Permission.SEARCH_APPEARANCE,
    Permission.TRAJECTORY_BUILD,
    Permission.WATCHLIST_READ,
    Permission.WATCHLIST_WRITE,
    Permission.EVIDENCE_CREATE,
    Permission.EVIDENCE_EXPORT,
})

_INVESTIGATION = {
    Permission.CAMERA_READ, Permission.HEALTH_READ, Permission.CAPABILITY_READ,
    Permission.SEARCH_PLATE, Permission.SEARCH_APPEARANCE,
    Permission.TRAJECTORY_BUILD, Permission.WATCHLIST_READ,
    Permission.ALERT_READ, Permission.ALERT_ACK,
    Permission.EVIDENCE_READ, Permission.EVIDENCE_CREATE, Permission.EVIDENCE_EXPORT,
    Permission.CASE_READ, Permission.CASE_WRITE,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset({
        Permission.CAMERA_READ, Permission.HEALTH_READ, Permission.CAPABILITY_READ,
        Permission.ADMIN_WRITE, Permission.AUDIT_READ, Permission.CASE_READ,
    }),
    Role.SUPERVISOR: frozenset(_INVESTIGATION | {
        Permission.WATCHLIST_WRITE, Permission.AUDIT_READ,
    }),
    Role.INVESTIGATOR: frozenset(_INVESTIGATION),
    Role.OPERATOR: frozenset({
        Permission.CAMERA_READ, Permission.HEALTH_READ, Permission.CAPABILITY_READ,
        Permission.ALERT_READ, Permission.ALERT_ACK, Permission.CASE_READ,
    }),
    Role.AUDITOR: frozenset({Permission.AUDIT_READ, Permission.CAMERA_READ}),
    Role.SERVICE: frozenset({
        Permission.EDGE_SYNC, Permission.CAMERA_READ, Permission.WATCHLIST_READ,
    }),
}

#: An ADMIN administers the estate; they do not get to read vehicle movement.
#: Splitting "runs the system" from "investigates people" is the single most
#: valuable separation of duty available here, so it is enforced rather than
#: documented: the mapping above gives ADMIN no search permission at all.
assert Permission.SEARCH_PLATE not in ROLE_PERMISSIONS[Role.ADMIN]

#: An AUDITOR holds CAMERA_READ deliberately, and it is worth being precise
#: about why, because "the auditor reads only the audit log" is the intuitive
#: reading and it is wrong. An audit entry records that a named user searched
#: cam21 for a purpose; without camera identity that entry is a row of opaque
#: identifiers and cannot be reviewed. So the auditor may resolve WHAT a camera
#: is — its name, district and health — and may not read WHO or WHAT was seen
#: by it. The line is drawn at observations, evidence and search, and the three
#: assertions below pin it so the grant cannot widen without a test failing.
assert Permission.CAMERA_READ in ROLE_PERMISSIONS[Role.AUDITOR]
assert Permission.EVIDENCE_READ not in ROLE_PERMISSIONS[Role.AUDITOR]
assert Permission.SEARCH_PLATE not in ROLE_PERMISSIONS[Role.AUDITOR]
assert Permission.TRAJECTORY_BUILD not in ROLE_PERMISSIONS[Role.AUDITOR]


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Principal:
    """An authenticated caller. Immutable for the life of a request."""

    user_id: str
    role: Role
    display_name: str = ""
    department: str | None = None
    #: Empty means statewide. Only SUPERVISOR, ADMIN, AUDITOR and SERVICE may
    #: hold statewide scope; `TokenService` refuses to mint anything else.
    districts: tuple[str, ...] = ()
    badge_no: str | None = None
    token_id: str | None = None

    @property
    def statewide(self) -> bool:
        return not self.districts

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS.get(self.role, frozenset())

    def may(self, perm: Permission) -> bool:
        return perm in self.permissions

    def require(self, perm: Permission) -> None:
        if not self.may(perm):
            raise PermissionDenied(
                f"role {self.role} does not hold {perm}; "
                f"held: {sorted(str(p) for p in self.permissions)}")

    def in_scope(self, district: str | None) -> bool:
        if self.statewide:
            return True
        if district is None:
            # An unlocated record cannot be shown to be inside a limited
            # jurisdiction, so it is treated as outside it. Failing closed on
            # missing data is the only safe direction for an access decision.
            return False
        return district in self.districts

    def require_scope(self, district: str | None) -> None:
        if not self.in_scope(district):
            raise OutOfScope(
                f"{self.user_id} is scoped to {list(self.districts)}; "
                f"{district!r} is outside it")

    def scope_filter(self) -> tuple[str, ...] | None:
        """Districts to constrain a query to, or None for statewide."""
        return None if self.statewide else self.districts

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id, "display_name": self.display_name,
            "role": str(self.role), "department": self.department,
            "districts": list(self.districts), "badge_no": self.badge_no,
            "statewide": self.statewide,
            "permissions": sorted(str(p) for p in self.permissions),
        }


@dataclass
class AuthContext:
    """Principal plus the purpose binding for one request."""

    principal: Principal
    case_id: str | None = None
    purpose: str | None = None
    request_id: str | None = None
    #: Filled by `authorise` so the audit record states which gate was applied.
    checked: list[str] = field(default_factory=list)

    MIN_PURPOSE_CHARS = 12

    def authorise(self, perm: Permission, *, district: str | None = None) -> None:
        """The single choke point. Every sensitive operation goes through here."""
        self.principal.require(perm)
        self.checked.append(str(perm))
        if district is not None:
            self.principal.require_scope(district)
        if perm in PURPOSE_BOUND:
            if not self.case_id:
                raise PurposeRequired(
                    f"{perm} is purpose-bound: supply a case id (X-Case-Id). "
                    "Open a case first if one does not exist.")
            if not self.purpose or len(self.purpose.strip()) < self.MIN_PURPOSE_CHARS:
                raise PurposeRequired(
                    f"{perm} is purpose-bound: supply a stated purpose "
                    f"(X-Purpose) of at least {self.MIN_PURPOSE_CHARS} characters. "
                    "It is recorded in the audit log.")

    def audit(self, store: Store, action: str, *, target: str | None = None,
              result_count: int | None = None) -> None:
        store.audit(
            actor=self.principal.user_id, action=action, role=str(self.principal.role),
            case_id=self.case_id, purpose=self.purpose, target=target,
            result_count=result_count,
            jurisdiction=("STATE" if self.principal.statewide
                          else ",".join(self.principal.districts)))


#: Used by tools, tests and the offline edge node, where there is no HTTP request
#: to authenticate. It is a *named* system identity rather than an absent one, so
#: machine-originated audit entries are still attributable.
SYSTEM = Principal(user_id="system", role=Role.SERVICE, display_name="system")


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
_STATEWIDE_ROLES = {Role.ADMIN, Role.SUPERVISOR, Role.AUDITOR, Role.SERVICE}


def _hash_token(token: str) -> str:
    """SHA-256 with no salt or stretching — correct *here* and nowhere near a
    password. The token is 256 bits from `secrets`, so there is no dictionary to
    attack and no work factor worth paying. Stretching a high-entropy secret
    buys nothing and costs latency on every request."""
    return hashlib.sha256(token.encode()).hexdigest()


class TokenService:
    """Mints and verifies bearer tokens. The plaintext exists exactly once."""

    TOKEN_PREFIX = "skv_"

    def __init__(self, store: Store) -> None:
        self.store = store

    # -- users ------------------------------------------------------------- #
    def upsert_user(self, user_id: str, role: Role, *, display_name: str = "",
                    department: str | None = None,
                    districts: tuple[str, ...] = (),
                    badge_no: str | None = None) -> Principal:
        if districts and role in (Role.ADMIN, Role.AUDITOR):
            # Not a hard error: an admin restricted to one district is a
            # perfectly sensible deployment. Recorded as given.
            pass
        if not districts and role not in _STATEWIDE_ROLES:
            raise ValueError(
                f"role {role} may not hold statewide scope; name its districts")
        row = {
            "user_id": user_id, "display_name": display_name or user_id,
            "role": str(role), "department": department,
            "districts": json.dumps(list(districts)), "badge_no": badge_no,
            "enabled": True, "updated_at_us": now_us(),
        }
        with self.store.engine.begin() as c:
            exists = c.execute(select(S.users.c.user_id).where(
                S.users.c.user_id == user_id)).first()
            if exists:
                c.execute(update(S.users).where(S.users.c.user_id == user_id).values(**row))
            else:
                row["created_at_us"] = now_us()
                c.execute(insert(S.users).values(**row))
        return Principal(user_id=user_id, role=role,
                         display_name=str(row["display_name"]),
                         department=department, districts=tuple(districts),
                         badge_no=badge_no)

    def disable_user(self, user_id: str) -> None:
        with self.store.engine.begin() as c:
            c.execute(update(S.users).where(S.users.c.user_id == user_id)
                      .values(enabled=False, updated_at_us=now_us()))

    def list_users(self) -> list[dict[str, Any]]:
        with self.store.engine.connect() as c:
            out = []
            for r in c.execute(select(S.users).order_by(S.users.c.user_id)):
                d = dict(r._mapping)
                d["districts"] = json.loads(d["districts"] or "[]")
                out.append(d)
            return out

    # -- tokens ------------------------------------------------------------ #
    def mint(self, user_id: str, *, label: str = "",
             ttl: timedelta | None = timedelta(days=7)) -> str:
        """Return the plaintext token. It is never stored and never recoverable."""
        with self.store.engine.connect() as c:
            u = c.execute(select(S.users).where(S.users.c.user_id == user_id)).first()
        if not u:
            raise ValueError(f"no such user: {user_id}")
        token = self.TOKEN_PREFIX + secrets.token_urlsafe(32)
        expires = to_us(datetime.now(UTC) + ttl) if ttl else None
        with self.store.engine.begin() as c:
            c.execute(insert(S.api_tokens).values(
                token_id="TK-" + secrets.token_hex(8), user_id=user_id,
                token_sha256=_hash_token(token), label=label,
                issued_at_us=now_us(), expires_at_us=expires, revoked=False))
        self.store.audit(actor="admin", action="token_mint", target=user_id)
        return token

    def revoke(self, token_id: str) -> None:
        with self.store.engine.begin() as c:
            c.execute(update(S.api_tokens)
                      .where(S.api_tokens.c.token_id == token_id).values(revoked=True))

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise NotAuthenticated("no bearer token supplied")
        digest = _hash_token(token)
        with self.store.engine.connect() as c:
            row = c.execute(
                select(S.api_tokens, S.users)
                .select_from(S.api_tokens.join(
                    S.users, S.api_tokens.c.user_id == S.users.c.user_id))
                .where(S.api_tokens.c.token_sha256 == digest)).first()
        if not row:
            # The lookup is by hash, so this branch already ran in constant time
            # with respect to the token value; the compare below is belt and
            # braces for any future non-indexed path.
            raise NotAuthenticated("token not recognised")
        m = row._mapping
        if not hmac.compare_digest(m["token_sha256"], digest):
            raise NotAuthenticated("token not recognised")
        if m["revoked"]:
            raise NotAuthenticated("token revoked")
        if m["expires_at_us"] and m["expires_at_us"] < now_us():
            raise NotAuthenticated("token expired")
        if not m["enabled"]:
            raise NotAuthenticated(f"user {m['user_id']} is disabled")
        with self.store.engine.begin() as c:
            c.execute(update(S.api_tokens)
                      .where(S.api_tokens.c.token_id == m["token_id"])
                      .values(last_used_at_us=now_us()))
        return Principal(
            user_id=m["user_id"], role=Role(m["role"]),
            display_name=m["display_name"] or m["user_id"],
            department=m["department"],
            districts=tuple(json.loads(m["districts"] or "[]")),
            badge_no=m["badge_no"], token_id=m["token_id"])
