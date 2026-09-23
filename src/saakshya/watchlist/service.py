"""Vehicle-of-Interest watchlist and alert generation.

Two properties matter more here than anywhere else in the system, because this
is where the platform makes a claim that can put a person in front of a police
officer.

**Every match is attributable.** A hit carries the watchlist entry's version,
the authority that created it, and the stated reason. "The system flagged it" is
not an answer an officer can act on or a court can review.

**History is immutable.** Editing a watchlist creates a new version; it never
mutates the old one. An alert raised last Tuesday must remain explicable in
terms of what the watchlist said last Tuesday, not what it says now.

Live government sources (VAHAN, SARATHI, eGujCop, AFIS, NAFIS) are represented
by adapter interfaces only. We hold no credentials and claim no integration; the
PoC runs on representative data, and `source_system` records which is which so
the distinction survives into every alert.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import insert, select, update

from saakshya.common.ids import new_id
from saakshya.store import Store, VehicleObservation, now_us, to_us
from saakshya.store import schema as S

log = logging.getLogger(__name__)


class Category(StrEnum):
    STOLEN_VEHICLE = "stolen_vehicle"
    WANTED_VEHICLE = "wanted_vehicle"
    WANTED_PERSON = "wanted_person"
    MISSING_PERSON = "missing_person"
    INVESTIGATION_TARGET = "investigation_target"
    MISSING_PERSON_ASSOCIATED = "missing_person_associated"
    SUSPECT_VEHICLE = "suspect_vehicle"
    BLACKLISTED_VEHICLE = "blacklisted_vehicle"
    #: A plate read off real footage and listed so the alert path can be shown
    #: working on live data. It says nothing about the vehicle or its owner.
    #: Such entries were filed as "stolen_vehicle", which put a false statement
    #: about a real, identifiable person's car into every alert and export.
    EVALUATION_DESIGNATED = "evaluation_designated"
    CUSTOM = "custom"


class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Status(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


#: How much a category raises alert priority, independent of match confidence.
#: A weak match on a stolen vehicle still deserves a look; a strong match on a
#: low-priority custom list may not.
CATEGORY_WEIGHT = {
    Category.STOLEN_VEHICLE: 1.0,
    Category.WANTED_VEHICLE: 1.0,
    Category.WANTED_PERSON: 1.0,
    Category.MISSING_PERSON: 0.95,
    Category.MISSING_PERSON_ASSOCIATED: 0.95,
    Category.BLACKLISTED_VEHICLE: 0.9,
    Category.SUSPECT_VEHICLE: 0.8,
    Category.INVESTIGATION_TARGET: 0.7,
    Category.EVALUATION_DESIGNATED: 0.7,
    Category.CUSTOM: 0.5,
}


@dataclass
class VehicleOfInterest:
    plate: str
    category: Category
    authority: str
    reason: str
    watchlist_id: str = field(default_factory=lambda: new_id("WL"))
    priority: Priority = Priority.MEDIUM
    jurisdiction: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    version: int = 1
    status: Status = Status.ACTIVE
    source_system: str = "REPRESENTATIVE"
    created_by: str | None = None
    approved_by: str | None = None
    attributes: dict = field(default_factory=dict)

    def active_at(self, when: datetime) -> tuple[bool, str]:
        """Is this entry in force at ``when``? Returns (yes/no, reason)."""
        if self.status is Status.REVOKED:
            return False, "entry revoked"
        if self.status is Status.SUPERSEDED:
            return False, "superseded by a newer version"
        if self.valid_from and when < self.valid_from:
            return False, f"not yet in force (from {self.valid_from.isoformat()})"
        if self.valid_until and when > self.valid_until:
            return False, f"expired {self.valid_until.isoformat()}"
        return True, "active"

    def row(self) -> dict:
        return {
            "watchlist_id": self.watchlist_id, "entity_type": "vehicle",
            "plate": self.plate, "attributes": json.dumps(self.attributes),
            "category": str(self.category), "authority": self.authority,
            "reason": self.reason, "priority": str(self.priority),
            "jurisdiction": self.jurisdiction,
            "valid_from_us": to_us(self.valid_from) if self.valid_from else None,
            "valid_until_us": to_us(self.valid_until) if self.valid_until else None,
            "version": self.version, "status": str(self.status),
            "source_system": self.source_system,
            "created_by": self.created_by, "approved_by": self.approved_by,
            "created_at_us": now_us(), "updated_at_us": now_us(),
        }

    @staticmethod
    def from_row(m) -> VehicleOfInterest:
        d = m._mapping if hasattr(m, "_mapping") else m
        from saakshya.store import from_us
        return VehicleOfInterest(
            watchlist_id=d["watchlist_id"], plate=d["plate"],
            category=Category(d["category"]), authority=d["authority"],
            reason=d["reason"], priority=Priority(d["priority"]),
            jurisdiction=d["jurisdiction"],
            valid_from=from_us(d["valid_from_us"]),
            valid_until=from_us(d["valid_until_us"]),
            version=d["version"], status=Status(d["status"]),
            source_system=d["source_system"], created_by=d["created_by"],
            approved_by=d["approved_by"],
            attributes=json.loads(d["attributes"]) if d["attributes"] else {},
        )


@dataclass
class WatchlistMatch:
    observation: VehicleObservation
    entry: VehicleOfInterest
    confidence: float
    terms: dict[str, float]
    explanation: str


class WatchlistService:
    """CRUD with versioning, plus matching against observations."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # -- lifecycle ---------------------------------------------------------- #
    def add(self, voi: VehicleOfInterest, *, actor: str = "system") -> VehicleOfInterest:
        with self.store.engine.begin() as c:
            c.execute(insert(S.watchlist).values(**voi.row()))
        self.store.audit(actor, "watchlist_add", target=voi.plate,
                         purpose=voi.reason,
                         jurisdiction=voi.jurisdiction, result_count=1)
        return voi

    def amend(self, watchlist_id: str, *, actor: str, **changes) -> VehicleOfInterest:
        """Supersede an entry with a new version.

        The previous row is marked SUPERSEDED and kept. Historical alerts
        reference the version that was in force when they fired, so they stay
        explicable even after the list changes.
        """
        cur = self.get(watchlist_id)
        if cur is None:
            raise KeyError(watchlist_id)
        with self.store.engine.begin() as c:
            c.execute(update(S.watchlist)
                      .where(S.watchlist.c.watchlist_id == watchlist_id)
                      .values(status=str(Status.SUPERSEDED), updated_at_us=now_us()))
        new = VehicleOfInterest(
            plate=changes.get("plate", cur.plate),
            category=changes.get("category", cur.category),
            authority=changes.get("authority", cur.authority),
            reason=changes.get("reason", cur.reason),
            priority=changes.get("priority", cur.priority),
            jurisdiction=changes.get("jurisdiction", cur.jurisdiction),
            valid_from=changes.get("valid_from", cur.valid_from),
            valid_until=changes.get("valid_until", cur.valid_until),
            version=cur.version + 1, status=Status.ACTIVE,
            source_system=cur.source_system, created_by=actor,
            approved_by=changes.get("approved_by"),
            attributes=changes.get("attributes", cur.attributes),
        )
        with self.store.engine.begin() as c:
            c.execute(insert(S.watchlist).values(**new.row()))
        self.store.audit(actor, "watchlist_amend", target=new.plate,
                         purpose=f"v{cur.version} -> v{new.version}")
        return new

    def revoke(self, watchlist_id: str, *, actor: str, reason: str) -> None:
        with self.store.engine.begin() as c:
            c.execute(update(S.watchlist)
                      .where(S.watchlist.c.watchlist_id == watchlist_id)
                      .values(status=str(Status.REVOKED), revoked_by=actor,
                              revoked_reason=reason, updated_at_us=now_us()))
        self.store.audit(actor, "watchlist_revoke", target=watchlist_id,
                         purpose=reason)

    def get(self, watchlist_id: str) -> VehicleOfInterest | None:
        with self.store.engine.connect() as c:
            r = c.execute(select(S.watchlist).where(
                S.watchlist.c.watchlist_id == watchlist_id)).first()
        return VehicleOfInterest.from_row(r) if r else None

    def active_entries(self, plate: str | None = None) -> list[VehicleOfInterest]:
        q = select(S.watchlist).where(S.watchlist.c.status == str(Status.ACTIVE))
        if plate:
            q = q.where(S.watchlist.c.plate == plate)
        with self.store.engine.connect() as c:
            return [VehicleOfInterest.from_row(r) for r in c.execute(q)]

    # -- matching ------------------------------------------------------------ #
    def match(self, obs: VehicleObservation) -> list[WatchlistMatch]:
        """Match one observation. Only plate matches produce a hit.

        Attribute-only matching is deliberately excluded: "a white car" is not a
        vehicle of interest, and generating alerts from it would flood the
        operator with noise and erode trust in every other alert.
        """
        if not obs.plate:
            return []
        out: list[WatchlistMatch] = []
        for e in self.active_entries(obs.plate):
            ok, why = e.active_at(obs.t_norm)
            if not ok:
                log.debug("watchlist %s not in force at %s: %s",
                          e.watchlist_id, obs.t_norm, why)
                continue
            plate_conf = obs.plate_confidence or 0.0
            quality = obs.observation_quality or 0.0
            cat_w = CATEGORY_WEIGHT.get(e.category, 0.5)
            # Confidence is about *this observation*, not about the watchlist.
            conf = 0.65 * plate_conf + 0.35 * quality
            out.append(WatchlistMatch(
                observation=obs, entry=e, confidence=float(conf),
                terms={"plate_confidence": plate_conf,
                       "observation_quality": quality,
                       "category_weight": cat_w},
                explanation=(
                    f"plate {obs.plate} matches {e.category} entry "
                    f"{e.watchlist_id} v{e.version}, authorised by {e.authority} "
                    f"({e.reason}); read from {obs.plate_votes} agreeing frames "
                    f"at observation quality {quality:.2f}"),
            ))
        return out


# --------------------------------------------------------------------------- #
# Edge bundle — for districts that lose the WAN.
# --------------------------------------------------------------------------- #
@dataclass
class WatchlistBundle:
    """A canonical, integrity-checked watchlist snapshot for an edge node.

    Integrity here is a **content hash over a canonical serialisation**, not a
    signature: we have no government PKI and will not pretend otherwise. The
    interface is shaped so that swapping the hash for a real detached signature
    is a one-method change, and the field is named `integrity` rather than
    `signature` so no reader is misled about what it proves.

    A hash detects corruption and accidental modification. It does **not** prove
    origin against a determined adversary — that needs a signing key we do not
    have. Stated in the bundle itself so an operator sees it too.
    """

    bundle_version: str
    created_at: datetime
    issuer: str
    entries: list[dict]
    integrity: str = ""
    integrity_method: str = "sha256-canonical-json"
    integrity_caveat: str = (
        "Content hash only. Detects corruption or accidental modification. "
        "Does NOT authenticate the issuer — that requires a signing key this "
        "deployment does not hold."
    )

    @staticmethod
    def _canonical(entries: list[dict], version: str, issuer: str,
                   created_at: datetime) -> bytes:
        return json.dumps(
            {"bundle_version": version, "issuer": issuer,
             "created_at": created_at.isoformat(),
             "entries": sorted(entries, key=lambda e: e["watchlist_id"])},
            sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def build(cls, entries: list[VehicleOfInterest], *, issuer: str,
              version: str | None = None) -> WatchlistBundle:
        created = datetime.now(UTC)
        rows = [{
            "watchlist_id": e.watchlist_id, "plate": e.plate,
            "category": str(e.category), "priority": str(e.priority),
            "authority": e.authority, "reason": e.reason,
            "version": e.version, "jurisdiction": e.jurisdiction,
            "valid_from": e.valid_from.isoformat() if e.valid_from else None,
            "valid_until": e.valid_until.isoformat() if e.valid_until else None,
        } for e in entries]
        v = version or f"wl-{int(created.timestamp())}"
        payload = cls._canonical(rows, v, issuer, created)
        return cls(bundle_version=v, created_at=created, issuer=issuer,
                   entries=rows,
                   integrity=hashlib.sha256(payload).hexdigest())

    def verify(self) -> tuple[bool, str]:
        """Recompute the hash. An edge node must call this before use."""
        expect = hashlib.sha256(self._canonical(
            self.entries, self.bundle_version, self.issuer, self.created_at)
        ).hexdigest()
        if expect != self.integrity:
            return False, "bundle integrity check FAILED — content does not match hash"
        return True, "integrity verified (content hash; issuer not authenticated)"

    def to_dict(self) -> dict:
        return {
            "bundle_version": self.bundle_version,
            "created_at": self.created_at.isoformat(),
            "issuer": self.issuer,
            "integrity": self.integrity,
            "integrity_method": self.integrity_method,
            "integrity_caveat": self.integrity_caveat,
            "entry_count": len(self.entries),
            "entries": self.entries,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WatchlistBundle:
        return cls(
            bundle_version=d["bundle_version"],
            created_at=datetime.fromisoformat(d["created_at"]),
            issuer=d["issuer"], entries=d["entries"],
            integrity=d.get("integrity", ""),
        )


# --------------------------------------------------------------------------- #
# Government source adapters — interfaces only.
# --------------------------------------------------------------------------- #
class GovernmentSourceAdapter:
    """Interface for an authorised government watchlist source.

    Implementations require credentials and an authorisation route we do not
    have. The class exists so integration is a configuration change rather than
    a redesign, and so nothing in the codebase can accidentally imply a live
    connection: every method raises until a real implementation is supplied.
    """

    name: str = "abstract"
    requires: tuple[str, ...] = ()

    def fetch(self, since: datetime | None = None) -> list[VehicleOfInterest]:
        raise NotImplementedError(
            f"{self.name} is an interface stub. No credentials or authorisation "
            f"route exist for this source. Required before implementation: "
            f"{', '.join(self.requires)}")


class VahanAdapter(GovernmentSourceAdapter):
    name = "VAHAN"
    requires = ("authorised API endpoint", "service credentials",
                "data-sharing approval", "purpose limitation agreement")


class EGujCopAdapter(GovernmentSourceAdapter):
    name = "eGujCop (CCTNS)"
    requires = ("SCRB authorisation", "CCTNS interface specification",
                "network path to the CCTNS environment")


ADAPTERS: dict[str, GovernmentSourceAdapter] = {
    "VAHAN": VahanAdapter(),
    "SARATHI": GovernmentSourceAdapter(),
    "eGujCop": EGujCopAdapter(),
    "AFIS": GovernmentSourceAdapter(),
    "NAFIS": GovernmentSourceAdapter(),
}
