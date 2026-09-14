"""Evidence integrity: every mutation must fail verification."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import update

from saakshya.evidence import EvidenceService
from saakshya.store import Store, VehicleObservation
from saakshya.store import schema as S

T0 = datetime(2026, 9, 1, 18, 0, 0, tzinfo=UTC)


def ob(cam="C-014", plate="GJ05AB1234", sec=10.0, key="e1"):
    t = T0 + timedelta(seconds=sec)
    return VehicleObservation(
        camera_id=cam, pts_s=sec, t_norm=t, t_ingest=t, dedup_key=key,
        plate=plate, object_type="car", observation_quality=0.91,
        model_versions={"pipeline": "saakshya@0.1.0", "ocr": "cct-s-v2"})


@pytest.fixture
def svc(tmp_path: Path):
    s = Store("sqlite:///:memory:")
    s.create_all()
    s.upsert_camera({"camera_id": "C-014", "district": "Ahmedabad"})
    return EvidenceService(s, root=tmp_path / "evidence"), s, tmp_path


def frame(seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_evidence_creates_and_verifies(svc):
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="edge-AHM-01")
    assert m.frame_sha256 and m.entry_hash
    r = es.verify(m.evidence_id)
    assert r.ok, r.to_dict()


def test_manifest_records_provenance(svc):
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="edge-AHM-01")
    assert m.model_versions["ocr"] == "cct-s-v2"
    assert m.pipeline_version
    assert m.source_quality == pytest.approx(0.91)
    assert "no manual editing" in m.capture_method


# --------------------------------------------------------------------------- #
# Tamper detection — each of these MUST fail
# --------------------------------------------------------------------------- #
def test_modified_frame_fails_verification(svc):
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="d")
    assert es.verify(m.evidence_id).ok

    from PIL import Image
    Image.fromarray(frame(seed=99)).save(m.frame_path, format="PNG")
    r = es.verify(m.evidence_id)
    assert not r.ok
    assert "frame hash" in r.to_dict()["failures"]


def test_missing_frame_fails_verification(svc):
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="d")
    Path(m.frame_path).unlink()
    r = es.verify(m.evidence_id)
    assert not r.ok
    assert "frame present" in r.to_dict()["failures"]


def test_modified_clip_fails_verification(svc, tmp_path):
    es, s, _ = svc
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"original clip bytes")
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), clip_path=clip, device="d")
    assert es.verify(m.evidence_id).ok

    clip.write_bytes(b"tampered clip bytes")
    r = es.verify(m.evidence_id)
    assert not r.ok
    assert "clip hash" in r.to_dict()["failures"]


def test_modified_manifest_fails_verification(svc):
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="d")
    with s.engine.begin() as c:
        c.execute(update(S.evidence)
                  .where(S.evidence.c.evidence_id == m.evidence_id)
                  .values(camera_id="C-999"))
    r = es.verify(m.evidence_id)
    assert not r.ok
    assert "manifest hash" in r.to_dict()["failures"]


def test_broken_chain_link_fails_verification(svc):
    es, s, _ = svc
    o1, o2 = ob(key="c1"), ob(sec=20, key="c2")
    s.add_observations([o1, o2])
    es.create(o1, frame=frame(1), device="d")
    m2 = es.create(o2, frame=frame(2), device="d")
    assert m2.prev_hash
    assert es.verify(m2.evidence_id).ok

    with s.engine.begin() as c:
        c.execute(update(S.evidence)
                  .where(S.evidence.c.evidence_id == m2.evidence_id)
                  .values(prev_hash="0" * 64))
    r = es.verify(m2.evidence_id)
    assert not r.ok


def test_chain_verification_covers_every_record(svc):
    es, s, _ = svc
    for i in range(3):
        o = ob(sec=10 + i, key=f"n{i}")
        s.add_observations([o])
        es.create(o, frame=frame(i), device="d")
    assert es.verify_chain().ok


# --------------------------------------------------------------------------- #
# BSA s.63 certificate
# --------------------------------------------------------------------------- #
def test_certificate_is_a_draft_with_empty_signatures(svc):
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    cert = es.create(o, frame=frame(), device="edge-01").certificate()
    assert cert.status == "DRAFT_PENDING_SIGNATURE"
    assert cert.signature_person_in_charge is None
    assert cert.signature_expert is None
    assert cert.hash_value and cert.hash_algorithm == "SHA-256"
    assert cert.device_particulars["camera_id"] == "C-014"
    assert "s.63" in cert.statutory_note


def test_nothing_claims_legal_admissibility(svc):
    """The one string that must never appear anywhere in an evidence package."""
    es, s, tmp = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="d")
    blob = json.dumps(es.export(m.evidence_id, out_dir=tmp / "out")).lower()
    assert "legally admissible" not in blob
    assert "is admissible" not in blob
    assert "determination for the court" in blob


def test_export_embeds_verification_state(svc, tmp_path):
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="d")
    pkg = es.export(m.evidence_id, out_dir=tmp_path / "out")
    assert pkg["verification_at_export"]["verified"] is True
    assert (tmp_path / "out" / f"{m.evidence_id}.evidence.json").exists()


def test_export_of_tampered_evidence_reports_failure_rather_than_refusing(svc, tmp_path):
    """An export must not silently succeed, and must not hide the problem: the
    recipient needs to see that verification failed at export time."""
    es, s, _ = svc
    o = ob()
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="d")
    Path(m.frame_path).unlink()
    pkg = es.export(m.evidence_id, out_dir=tmp_path / "out")
    assert pkg["verification_at_export"]["verified"] is False
    assert pkg["verification_at_export"]["failures"]


# --------------------------------------------------------------------------- #
# Regression: the canonical form must not depend on numeric representation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("pts", [10, 10.0, 10.000000, 0, 0.0])
def test_hash_is_stable_across_numeric_representation(svc, pts):
    """An untampered record once failed its own verification because pts_s=10
    serialised as `10` at creation and `10.0` after a round trip through a Float
    column. A hash that depends on representation rather than content is not an
    integrity check."""
    es, s, _ = svc
    o = ob(sec=pts, key=f"p{pts}")
    s.add_observations([o])
    m = es.create(o, frame=frame(), device="d")
    r = es.verify(m.evidence_id)
    assert r.ok, f"pts_s={pts!r} ({type(pts).__name__}) broke verification: " \
                 f"{r.to_dict()['failures']}"


def test_hash_still_changes_when_content_actually_changes(svc):
    """The normalisation must not have made the hash insensitive."""
    es, s, _ = svc
    o1 = ob(sec=10.0, key="q1")
    o2 = ob(sec=10.5, key="q2")
    s.add_observations([o1, o2])
    m1 = es.create(o1, frame=frame(1), device="d")
    m2 = es.create(o2, frame=frame(2), device="d")
    assert m1.entry_hash != m2.entry_hash
    # And a one-microsecond difference must still be visible.
    m3 = es.load(m1.evidence_id)
    m3.pts_s = 10.000001
    assert m3.compute_hash() != m1.entry_hash


# --------------------------------------------------------------------------- #
# A defective statement inside an intact record
# --------------------------------------------------------------------------- #
def test_a_sealed_record_that_overstates_what_it_holds_cautions_not_fails(svc):
    """Integrity and truthfulness are separate tests, and must stay separate.

    `capture_method` was once a constant asserting "no manual editing of the
    retained frame", written into metadata-only records too. The generator was
    corrected; records already sealed with the wrong string cannot be — editing
    a sealed record to fix its wording would break the chain and would be
    exactly the tampering this system exists to detect.

    So such a record must **verify** — it is unmodified, and its chain holds —
    while its verification says plainly that a statement inside it is wrong.
    Failing it instead would put "VERIFICATION FAILED" over an intact chain,
    and an operator shown that learns to disregard the warning.
    """
    es, s, _ = svc
    o = ob()
    s.add_observations([o])

    # Seal it the way the old generator did, so the entry hash covers the
    # overstating string. Editing the string afterwards would be tampering and
    # would fail on the manifest hash — which is correct, and a different test.
    import saakshya.evidence.manifest as mod
    original = mod._capture_method
    mod._capture_method = lambda f, c: (
        "automated capture from live RTSP; no manual editing of the retained "
        "frame")
    try:
        m = es.create(o, device="edge-AHM-01")   # no frame: metadata only
    finally:
        mod._capture_method = original

    assert m.frame_sha256 is None and m.clip_sha256 is None
    assert "retained frame" in m.capture_method

    r = es.verify(m.evidence_id).to_dict()
    assert r["cautions"], "the overstatement must be reported"
    assert "capture method consistent" in r["cautions"][0]["check"]
    assert not r["failures"], "a defective statement is not an integrity failure"

    chain = es.verify_chain().to_dict()
    assert chain["verified"] is True, "the chain is intact and must say so"
    assert chain["cautions"], "the caution must survive into the chain result"
