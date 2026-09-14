"""Sealing links both ways, states what it holds, and does not duplicate.

Three defects found together on the live grid, all of which made the evidence
layer claim more than it held:

  * `observations.evidence_ref` was never written, so search reported
    `evidence_available: false` for sightings that were sealed. An investigator
    told nothing was sealed seals it again — which is how one sighting acquired
    two competing manifests.
  * `capture_method` was a constant asserting "no manual editing of the
    retained frame" on records with no retained frame at all. On the live grid,
    where footage is not retained, that was the usual case.
  * verification skipped the media checks when there was no media, and returned
    the same PASS as a record whose frame had been hashed and re-checked.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from saakshya.evidence.manifest import EvidenceService, evidence_class
from saakshya.store import Store
from saakshya.store.repository import VehicleObservation


@pytest.fixture
def svc(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/ev.db")
    store.create_all()
    store.upsert_camera({"camera_id": "cam21", "name": "Dethali Char Rasta"})
    return EvidenceService(store, root=tmp_path / "media"), store


def _obs(store, oid="OB1"):
    now = datetime.now(UTC)
    o = VehicleObservation(
        observation_id=oid, camera_id="cam21", track_id="TR1",
        segment_id="cam21-S1", pts_s=93.86, t_norm=now, t_ingest=now,
        dedup_key=f"cam21:{oid}", plate="GJ38BH5815", plate_confidence=0.99,
        observation_quality=0.96, model_versions={"model": "anpr-onnx-cpu@1.0.0"})
    store.add_observations([o])
    return o


def test_sealing_links_the_observation_back(svc):
    """The column search reads must be set, not merely derivable."""
    from sqlalchemy import select

    from saakshya.store import schema as S

    service, store = svc
    o = _obs(store)
    m = service.create(o)
    with store.engine.connect() as c:
        ref = c.execute(select(S.observations.c.evidence_ref).where(
            S.observations.c.observation_id == o.observation_id)).scalar()
    assert ref == m.evidence_id


def test_find_by_observation_returns_the_earliest(svc):
    service, store = svc
    o = _obs(store)
    first = service.create(o)
    second = service.create(o)
    assert first.evidence_id != second.evidence_id
    assert service.find_by_observation(o.observation_id).evidence_id == first.evidence_id


def test_metadata_only_record_says_so(svc):
    service, store = svc
    m = service.create(_obs(store))
    assert m.frame_sha256 is None
    assert evidence_class(m.frame_sha256, m.clip_sha256) == "METADATA_ONLY"
    assert "metadata only" in m.capture_method
    assert "retained frame" not in m.capture_method.replace("no frame", "")


def test_verification_states_that_no_media_was_covered(svc):
    service, store = svc
    m = service.create(_obs(store))
    result = service.verify(m.evidence_id)
    names = {c[0] for c in result.checks}
    assert "media retained" in names, (
        "a metadata-only record must say that its checks cover no image")
    detail = next(c for c in result.checks if c[0] == "media retained")[2]
    assert "no image" in detail


def test_a_record_with_a_frame_claims_the_frame(svc):
    import numpy as np
    service, store = svc
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    m = service.create(_obs(store), frame=frame)
    assert m.frame_sha256
    assert evidence_class(m.frame_sha256, m.clip_sha256) == "FRAME_ONLY"
    assert "retained frame" in m.capture_method
