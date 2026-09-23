"""The evidence view says what each sealed record is, not just that it held.

It listed record ids with ticks. Each row now carries camera, capture time,
whether a still was sealed and the hash link to the record before; integrity
stays statewide while the content of an out-of-jurisdiction record is withheld.
All plates are synthetic fixtures.
"""
from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.security import Role, TokenService
from tests.conftest import make_observation


def test_records_carry_content_and_links_and_respect_jurisdiction(tmp_path):
    state = AppState(f"sqlite:///{tmp_path / 'e.db'}", evidence_root=tmp_path / "ev")
    state.require_auth = True
    s = state.store
    for cid, d in (("CAM-A", "Ahmedabad"), ("CAM-B", "Gandhinagar")):
        s.upsert_camera({"camera_id": cid, "name": f"{cid} gate", "district": d,
                         "tier": "A", "enabled": True})
    oa = make_observation("CAM-A", plate="GJ01EV0001", offset_s=0, district="Ahmedabad")
    ob = make_observation("CAM-B", plate="GJ02EV0002", offset_s=60, district="Gandhinagar",
                          track="T2")
    s.add_observations([oa, ob])
    frame = np.zeros((72, 128, 3), dtype=np.uint8)
    ea = state.evidence.create(oa, frame=frame)
    eb = state.evidence.create(ob, frame=frame)
    ts = TokenService(s)
    ts.upsert_user("sup", Role.SUPERVISOR)
    ts.upsert_user("inv", Role.INVESTIGATOR, districts=("Ahmedabad",))
    c = TestClient(create_app(state), raise_server_exceptions=False)

    def recs(user):
        r = c.get("/evidence/chain/verify",
                  headers={"Authorization": f"Bearer {ts.mint(user)}"})
        assert r.status_code == 200, r.text[:300]
        return r.json()["records"]

    sup = recs("sup")
    assert [r["evidence_id"] for r in sup] == [ea.evidence_id, eb.evidence_id]
    assert all(r["ok"] is True and r["still_sealed"] for r in sup)
    assert sup[0]["plate"] == "GJ01EV0001" and sup[0]["camera_name"] == "CAM-A gate"
    # The second record's link is the first record's hash.
    assert sup[1]["prev_hash"] == sup[0]["entry_hash"]

    inv = recs("inv")
    assert inv[0]["plate"] == "GJ01EV0001"
    assert inv[1]["withheld"] == "outside your jurisdiction"
    assert "plate" not in inv[1] and "camera_id" not in inv[1]
    assert inv[1]["ok"] is True                   # integrity is still reported


def test_the_page_keeps_the_records_the_server_sends() -> None:
    """The first version of this change passed its server test and showed
    nothing new: the client's normaliser rebuilt the response without them."""
    from pathlib import Path
    app = (Path(__file__).resolve().parents[2] / "ui/app.js").read_text(encoding="utf-8")
    norm = app[app.index("function normaliseVerification"):]
    norm = norm[:norm.index("\n}\n")]
    assert "records: v.records" in norm
    assert "evidenceRecordsTable(v.records)" in app
