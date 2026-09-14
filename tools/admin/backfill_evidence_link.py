"""Repair observations that were sealed before the back-link existed.

`EvidenceService.create` wrote the evidence row but never set
`observations.evidence_ref`, so search reported `evidence_available: false` for
sightings that were sealed. This sets the link from the evidence table, which is
the authoritative side, and reports duplicates rather than deleting them: a hash
chain is an append-only record and removing an entry from it is not a repair.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select, update

from saakshya.store import Store
from saakshya.store import schema as S


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write the links; without it, only report")
    a = ap.parse_args()

    store = Store(a.db)

    store.create_all()      # a store older than the code is migrated, not queried
    by_obs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with store.engine.connect() as c:
        for row in c.execute(select(S.evidence.c.evidence_id,
                                    S.evidence.c.observation_id,
                                    S.evidence.c.created_at_us)):
            by_obs[row[1]].append((row[0], row[2]))
        linked = {r[0] for r in c.execute(
            select(S.observations.c.observation_id)
            .where(S.observations.c.evidence_ref.isnot(None)))}

    missing = {o: v for o, v in by_obs.items() if o not in linked}
    dupes = {o: v for o, v in by_obs.items() if len(v) > 1}

    print(f"evidence records : {sum(len(v) for v in by_obs.values())}")
    print(f"observations     : {len(by_obs)} sealed, {len(missing)} unlinked")
    for obs, recs in sorted(dupes.items()):
        ids = ", ".join(e for e, _ in sorted(recs, key=lambda r: r[1]))
        print(f"  DUPLICATE      : {obs} has {len(recs)} manifests — {ids}")
    if dupes:
        print("    The earliest is linked. The others are left in place: the "
              "chain is append-only, and a duplicate that is explained is "
              "safer than one that has been quietly removed.")

    if not a.apply:
        print("\ndry run — pass --apply to write the links")
        return 0

    written = 0
    with store.engine.begin() as c:
        for obs, recs in missing.items():
            eid = min(recs, key=lambda r: r[1])[0]        # earliest wins
            written += c.execute(
                update(S.observations)
                .where(S.observations.c.observation_id == obs)
                .values(evidence_ref=eid)).rowcount
    print(f"\nlinked           : {written} observation(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
