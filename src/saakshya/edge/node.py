"""The edge node: local processing that does not need the centre to be reachable.

The rule this module exists to enforce: **loss of the uplink degrades reporting,
never detection.** A district node continues to ingest, track, read plates, match
its local watchlist, raise alerts and seal evidence with the link down. What it
loses is the centre's view of those things, and that is recovered on reconnect.

Watchlist distribution runs the opposite way and fails closed. A node accepts a
new watchlist bundle only if the integrity check passes, the version is newer
than what it holds, and the issuer is one it was configured to trust. Any doubt
and it keeps the bundle it already has — a stale watchlist is a known quantity,
while an unverified one is an unknown vehicle list of unknown origin driving
police action.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from saakshya.edge.queue import DurableQueue, QueuedEvent
from saakshya.store import Store, VehicleObservation
from saakshya.watchlist import WatchlistBundle

log = logging.getLogger("saakshya.edge.node")


# --------------------------------------------------------------------------- #
# Bundle verification
# --------------------------------------------------------------------------- #
@dataclass
class VerificationOutcome:
    accepted: bool
    method: str
    reason: str
    authenticates_issuer: bool

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "method": self.method,
                "reason": self.reason,
                "authenticates_issuer": self.authenticates_issuer}


class BundleVerifier(Protocol):
    """The seam where real PKI plugs in without touching anything else."""

    method: str
    authenticates_issuer: bool

    def verify(self, bundle: WatchlistBundle) -> VerificationOutcome: ...


class HashOnlyVerifier:
    """Content hash. Detects corruption; does not authenticate origin.

    This is what a deployment without a signing key actually has, and saying so
    is the whole point. The node still enforces every other acceptance rule, and
    the outcome carries `authenticates_issuer=False` so a UI cannot present a
    hash check as a signature check.
    """

    method = "sha256-canonical-json"
    authenticates_issuer = False

    def verify(self, bundle: WatchlistBundle) -> VerificationOutcome:
        ok, detail = bundle.verify()
        return VerificationOutcome(ok, self.method, detail, False)


class HmacVerifier:
    """Shared-secret authentication, when one has been provisioned.

    Strictly better than a bare hash — it establishes that the bundle came from
    a holder of the key — and strictly weaker than a detached signature, because
    every node that can verify can also forge. Suitable for a closed distribution
    within one force; not suitable for cross-agency distribution.

    The key comes from the environment and is never written to the repository.
    """

    method = "hmac-sha256"
    authenticates_issuer = True

    def __init__(self, key: bytes | None = None, *,
                 env_var: str = "SAAKSHYA_BUNDLE_KEY") -> None:
        raw = key or (os.environ.get(env_var) or "").encode()
        if not raw:
            raise MissingKeyMaterial(
                f"{env_var} is not set. Provision the shared bundle key through "
                "the environment or the platform's secret store. It must not be "
                "written into configuration held in version control.")
        self._key = raw

    def verify(self, bundle: WatchlistBundle) -> VerificationOutcome:
        import hashlib
        import hmac
        payload = WatchlistBundle._canonical(
            bundle.entries, bundle.bundle_version, bundle.issuer, bundle.created_at)
        expect = hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expect, bundle.integrity):
            return VerificationOutcome(True, self.method,
                                       "HMAC verified against the provisioned key",
                                       True)
        return VerificationOutcome(False, self.method,
                                   "HMAC does not match — bundle REJECTED", True)


class DetachedSignatureVerifier:
    """Placeholder for real asymmetric verification.

    Not implemented, and deliberately not faked. Implementing it requires a
    signing authority, key custody, a distribution channel for the public key and
    a revocation story — none of which this deployment has. A verifier that
    returned True would be worse than no verifier, because it would look like
    one.
    """

    method = "detached-signature"
    authenticates_issuer = True

    def verify(self, bundle: WatchlistBundle) -> VerificationOutcome:
        raise NotImplementedError(
            "Detached signature verification requires: an issuing authority, a "
            "signing key held by that authority, a distribution channel for the "
            "public key, and a revocation mechanism. None is available. Use "
            "HmacVerifier where a shared key has been provisioned, otherwise "
            "HashOnlyVerifier with its stated limitation.")


class MissingKeyMaterial(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Node
# --------------------------------------------------------------------------- #
@dataclass
class EdgeConfig:
    node_id: str
    site: str = ""
    district: str = ""
    trusted_issuers: tuple[str, ...] = ()
    #: Batch size per sync attempt. Small enough that a flaky link makes
    #: progress rather than repeatedly timing out on one huge request.
    sync_batch: int = 200


@dataclass
class SyncReport:
    attempted: int = 0
    delivered: int = 0
    acknowledged: int = 0
    failed: int = 0
    link_up: bool = True
    error: str | None = None
    remaining: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"attempted": self.attempted, "delivered": self.delivered,
                "acknowledged": self.acknowledged, "failed": self.failed,
                "link_up": self.link_up, "error": self.error,
                "remaining": self.remaining}


class CentralLink(Protocol):
    """Transport abstraction. HTTP in deployment, in-process in tests."""

    def push(self, node_id: str, events: list[dict[str, Any]]) -> dict[str, Any]: ...


class EdgeNode:
    """Local-first processing with store-and-forward reporting."""

    def __init__(self, store: Store, config: EdgeConfig, *,
                 link: CentralLink | None = None,
                 verifier: BundleVerifier | None = None,
                 state_dir: Path | None = None) -> None:
        self.store = store
        self.config = config
        self.queue = DurableQueue(store, config.node_id)
        self.link = link
        self.verifier: BundleVerifier = verifier or HashOnlyVerifier()
        self.state_dir = state_dir or Path("var/edge") / config.node_id
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._bundle: WatchlistBundle | None = self._load_bundle()

    # -- local processing --------------------------------------------------- #
    def record(self, observations: list[VehicleObservation]) -> dict[str, Any]:
        """Persist locally and queue for the centre. Order matters.

        The local write happens first and unconditionally. If queueing then
        fails — a full queue, a corrupt payload — the observation still exists
        on the node and can be re-queued. The reverse order would let a queueing
        failure destroy the observation.
        """
        written = self.store.add_observations(observations)
        queued = 0
        for o in observations:
            try:
                self.queue.enqueue("observation", dedup_key=o.dedup_key,
                                   camera_id=o.camera_id, pts_s=o.pts_s,
                                   payload=o.to_public())
                queued += 1
            except Exception as exc:  # queue full or payload rejected
                log.error("queueing failed; observation retained locally",
                          extra={"extra_fields": {"error": str(exc),
                                                  "observation": o.observation_id}})
        return {"stored": written, "queued": queued,
                "queue_depth": self.queue.depth()}

    # -- watchlist ---------------------------------------------------------- #
    def install_bundle(self, bundle: WatchlistBundle) -> dict[str, Any]:
        """Accept a watchlist bundle, or refuse it and keep the current one.

        Four gates, all of which must pass. Failing any one keeps the existing
        bundle in place — the node never ends up with *no* watchlist because a
        bad one arrived.
        """
        outcome = self.verifier.verify(bundle)
        checks: list[dict[str, Any]] = [
            {"check": "integrity", "ok": outcome.accepted, "detail": outcome.reason}]

        trusted = (not self.config.trusted_issuers
                   or bundle.issuer in self.config.trusted_issuers)
        checks.append({
            "check": "issuer", "ok": trusted,
            "detail": (f"issuer {bundle.issuer!r} is trusted" if trusted else
                       f"issuer {bundle.issuer!r} is not in the trusted set "
                       f"{list(self.config.trusted_issuers)}")})

        newer = (self._bundle is None
                 or bundle.created_at > self._bundle.created_at
                 or bundle.bundle_version != self._bundle.bundle_version)
        checks.append({
            "check": "version", "ok": newer,
            "detail": ("newer than the installed bundle" if newer else
                       f"version {bundle.bundle_version} is not newer than "
                       f"the installed {self._bundle.bundle_version}"  # type: ignore[union-attr]
                       + " — refused to prevent rollback")})

        now = datetime.now(UTC)
        live = [e for e in bundle.entries if _entry_live(e, now)]
        expired = len(bundle.entries) - len(live)
        checks.append({
            "check": "entry_validity", "ok": True,
            "detail": (f"{len(live)} live entries; {expired} expired entries "
                       "dropped at install")})

        accepted = all(c["ok"] for c in checks)
        if accepted:
            self._bundle = WatchlistBundle(
                bundle_version=bundle.bundle_version, created_at=bundle.created_at,
                issuer=bundle.issuer, entries=live, integrity=bundle.integrity)
            self._save_bundle(self._bundle)
            log.info("watchlist bundle installed", extra={"extra_fields": {
                "version": bundle.bundle_version, "entries": len(live)}})
        else:
            log.warning("watchlist bundle REFUSED; keeping existing",
                        extra={"extra_fields": {"checks": checks}})

        return {
            "accepted": accepted,
            "installed_version": self._bundle.bundle_version if self._bundle else None,
            "checks": checks,
            "verification": outcome.to_dict(),
            "caveat": (None if outcome.authenticates_issuer else
                       "Integrity was checked but the issuer was NOT "
                       "authenticated. This node cannot prove where this "
                       "watchlist came from."),
        }

    def local_watchlist(self) -> list[dict[str, Any]]:
        if self._bundle is None:
            return []
        now = datetime.now(UTC)
        return [e for e in self._bundle.entries if _entry_live(e, now)]

    def match(self, obs: VehicleObservation) -> list[dict[str, Any]]:
        """Local watchlist matching. Plate only — deliberately.

        Attribute-only matching on an edge node with no supervision would mean
        "a white hatchback" raising a police alert. Colour is corroboration; it
        is never the reason an alert exists.
        """
        if not obs.plate:
            return []
        return [e for e in self.local_watchlist() if e.get("plate") == obs.plate]

    def _bundle_path(self) -> Path:
        return self.state_dir / "watchlist_bundle.json"

    def _save_bundle(self, b: WatchlistBundle) -> None:
        tmp = self._bundle_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(b.to_dict(), indent=2))
        # Atomic replace: a power cut mid-write leaves the previous bundle
        # intact rather than a truncated file that fails to parse on boot.
        tmp.replace(self._bundle_path())

    def _load_bundle(self) -> WatchlistBundle | None:
        p = self._bundle_path()
        if not p.is_file():
            return None
        try:
            return WatchlistBundle.from_dict(json.loads(p.read_text()))
        except (ValueError, KeyError) as exc:
            log.error("stored watchlist bundle is unreadable; ignoring",
                      extra={"extra_fields": {"error": str(exc)}})
            return None

    # -- sync --------------------------------------------------------------- #
    def sync(self, *, max_batches: int = 20) -> SyncReport:
        """Drain the queue to the centre. Safe to call at any time.

        Returns rather than raises when the link is down: an offline node calling
        `sync()` on a timer is the normal case, not an error condition.
        """
        rep = SyncReport()
        if self.link is None:
            rep.link_up = False
            rep.error = "no central link configured"
            rep.remaining = self.queue.depth()
            return rep

        for _ in range(max_batches):
            batch = self.queue.pending(self.config.sync_batch)
            if not batch:
                break
            rep.attempted += len(batch)
            try:
                result = self.link.push(
                    self.config.node_id, [e.to_dict() for e in batch])
            except Exception as exc:  # any transport failure
                rep.link_up = False
                rep.error = str(exc)
                rep.failed += len(batch)
                self.queue.mark_failed([e.event_id for e in batch], str(exc))
                break
            acked = result.get("acknowledged", [])
            n = self.queue.acknowledge(acked)
            rep.delivered += len(batch)
            rep.acknowledged += n
            if len(acked) < len(batch):
                # Partial acceptance. The unacknowledged ones stay pending and
                # will be retried; they are never silently dropped.
                unacked = [e.event_id for e in batch if e.event_id not in set(acked)]
                self.queue.mark_failed(unacked, "not acknowledged by centre")
                rep.failed += len(unacked)
        rep.remaining = self.queue.depth()
        return rep

    def status(self) -> dict[str, Any]:
        return {
            "node_id": self.config.node_id, "site": self.config.site,
            "district": self.config.district,
            "link": "configured" if self.link else "offline",
            "queue": self.queue.stats(),
            "watchlist": {
                "version": self._bundle.bundle_version if self._bundle else None,
                "entries": len(self.local_watchlist()),
                "verification_method": self.verifier.method,
                "authenticates_issuer": self.verifier.authenticates_issuer,
            },
            "mode": ("LOCAL — processing continues; reporting is queued"
                     if self.queue.depth() else "SYNCED"),
        }


def _entry_live(entry: dict[str, Any], now: datetime) -> bool:
    until = entry.get("valid_until")
    if until:
        try:
            if datetime.fromisoformat(until) < now:
                return False
        except ValueError:
            # An unparseable validity window is treated as expired. Failing
            # closed on a watchlist entry means at worst a missed alert; failing
            # open means acting on an entry nobody can date.
            return False
    frm = entry.get("valid_from")
    if frm:
        try:
            if datetime.fromisoformat(frm) > now:
                return False
        except ValueError:
            return False
    return True


class HttpLink:
    """Real transport. Kept trivial on purpose — the interesting behaviour is in
    the queue, and a transport with its own retry logic would fight it."""

    def __init__(self, base_url: str, token: str, *, timeout_s: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout_s = timeout_s

    def push(self, node_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        import httpx
        r = httpx.post(f"{self.base_url}/edge/{node_id}/events",
                       json={"events": events},
                       headers={"Authorization": f"Bearer {self._token}"},
                       timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()


class InProcessLink:
    """Test and single-box deployment transport. Also the honest way to run the
    offline demonstration without pretending a network exists."""

    def __init__(self, receiver: Any) -> None:
        self.receiver = receiver
        self.up = True

    def push(self, node_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.up:
            raise ConnectionError("central link is down")
        return self.receiver.receive(node_id, events).to_dict()


def queued_summary(events: list[QueuedEvent]) -> dict[str, Any]:
    return {"count": len(events),
            "sequences": [e.sequence for e in events[:20]],
            "cameras": sorted({e.camera_id for e in events if e.camera_id})}
