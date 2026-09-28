#!/usr/bin/env python3
"""Emit the Model 3 federated analytics report.

A named deliverable: "sample federated analytics report". Model 3 is the
federation middleware — it onboards heterogeneous camera systems behind one
platform, so the report worth generating is the one that shows the estate *as
federated*: broken down by the provenance of each source, and — the point of
federation — the vehicles that were seen across more than one source.

    python tools/reports/federated_report.py \
        --db sqlite:///var/demo.db --out reports/MODEL3_FEDERATED.md

It is generated from the live store, never written, so it cannot drift from what
the platform holds. The store is opened **read-only**: a plain ``sqlite:///``
path is rewritten to ``sqlite:///file:<abs>?mode=ro&uri=true`` so the script
cannot create, migrate or write the database it reports on. With no ``--out`` it
prints to stdout. For a frozen snapshot, ``--immutable`` also avoids SQLite
lock/sidecar writes (and ignores WAL updates).

Provenance is resolved with the platform's own classifier
(:func:`saakshya.command.domain.classify_source_domain`): the stored
``source_domain`` wins, and where a camera row does not carry one — or an
observation arrives from a camera not in the registry — the id pattern decides,
exactly as the wall and the GIS layers label it. Nothing here is sampled.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import and_, func, inspect, select

from saakshya.command.domain import DOMAINS, classify_source_domain
from saakshya.store import schema as S
from saakshya.store.repository import Store, from_us

#: Column order for the per-domain tables. Kept in the module's canonical domain
#: order so GOVERNMENT / OWN_FEED / SYNTHETIC_CONTROL always read the same way,
#: and an unregistered source is appended after them.
UNREGISTERED = "UNREGISTERED"


def read_only_url(url: str, *, immutable: bool = False) -> str:
    """Rewrite a plain ``sqlite:///`` path into a read-only URI open.

    ``immutable`` also avoids SQLite lock/sidecar writes for a frozen snapshot.
    It ignores WAL updates, so use it only when the database is no longer being
    written. Non-SQLite callers must use a read-only database role.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    tail = url[len(prefix):]
    if tail.startswith("file:"):
        path, _, query = tail.partition("?")
        params = dict(parse_qsl(query))
        params.update(mode="ro", uri="true")
        if immutable:
            params["immutable"] = "1"
        return f"{prefix}{path}?{urlencode(params)}"
    if tail == ":memory:":
        return url
    abs_path = Path(tail).resolve()
    # quote the path so a space or a '?' in it cannot corrupt the query string.
    return (f"{prefix}file:{quote(str(abs_path))}?mode=ro&uri=true"
            + ("&immutable=1" if immutable else ""))


def _domain_resolver(cam_rows: list[dict]):
    """Return ``camera_id -> source_domain`` using the platform's classifier.

    Memoised, and falls back to id-pattern classification for a camera that has
    observations but no registry row (which happens routinely — see
    ``Store._cam_ctx``). Unknown-but-classifiable ids still resolve; only a
    genuinely blank id would land in :data:`UNREGISTERED`.
    """
    stored: dict[str, str] = {}
    for cam in cam_rows:
        cid = str(cam["camera_id"])
        stored[cid] = classify_source_domain(
            cid, stored=cam.get("source_domain"),
            integration_model=cam.get("integration_model"))
    cache = dict(stored)

    def resolve(camera_id: str | None) -> str:
        cid = str(camera_id or "")
        if not cid:
            return UNREGISTERED
        got = cache.get(cid)
        if got is None:
            got = classify_source_domain(cid)
            cache[cid] = got
        return got

    return resolve


def _domain_order(seen: set[str]) -> list[str]:
    """Canonical domains first, then anything else (e.g. UNREGISTERED)."""
    ordered = [d for d in DOMAINS if d in seen]
    ordered += sorted(seen - set(DOMAINS))
    return ordered


def _camera_rows(store: Store) -> list[dict]:
    """Camera rows, reading only the columns this report needs *and* that the

    opened store actually has. A read-only report cannot migrate the store it
    reads (see ``read_only_url``), so it must not assume a current schema:
    ``list_cameras`` selects every column and would raise ``no such column`` on
    a store older than ``source_domain``. Selecting the present subset lets the
    report degrade to id-pattern provenance instead of crashing.
    """
    want = ("camera_id", "source_domain", "department", "integration_model")
    have = {col["name"] for col in inspect(store.engine).get_columns("cameras")}
    cols = [S.cameras.c[name] for name in want if name in have]
    with store.engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(select(*cols))]


def gather(store: Store) -> dict:
    """All figures for the report, in one pass of read-only queries."""
    cam_rows = _camera_rows(store)
    resolve = _domain_resolver(cam_rows)

    # -- cameras per source domain and department --------------------------- #
    cameras_by_domain: dict[str, int] = {}
    cameras_by_department: dict[str, int] = {}
    domain_department: dict[str, dict[str, int]] = {}
    for cam in cam_rows:
        dom = resolve(cam["camera_id"])
        dept = (cam.get("department") or "(unspecified)").strip() or "(unspecified)"
        cameras_by_domain[dom] = cameras_by_domain.get(dom, 0) + 1
        cameras_by_department[dept] = cameras_by_department.get(dept, 0) + 1
        domain_department.setdefault(dom, {})
        domain_department[dom][dept] = domain_department[dom].get(dept, 0) + 1

    obs = S.observations.c
    with store.engine.connect() as c:
        # -- observations per source and object type ------------------------ #
        obs_rows = c.execute(
            select(obs.camera_id, obs.object_type, func.count())
            .group_by(obs.camera_id, obs.object_type)).all()

        # -- plate publication, per (plate, camera) ------------------------- #
        plated = and_(obs.plate.isnot(None), obs.plate != "")
        plate_rows = c.execute(
            select(obs.plate, obs.camera_id, func.count(),
                   func.max(obs.plate_votes))
            .where(plated)
            .group_by(obs.plate, obs.camera_id)).all()

        # -- watchlist incidents (alerts) per source ------------------------ #
        alert_rows = c.execute(
            select(S.alerts.c.camera_id, func.count())
            .group_by(S.alerts.c.camera_id)).all()

        # -- time range ----------------------------------------------------- #
        span = c.execute(select(func.min(obs.t_norm_us),
                                func.max(obs.t_norm_us))).first()
        total_observations = c.execute(
            select(func.count()).select_from(S.observations)).scalar_one()
        watchlist_total = c.execute(
            select(func.count()).select_from(S.watchlist)).scalar_one()
        alerts_total = c.execute(
            select(func.count()).select_from(S.alerts)).scalar_one()

    observations_by_domain: dict[str, int] = {}
    obs_domain_type: dict[str, dict[str, int]] = {}
    for cid, otype, n in obs_rows:
        dom = resolve(cid)
        ot = otype or "unknown"
        observations_by_domain[dom] = observations_by_domain.get(dom, 0) + int(n)
        obs_domain_type.setdefault(dom, {})
        obs_domain_type[dom][ot] = obs_domain_type[dom].get(ot, 0) + int(n)

    # A plate's cameras, its domains, and its strongest vote anywhere. This is
    # the federation index: a plate whose domain set has more than one member
    # was seen across systems, which is the thing federation makes possible.
    plate_index: dict[str, dict] = {}
    for plate, cid, n, votes in plate_rows:
        if not plate:
            continue
        dom = resolve(cid)
        entry = plate_index.setdefault(
            plate, {"cameras": set(), "domains": set(), "max_votes": 0, "reads": 0})
        entry["cameras"].add(str(cid))
        entry["domains"].add(dom)
        entry["max_votes"] = max(entry["max_votes"], int(votes or 0))
        entry["reads"] += int(n)

    plates_by_domain: dict[str, dict[str, int]] = {}
    for e in plate_index.values():
        for dom in e["domains"]:
            d = plates_by_domain.setdefault(
                dom, {"distinct": 0, "confirmed": 0, "leads": 0})
            d["distinct"] += 1
            if e["max_votes"] >= 2:
                d["confirmed"] += 1
            elif e["max_votes"] == 1:
                d["leads"] += 1

    cross_camera = {p: e for p, e in plate_index.items() if len(e["cameras"]) > 1}
    cross_source = {p: e for p, e in plate_index.items() if len(e["domains"]) > 1}

    incidents_by_domain: dict[str, int] = {}
    for cid, n in alert_rows:
        incidents_by_domain[resolve(cid)] = (
            incidents_by_domain.get(resolve(cid), 0) + int(n))

    t_from = from_us(span[0]) if span and span[0] is not None else None
    t_to = from_us(span[1]) if span and span[1] is not None else None

    return {
        "cameras_total": len(cam_rows),
        "cameras_by_domain": cameras_by_domain,
        "cameras_by_department": cameras_by_department,
        "domain_department": domain_department,
        "observations_total": int(total_observations),
        "observations_by_domain": observations_by_domain,
        "obs_domain_type": obs_domain_type,
        "plates_by_domain": plates_by_domain,
        "distinct_plates": len(plate_index),
        "cross_camera": cross_camera,
        "cross_source": cross_source,
        "watchlist_total": int(watchlist_total),
        "alerts_total": int(alerts_total),
        "incidents_by_domain": incidents_by_domain,
        "t_from": t_from,
        "t_to": t_to,
    }


def render(data: dict, db_url: str) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    out: list[str] = []
    w = out.append

    domains = _domain_order(
        set(data["cameras_by_domain"])
        | set(data["observations_by_domain"])
        | set(data["plates_by_domain"])
        | set(data["incidents_by_domain"]))

    w("# Federated analytics report")
    w("")
    w(f"Generated {now} from `{db_url}` (opened read-only). Every figure is")
    w("counted in SQL across the whole store; nothing is sampled or estimated.")
    w("")
    w("A *source domain* is a camera's provenance, resolved with the platform's")
    w("own classifier — GOVERNMENT (the supplied grid), OWN_FEED (participant")
    w("submission feeds) and SYNTHETIC_CONTROL (labelled evaluation slots),")
    w("never mixed. This is a federation report: the section that matters is")
    w("**cross-source vehicles**, the plates seen under more than one domain.")
    w("")

    # -- coverage ----------------------------------------------------------- #
    w("## Estate")
    w("")
    w("| | |")
    w("|---|---:|")
    w(f"| Cameras onboarded | {data['cameras_total']:,} |")
    w(f"| Observations | {data['observations_total']:,} |")
    w(f"| Distinct registration marks | {data['distinct_plates']:,} |")
    w(f"| Watchlist entries | {data['watchlist_total']:,} |")
    w(f"| Alerts raised | {data['alerts_total']:,} |")
    if data["t_from"] and data["t_to"]:
        w(f"| First observation | {data['t_from'].isoformat()} |")
        w(f"| Last observation | {data['t_to'].isoformat()} |")
    else:
        w("| Time range | no observations in store |")
    w("")

    # -- cameras per source and department ---------------------------------- #
    w("## Cameras per source domain")
    w("")
    w("| Source domain | Cameras |")
    w("|---|---:|")
    for dom in domains:
        w(f"| {dom} | {data['cameras_by_domain'].get(dom, 0):,} |")
    w("")

    w("### By source domain and department")
    w("")
    w("| Source domain | Department | Cameras |")
    w("|---|---|---:|")
    for dom in domains:
        depts = data["domain_department"].get(dom, {})
        for dept in sorted(depts):
            w(f"| {dom} | {dept} | {depts[dept]:,} |")
    w("")

    # -- observations per source and object type ---------------------------- #
    w("## Observations per source and object type")
    w("")
    types = sorted({t for per in data["obs_domain_type"].values() for t in per})
    if types:
        header = "| Source domain | " + " | ".join(types) + " | Total |"
        w(header)
        w("|---" * (len(types) + 2) + "|")
        for dom in domains:
            per = data["obs_domain_type"].get(dom, {})
            cells = " | ".join(f"{per.get(t, 0):,}" for t in types)
            total = data["observations_by_domain"].get(dom, 0)
            w(f"| {dom} | {cells} | {total:,} |")
    else:
        w("No observations in the store.")
    w("")

    # -- plates per source -------------------------------------------------- #
    w("## Plates published per source")
    w("")
    w("Distinct marks; *confirmed* had two or more agreeing reads, *leads* had")
    w("one. A mark seen under two domains is counted in each — the deduplicated")
    w("figure is the distinct-marks line above.")
    w("")
    w("| Source domain | Distinct | Confirmed | Leads |")
    w("|---|---:|---:|---:|")
    for dom in domains:
        p = data["plates_by_domain"].get(dom, {})
        w(f"| {dom} | {p.get('distinct', 0):,} | {p.get('confirmed', 0):,} | "
          f"{p.get('leads', 0):,} |")
    w("")

    # -- watchlist incidents per source ------------------------------------- #
    w("## Watchlist incidents per source")
    w("")
    if data["alerts_total"]:
        w("| Source domain | Alerts |")
        w("|---|---:|")
        for dom in domains:
            w(f"| {dom} | {data['incidents_by_domain'].get(dom, 0):,} |")
    else:
        w("No watchlist alerts have been raised in this store.")
    w("")

    # -- cross-source correlation ------------------------------------------- #
    w("## Cross-camera and cross-source vehicles")
    w("")
    w(f"- **{len(data['cross_camera']):,}** marks were seen by more than one "
      "camera.")
    w(f"- **{len(data['cross_source']):,}** marks were seen under more than one "
      "source domain — the vehicles federation actually correlated.")
    w("")
    if data["cross_source"]:
        w("The strongest cross-source correlations (a mark, the domains that saw")
        w("it, and how many cameras):")
        w("")
        w("| Mark | Domains | Cameras | Reads |")
        w("|---|---|---:|---:|")
        ranked = sorted(data["cross_source"].items(),
                        key=lambda kv: (-len(kv[1]["cameras"]), -kv[1]["reads"]))
        for plate, e in ranked[:25]:
            doms = ", ".join(_domain_order(e["domains"]))
            w(f"| `{plate}` | {doms} | {len(e['cameras'])} | {e['reads']:,} |")
        if len(ranked) > 25:
            w("")
            w(f"…and {len(ranked) - 25:,} more.")
    else:
        w("No mark was seen under more than one source domain in this store.")
    w("")

    w("---")
    w("")
    w("*Federation correlates identities across systems; provenance is carried")
    w("with every figure so a government count is never inflated by own-feed or")
    w("control data.*")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="sqlite:///var/demo.db",
                    help="store URL; a plain sqlite path is opened read-only")
    ap.add_argument("--immutable", action="store_true",
                    help="read a frozen SQLite snapshot without lock/sidecar writes; ignores WAL updates")
    ap.add_argument("--out", default=None,
                    help="output path (inside the worktree); stdout if omitted")
    a = ap.parse_args(argv)

    url = read_only_url(a.db, immutable=a.immutable)
    store = Store(url)
    # A writable SQLite store is migrated first, so an older schema does not
    # raise 'no such column' mid-report. The read-only default cannot migrate
    # (its open is mode=ro) and does not need to: `_camera_rows` reflects the
    # columns the store actually has. A non-SQLite URL is left to a read-only
    # role and is not migrated here.
    if url.startswith("sqlite") and "mode=ro" not in url and ":memory:" not in url:
        store.create_all()
    data = gather(store)
    text = render(data, a.db)

    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} — {data['cameras_total']:,} cameras, "
              f"{data['observations_total']:,} observations, "
              f"{len(data['cross_source']):,} cross-source marks")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
