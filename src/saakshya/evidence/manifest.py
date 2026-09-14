"""Evidence manifests, integrity verification, and s.63 certificate preparation.

What this layer does and does not claim
---------------------------------------
It **prepares** an evidence record: the frame, the clip, their hashes, the models
and pipeline that produced them, the source quality, and a hash-chained audit
entry. It generates a Section 63 certificate **draft** with the fields the
statute requires, leaving both signature blocks empty.

It does **not** make evidence admissible. Admissibility is a determination for a
court, and Section 63 of the Bharatiya Sakshya Adhiniyam requires signatures
from the person in charge of the device and from an expert — two humans this
system is not entitled to impersonate. Nothing in this module, its output, or
the UI may say "legally admissible".

Integrity model
---------------
Content hashes (SHA-256) over the frame, the clip and a canonical serialisation
of the manifest, chained to the previous evidence entry. That detects tampering
and truncation. It does not authenticate origin against an adversary who can
rewrite the whole chain — that needs a signing key and a trusted timestamp
authority, neither of which this deployment holds. Stated in the record itself
so a reader is not misled.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import insert, select, update

from saakshya.common.ids import evidence_id
from saakshya.store import Store, VehicleObservation, now_us, to_us
from saakshya.store import schema as S

log = logging.getLogger(__name__)

CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class BsaS63Certificate:
    """Draft certificate under s.63, Bharatiya Sakshya Adhiniyam 2023.

    In force since 1 July 2024, replacing s.65B of the Indian Evidence Act. The
    statute requires the certificate to identify the record, describe how it was
    produced, give particulars of the devices involved, state the hash value, and
    be signed by the person in charge of the device **and** an expert.

    We populate everything a machine can know and leave the two signature blocks
    empty. Status stays DRAFT_PENDING_SIGNATURE until authorised humans sign.
    """

    evidence_id: str
    record_identifier: str
    record_description: str
    production_method: str
    device_particulars: dict
    hash_algorithm: str = "SHA-256"
    hash_value: str = ""
    period_of_operation: str = ""
    status: str = "DRAFT_PENDING_SIGNATURE"
    #: Deliberately None. Populating these from software would be impersonation.
    signature_person_in_charge: None = None
    signature_expert: None = None
    statutory_note: str = (
        "Prepared under s.63, Bharatiya Sakshya Adhiniyam 2023. This is a DRAFT. "
        "It requires signature by the person in charge of the device and by an "
        "expert before it has any evidential effect. This system does not and "
        "cannot certify admissibility; that is a determination for the court."
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceManifest:
    evidence_id: str
    observation_id: str
    camera_id: str
    pts_s: float
    t_norm: datetime

    frame_path: str | None = None
    frame_sha256: str | None = None
    clip_path: str | None = None
    clip_sha256: str | None = None

    pipeline_version: str = ""
    model_versions: dict = field(default_factory=dict)
    capture_method: str = ""
    device: str = ""
    source_quality: float | None = None
    confidence_decomposition: dict = field(default_factory=dict)

    prev_hash: str | None = None
    entry_hash: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    integrity_caveat: str = (
        "SHA-256 content hashes chained to the previous evidence record. "
        "Detects modification and truncation. Does NOT authenticate origin "
        "against an adversary able to rewrite the chain, which would require a "
        "signing key and trusted timestamping this deployment does not hold."
    )

    #: Fixed precision for every float in the canonical form. Without this the
    #: hash depends on Python's numeric *type*, not on the value: pts_s=10
    #: serialises as `10` at creation and as `10.0` after a round-trip through a
    #: Float column, so an untampered record failed its own verification. A
    #: hash that depends on representation rather than content is not an
    #: integrity check.
    _FLOAT_PLACES = 6

    def _num(self, v: float | None) -> float | None:
        return None if v is None else round(float(v), self._FLOAT_PLACES)

    def canonical(self) -> bytes:
        """Byte form the entry hash is computed over.

        Every value is coerced to a canonical type and precision so that the
        same record always produces the same bytes, whether it was just built in
        memory or reloaded from storage.
        """
        return json.dumps({
            "evidence_id": str(self.evidence_id),
            "observation_id": str(self.observation_id),
            "camera_id": str(self.camera_id),
            "pts_s": self._num(self.pts_s),
            # Microsecond precision: storage keeps epoch microseconds, so
            # anything finer cannot survive the round trip.
            "t_norm": self.t_norm.astimezone(UTC).isoformat(timespec="microseconds"),
            "frame_sha256": self.frame_sha256,
            "clip_sha256": self.clip_sha256,
            "pipeline_version": str(self.pipeline_version),
            "model_versions": self.model_versions or {},
            "capture_method": str(self.capture_method),
            "device": str(self.device),
            "source_quality": self._num(self.source_quality),
            "confidence_decomposition": self.confidence_decomposition or {},
            "prev_hash": self.prev_hash,
        }, sort_keys=True, separators=(",", ":")).encode()

    def compute_hash(self) -> str:
        return sha256_bytes(self.canonical())

    def certificate(self) -> BsaS63Certificate:
        return BsaS63Certificate(
            evidence_id=self.evidence_id,
            record_identifier=f"{self.evidence_id} / observation {self.observation_id}",
            record_description=(
                f"Video frame and clip captured by CCTV camera {self.camera_id} "
                f"at {self.t_norm.isoformat()} (stream presentation timestamp "
                f"{self.pts_s:.3f}s)."),
            production_method=(
                "Automated capture from a live RTSP stream by the Saakshya "
                f"pipeline {self.pipeline_version}. Frames were decoded and "
                "written without manual editing, enhancement or re-encoding of "
                "the retained frame. Analytics models recorded in "
                "device_particulars produced the associated metadata; they did "
                "not alter the retained media."),
            device_particulars={
                "camera_id": self.camera_id,
                "processing_device": self.device,
                "pipeline_version": self.pipeline_version,
                "models": self.model_versions,
                "source_quality_score": self.source_quality,
            },
            hash_value=self.entry_hash or self.compute_hash(),
            period_of_operation=(
                f"Record captured {self.t_norm.isoformat()}; manifest created "
                f"{self.created_at.isoformat()}."),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["t_norm"] = self.t_norm.isoformat()
        d["created_at"] = self.created_at.isoformat()
        return d


class VerificationResult:
    """Three outcomes, because integrity and truthfulness are not the same test.

    A record can be exactly what was sealed — every hash matching, the chain
    intact — and still contain a statement that is wrong. Collapsing that into
    "failed" reports a broken chain where none exists, and an operator who is
    shown "EVIDENCE CHAIN BROKEN" over an intact chain learns to disregard the
    warning. Collapsing it into "passed" hides a defect a court would find.

    So a **caution** is neither: the record's integrity holds, and something in
    it needs saying.
    """

    def __init__(self) -> None:
        #: name, ok, detail, level — level is "check" or "caution".
        self.checks: list[tuple[str, bool, str, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail, "check"))

    def caution(self, name: str, detail: str) -> None:
        """Record a defect that does not impugn the record's integrity."""
        self.checks.append((name, False, detail, "caution"))

    @property
    def ok(self) -> bool:
        """Integrity only. Cautions are reported, and do not fail a chain."""
        return all(c[1] for c in self.checks if c[3] == "check")

    @property
    def cautions(self) -> list[tuple[str, str]]:
        return [(n, d) for n, _, d, lv in self.checks if lv == "caution"]

    def to_dict(self) -> dict:
        return {
            "verified": self.ok,
            "checks": [{"check": n, "passed": p, "detail": d, "level": lv}
                       for n, p, d, lv in self.checks],
            "failures": [n for n, p, _, lv in self.checks
                         if not p and lv == "check"],
            "cautions": [{"check": n, "detail": d} for n, d in self.cautions],
        }


#: What a record actually holds, derived from what was stored rather than
#: declared. Derived, not persisted, so adding it changes no manifest hash and
#: every record sealed before it existed still verifies.
def evidence_class(frame_sha256: str | None, clip_sha256: str | None) -> str:
    if frame_sha256 and clip_sha256:
        return "FRAME_AND_CLIP"
    if frame_sha256:
        return "FRAME_ONLY"
    if clip_sha256:
        return "CLIP_ONLY"
    return "METADATA_ONLY"


def _capture_method(frame_sha256: str | None, clip_sha256: str | None) -> str:
    """Say what was captured, not what a sealed record usually captures.

    This string was previously a constant reading "automated capture from live
    RTSP; no manual editing of the retained frame" — written into every record,
    including records with `frame_path=None`. That is an assertion about a
    retained frame that does not exist, made by the component whose entire job
    is to be truthful about provenance. On the live grid, where footage is not
    retained, it was the *usual* case rather than the exception.
    """
    kind = evidence_class(frame_sha256, clip_sha256)
    if kind == "METADATA_ONLY":
        return ("metadata only: no frame or clip was retained, so this record "
                "attests what the system observed and when, not an image. It "
                "is not a sealed copy of footage and must not be offered as one.")
    held = {"FRAME_AND_CLIP": "retained frame and clip",
            "FRAME_ONLY": "retained frame",
            "CLIP_ONLY": "retained clip"}[kind]
    return (f"automated capture from live RTSP; no manual editing of the {held}")



class EvidenceService:
    """Creates, stores and verifies evidence records."""

    def __init__(self, store: Store, root: Path | None = None,
                 pipeline_version: str = "") -> None:
        from saakshya import PIPELINE_VERSION

        self.store = store
        self.root = root or Path("var/evidence")
        self.root.mkdir(parents=True, exist_ok=True)
        self.pipeline_version = pipeline_version or PIPELINE_VERSION

    def _last_hash(self) -> str | None:
        with self.store.engine.connect() as c:
            return c.execute(select(S.evidence.c.entry_hash)
                             .order_by(S.evidence.c.created_at_us.desc())
                             .limit(1)).scalar()

    def create(self, obs: VehicleObservation, *, frame: np.ndarray | None = None,
               clip_path: Path | None = None, device: str = "",
               confidence_decomposition: dict | None = None,
               actor: str = "system") -> EvidenceManifest:
        """Write the frame, hash everything, chain it, persist."""
        eid = evidence_id()
        frame_path = frame_hash = None

        if frame is not None:
            from PIL import Image

            out = self.root / f"{eid}.png"
            # PNG: lossless. A re-encoded frame is a different record from the
            # one that was captured, and the hash must cover what was captured.
            Image.fromarray(frame[:, :, ::-1]).save(out, format="PNG")
            frame_path, frame_hash = str(out), sha256_file(out)

        clip_hash = sha256_file(clip_path) if clip_path and clip_path.exists() else None

        m = EvidenceManifest(
            evidence_id=eid, observation_id=obs.observation_id,
            camera_id=obs.camera_id, pts_s=obs.pts_s, t_norm=obs.t_norm,
            frame_path=frame_path, frame_sha256=frame_hash,
            clip_path=str(clip_path) if clip_path else None, clip_sha256=clip_hash,
            pipeline_version=self.pipeline_version,
            model_versions=obs.model_versions or {},
            capture_method=_capture_method(frame_hash, clip_hash),
            device=device or "edge-node",
            source_quality=obs.observation_quality,
            confidence_decomposition=confidence_decomposition or {},
            prev_hash=self._last_hash(),
        )
        m.entry_hash = m.compute_hash()

        with self.store.engine.begin() as c:
            c.execute(insert(S.evidence).values(
                evidence_id=m.evidence_id, observation_id=m.observation_id,
                camera_id=m.camera_id, pts_s=m.pts_s, t_norm_us=to_us(m.t_norm),
                frame_path=m.frame_path, frame_sha256=m.frame_sha256,
                clip_path=m.clip_path, clip_sha256=m.clip_sha256,
                pipeline_version=m.pipeline_version,
                model_versions=json.dumps(m.model_versions),
                capture_method=m.capture_method, device=m.device,
                source_quality=m.source_quality,
                prev_hash=m.prev_hash, entry_hash=m.entry_hash,
                bsa_s63_status="DRAFT_PENDING_SIGNATURE",
                created_at_us=now_us()))

            # Close the link back. The evidence row has always named its
            # observation; the observation did not name its evidence, so search
            # reported `evidence_available: false` for sightings that were in
            # fact sealed — and an investigator, told nothing was sealed, would
            # seal it again. That is how one sighting acquired two competing
            # manifests. Written in the same transaction as the insert, so the
            # two directions cannot disagree.
            c.execute(update(S.observations)
                      .where(S.observations.c.observation_id == m.observation_id)
                      .values(evidence_ref=m.evidence_id))
        self.store.audit(actor, "evidence_create", target=m.evidence_id,
                         result_count=1)
        return m

    def find_by_observation(self, observation_id: str) -> EvidenceManifest | None:
        """The existing sealed record for an observation, if there is one.

        Sealing is idempotent per observation. Two records for one sighting sit
        at different points in the hash chain and are indistinguishable from
        each other in an export, so a double-click on "Seal evidence" would
        put two competing manifests for the same frame into a case file. The
        chain is meant to make tampering visible, not to accumulate copies.
        """
        with self.store.engine.connect() as c:
            eid = c.execute(
                select(S.evidence.c.evidence_id)
                .where(S.evidence.c.observation_id == observation_id)
                .order_by(S.evidence.c.created_at_us.asc())
                .limit(1)).scalar()
        return self.load(eid) if eid else None

    def load(self, eid: str) -> EvidenceManifest | None:
        with self.store.engine.connect() as c:
            r = c.execute(select(S.evidence).where(
                S.evidence.c.evidence_id == eid)).first()
        if not r:
            return None
        d = r._mapping
        from saakshya.store import from_us_required
        return EvidenceManifest(
            evidence_id=d["evidence_id"], observation_id=d["observation_id"],
            camera_id=d["camera_id"], pts_s=d["pts_s"],
            # An evidence record whose timestamp is NULL cannot be verified or
            # certified, so loading it must fail rather than produce a manifest
            # with a hole in it.
            t_norm=from_us_required(d["t_norm_us"], "evidence.t_norm_us"),
            frame_path=d["frame_path"], frame_sha256=d["frame_sha256"],
            clip_path=d["clip_path"], clip_sha256=d["clip_sha256"],
            pipeline_version=d["pipeline_version"],
            model_versions=json.loads(d["model_versions"]) if d["model_versions"] else {},
            capture_method=d["capture_method"] or "", device=d["device"] or "",
            source_quality=d["source_quality"],
            prev_hash=d["prev_hash"], entry_hash=d["entry_hash"],
        )

    def verify(self, eid: str) -> VerificationResult:
        """Verify one evidence record end to end.

        Checks the manifest hash, the frame on disk, the clip on disk, and the
        link to the previous record. Any single failure fails the whole result:
        partial integrity is not integrity.
        """
        r = VerificationResult()
        m = self.load(eid)
        if m is None:
            r.add("record exists", False, f"no evidence record {eid}")
            return r
        r.add("record exists", True, eid)

        recomputed = m.compute_hash()
        r.add("manifest hash", recomputed == m.entry_hash,
              "manifest content does not match its recorded hash"
              if recomputed != m.entry_hash else "matches")

        # State the scope of what was verified. Skipping the media checks when
        # there is no media meant a metadata-only record returned exactly the
        # same PASS as a record whose frame had been hashed and re-checked —
        # the reader could not tell which had happened. Absence of media is a
        # property of the record and belongs in its verification, stated.
        kind = evidence_class(m.frame_sha256, m.clip_sha256)
        if kind == "METADATA_ONLY":
            r.add("media retained", True,
                  "none — this record attests metadata only. Its integrity "
                  "checks cover the manifest and the chain, and cover no image.")

            # A record whose own words contradict its hashes.
            #
            # `capture_method` was once a constant asserting "no manual editing
            # of the retained frame", written into metadata-only records too.
            # The generator was fixed; the records already sealed were not, and
            # they cannot be. Editing a sealed record to correct it would break
            # the chain and would be precisely the tampering this system exists
            # to detect — so the record stands, and the verification says what
            # is wrong with it.
            #
            # This is deliberately **not** a failure. The record's integrity is
            # intact: it is exactly what was sealed. What is defective is a
            # statement inside it, and a reader relying on that statement needs
            # to be told.
            if "retained" in m.capture_method and not m.capture_method.startswith(
                    "metadata only"):
                r.caution("capture method consistent",
                      "this record's capture_method asserts a retained frame or "
                      "clip, and neither was retained. The record is unmodified "
                      "and its chain is intact — the defective statement was "
                      "sealed in, by a generator since corrected. Do not offer "
                      "this record as a sealed copy of footage.")

        if m.frame_path:
            p = Path(m.frame_path)
            if not p.exists():
                r.add("frame present", False, f"missing: {m.frame_path}")
            else:
                r.add("frame present", True, m.frame_path)
                actual = sha256_file(p)
                r.add("frame hash", actual == m.frame_sha256,
                      "frame file has been modified since capture"
                      if actual != m.frame_sha256 else "matches")

        if m.clip_path:
            p = Path(m.clip_path)
            if not p.exists():
                r.add("clip present", False, f"missing: {m.clip_path}")
            else:
                r.add("clip present", True, m.clip_path)
                actual = sha256_file(p)
                r.add("clip hash", actual == m.clip_sha256,
                      "clip file has been modified since capture"
                      if actual != m.clip_sha256 else "matches")

        if m.prev_hash:
            with self.store.engine.connect() as c:
                found = c.execute(select(S.evidence.c.evidence_id).where(
                    S.evidence.c.entry_hash == m.prev_hash)).first()
            r.add("chain link", found is not None,
                  "predecessor named by prev_hash is missing — the chain has "
                  "been broken or truncated" if found is None else "intact")
        return r

    def verify_chain(self) -> VerificationResult:
        """Verify every record and the links between them."""
        r = VerificationResult()
        with self.store.engine.connect() as c:
            rows = list(c.execute(select(S.evidence)
                                  .order_by(S.evidence.c.created_at_us)))
        prev = None
        for row in rows:
            eid = row._mapping["evidence_id"]
            one = self.verify(eid)
            r.add(f"record {eid}", one.ok,
                  "" if one.ok else ", ".join(one.to_dict()["failures"]))
            # Cautions travel up with the record they belong to. A defect
            # visible when verifying one record and invisible when verifying
            # the chain is a defect nobody will ever see: the chain is what
            # gets checked before a record is relied on.
            for name, detail in one.cautions:
                r.caution(f"{eid}: {name}", detail)
            if prev is not None and row._mapping["prev_hash"] != prev:
                r.add(f"link {eid}", False,
                      "prev_hash does not match the preceding record")
            prev = row._mapping["entry_hash"]
        if not rows:
            r.add("chain", True, "no evidence records")
        return r

    def export(self, eid: str, out_dir: Path | None = None) -> dict:
        """Export a verifiable evidence package.

        Verification runs *before* export and is included in the package, so a
        recipient sees the state at export time rather than having to trust it.
        """
        m = self.load(eid)
        if m is None:
            raise KeyError(eid)
        verification = self.verify(eid)
        pkg = {
            "package_version": "saakshya-evidence/1",
            "exported_at": datetime.now(UTC).isoformat(),
            "manifest": m.to_dict(),
            "verification_at_export": verification.to_dict(),
            "bsa_s63_certificate": m.certificate().to_dict(),
            "notice": (
                "This package is prepared for authorised certification. It is "
                "not, and does not assert, a determination of admissibility."),
        }
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{eid}.evidence.json").write_text(json.dumps(pkg, indent=2))
        return pkg
