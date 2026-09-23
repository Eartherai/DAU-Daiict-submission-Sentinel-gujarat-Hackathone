"""The vehicle trace report: one printable page an officer can sign.

Investigate answered "where has this vehicle been" on screen, and nowhere
else. The CSV export is a list of reads, not a document: nothing in it says
who asked, for what purpose, which reads are single-frame leads, whether a leg
of the route is physically possible, or whether the stills behind it are the
sealed ones. A trace that goes into a case diary needs all of that on paper.

What the report holds, and where each part comes from:

* every read of the mark in the caller's jurisdiction, oldest first
  (`anpr_rows`, the same rows the CSV carries, so the two cannot disagree);
* the route as legs between cameras, with distance, elapsed time and the
  implied speed, and a leg a road vehicle could not drive flagged as a
  possible misread or cloned plate rather than drawn as a route;
* the watchlist status at the moment of printing, stated as a moment;
* the sealed still for each read that has one, embedded, with its SHA-256
  recomputed now and compared to the manifest - a still that no longer matches
  is withheld, not printed as if it were the record;
* who generated it, their role, the purpose they gave, and a digest over the
  rows so a printed copy can be checked against the store.

The page has no script and loads nothing: it prints, saves and emails as one
file. It is rendered from the store at request time, so an unseen plate gives
a report that says so.
"""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saakshya.common.ist import iso_ist

#: Above this a leg is not a drive. Urban arterials in Gujarat do not sustain
#: it; a read pair that implies it is two vehicles or one wrong read.
IMPLAUSIBLE_KMH = 150.0
#: Stills embedded in one report. Each is ~25 KB; a report is a document to
#: print, and past this it is the export package that should be used.
MAX_STILLS = 24
STILL_WIDTH = 360


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def _latlon(cam: dict[str, Any]) -> tuple[float, float] | None:
    lat, lon = cam.get("lat"), cam.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def legs(reads: list[dict[str, Any]], cams: dict[str, dict[str, Any]]
         ) -> list[dict[str, Any]]:
    """Consecutive moves between *different* cameras, oldest first.

    Repeated reads at one camera are one stop, not a leg. Distance is straight
    line, so the implied speed is a lower bound on the real one: a leg flagged
    here is impossible by road too.
    """
    out: list[dict[str, Any]] = []
    prev = None
    for r in reads:
        if prev is not None and r["camera_id"] != prev["camera_id"]:
            t0, t1 = _parse(prev["timestamp_utc"]), _parse(r["timestamp_utc"])
            a = _latlon(cams.get(prev["camera_id"], {}))
            b = _latlon(cams.get(r["camera_id"], {}))
            km = _haversine_km(a, b) if a and b else None
            secs = (t1 - t0).total_seconds() if t0 and t1 else None
            kmh = (km / (secs / 3600.0)) if km is not None and secs and secs > 0 else None
            flag = None
            if km is not None and secs is not None:
                if secs <= 0 and km > 0.5:
                    flag = "read at two places at once"
                elif kmh is not None and kmh > IMPLAUSIBLE_KMH:
                    flag = f"implies {kmh:.0f} km/h"
            out.append({"from": prev["camera_id"], "to": r["camera_id"],
                        "from_ist": prev["timestamp_ist"], "to_ist": r["timestamp_ist"],
                        "km": km, "seconds": secs, "kmh": kmh, "flag": flag})
        prev = r
    return out


def _still(state: Any, evidence_id: str) -> dict[str, Any]:
    """The sealed still as a data URI, or the reason it is not printed."""
    from PIL import Image

    from saakshya.evidence.manifest import sha256_file

    m = state.evidence.load(evidence_id)
    if m is None:
        return {"status": "no manifest"}
    if not m.frame_path:
        return {"status": "no frame sealed", "manifest": m.entry_hash}
    p = Path(m.frame_path)
    if not p.is_file():
        p = Path(state.evidence.root) / p.name
    if not p.is_file():
        return {"status": "frame not on this server", "manifest": m.entry_hash}
    digest = sha256_file(p)
    if m.frame_sha256 and digest != m.frame_sha256:
        return {"status": "FRAME DOES NOT MATCH ITS SEAL - withheld",
                "sha256": digest, "manifest": m.entry_hash}
    img = Image.open(p).convert("RGB")
    if img.width > STILL_WIDTH:
        img = img.resize((STILL_WIDTH, max(1, round(img.height * STILL_WIDTH / img.width))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return {"status": "verified" if m.frame_sha256 else "no digest recorded",
            "sha256": digest, "manifest": m.entry_hash,
            "uri": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}


def build(state: Any, ctx: Any, plate: str, *, limit: int = 500) -> dict[str, Any]:
    """Everything the page prints, as data. Access is checked by the caller."""
    from saakshya.analytics.plates import normalise
    from saakshya.reports.anpr import anpr_rows
    from saakshya.security import Permission

    canon = normalise(plate) or plate.upper()
    rows = anpr_rows(state.store, plate=canon, reads="all", limit=limit,
                     districts=ctx.principal.scope_filter())
    rows.sort(key=lambda r: r["timestamp_utc"])
    cams = {cid: state.store.get_camera(cid) or {} for cid in {r["camera_id"] for r in rows}}

    may_stills = ctx.principal.may(Permission.EVIDENCE_READ)
    stills: dict[str, dict[str, Any]] = {}
    for r in rows:
        eid = r.get("evidence_id")
        if not eid or eid in stills:
            continue
        if not may_stills:
            stills[eid] = {"status": "your role does not include evidence access"}
        elif sum(1 for s in stills.values() if "uri" in s) >= MAX_STILLS:
            stills[eid] = {"status": f"not embedded (report holds the first {MAX_STILLS})"}
        else:
            try:
                stills[eid] = _still(state, eid)
            except Exception as exc:        # a broken file must not sink the report
                stills[eid] = {"status": f"could not be read: {type(exc).__name__}"}

    try:
        wl = state.investigation.watchlist_status(ctx, canon)
    except Exception:
        wl = {"checked": False, "reason": "watchlist could not be checked"}

    route = legs(rows, cams)
    now = datetime.now(UTC)
    canonical = json.dumps(
        [[r["observation_id"], r["timestamp_utc"], r["camera_id"], r["plate"],
          r["confidence"], r["votes"], r.get("evidence_id") or ""] for r in rows],
        separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    confirmed = sum(1 for r in rows if r["confirmed"] == "yes")
    scope = ctx.principal.scope_filter()
    return {
        "plate": canon, "asked_as": plate, "rows": rows, "cameras": cams,
        "legs": route, "stills": stills, "watchlist": wl,
        "confirmed": confirmed, "leads": len(rows) - confirmed,
        "flagged_legs": sum(1 for g in route if g["flag"]),
        "generated_at": now.isoformat(), "generated_ist": iso_ist(now),
        "user": ctx.principal.user_id,
        "role": getattr(ctx.principal.role, "value", str(ctx.principal.role)),
        "purpose": getattr(ctx, "purpose", None) or "",
        "case_id": getattr(ctx, "case_id", None) or "",
        "jurisdiction": "statewide" if scope is None else ", ".join(sorted(scope)) or "none",
        "digest": digest, "report_id": f"TR-{canon}-{digest[:10].upper()}",
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
_CSS = """
@page { size: A4; margin: 14mm 12mm 16mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.45 "Segoe UI", system-ui, -apple-system, sans-serif;
       color: #111; background: #fff; margin: 0; padding: 18px 22px; }
h1 { font-size: 17pt; margin: 0 0 2px; letter-spacing: .01em; }
h2 { font-size: 11.5pt; margin: 18px 0 6px; padding-bottom: 3px;
     border-bottom: 1.5px solid #111; text-transform: uppercase; letter-spacing: .06em; }
.mono { font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; }
.head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start;
        border-bottom: 3px double #111; padding-bottom: 8px; }
.head .plate { font-size: 22pt; font-weight: 700; letter-spacing: .08em;
               border: 2px solid #111; padding: 2px 10px; border-radius: 4px; }
.meta { font-size: 9pt; color: #333; }
.meta b { color: #111; }
.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-top: 10px; }
.kpi { border: 1px solid #999; border-radius: 4px; padding: 6px 8px; }
.kpi .n { font-size: 15pt; font-weight: 700; }
.kpi .l { font-size: 8pt; color: #444; text-transform: uppercase; letter-spacing: .05em; }
.banner { margin-top: 10px; padding: 7px 10px; border-radius: 4px; font-weight: 600;
          border: 1.5px solid #111; }
.banner.listed { background: #fde8e8; border-color: #b00020; color: #6d0012; }
.banner.clear { background: #eef6ee; border-color: #2e7d32; color: #1b4d1f; }
.banner.unchecked { background: #f3f3f3; border-color: #777; color: #333; font-weight: 500; }
table { width: 100%; border-collapse: collapse; font-size: 9pt; }
th, td { border: 1px solid #bbb; padding: 3px 5px; text-align: left; vertical-align: top; }
th { background: #eee; font-size: 8pt; text-transform: uppercase; letter-spacing: .04em; }
tr { page-break-inside: avoid; }
.lead { color: #7a4b00; font-weight: 600; }
.ok { color: #1b5e20; font-weight: 600; }
.bad { color: #b00020; font-weight: 700; }
.map { border: 1px solid #999; border-radius: 4px; width: 100%; height: auto; background: #fafafa; }
.stills { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.still { border: 1px solid #bbb; border-radius: 4px; padding: 4px; page-break-inside: avoid;
         font-size: 7.5pt; }
.still img { width: 100%; display: block; border-radius: 2px; }
.still .cap { margin-top: 3px; }
.note { font-size: 8.5pt; color: #333; }
.sign { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; margin-top: 26px; }
.sign div { border-top: 1px solid #111; padding-top: 4px; font-size: 9pt; }
.foot { margin-top: 18px; font-size: 7.5pt; color: #444; border-top: 1px solid #999;
        padding-top: 6px; word-break: break-all; }
.muted { color: #666; }
.empty { padding: 18px; border: 1.5px dashed #777; border-radius: 4px; text-align: center; }
@media print { body { padding: 0; } .noprint { display: none; } }
"""


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _dur(secs: float | None) -> str:
    if secs is None:
        return "—"
    s = int(round(abs(secs)))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return (f"{h} h {m:02d} min" if h else f"{m} min {s:02d} s" if m else f"{s} s")


def _ist_short(ts: str) -> str:
    """'2026-09-23T19:24:05.123+05:30' -> '23 Sep 2026, 19:24:05 IST'."""
    d = _parse(ts)
    return d.strftime("%d %b %Y, %H:%M:%S IST") if d else (ts or "—")


def _map_svg(rows: list[dict[str, Any]], cams: dict[str, dict[str, Any]]) -> str:
    """A schematic of the stops in order. No tiles: nothing is fetched."""
    stops: list[tuple[str, tuple[float, float]]] = []
    for r in rows:
        ll = _latlon(cams.get(r["camera_id"], {}))
        if ll and (not stops or stops[-1][0] != r["camera_id"]):
            stops.append((r["camera_id"], ll))
    if len(stops) < 1:
        return ""
    lats = [p[1][0] for p in stops]
    lons = [p[1][1] for p in stops]
    lat0 = sum(lats) / len(lats)
    kx = math.cos(math.radians(lat0))
    xs = [lo * kx for lo in lons]
    minx, maxx, miny, maxy = min(xs), max(xs), min(lats), max(lats)
    span = max(maxx - minx, maxy - miny, 1e-4)
    # Height follows the route's shape: a north-south route gets a tall map,
    # an east-west one a short one, and two stops never fill half a page.
    W, pad = 720, 34
    aspect = (maxy - miny) / max(maxx - minx, 1e-9)
    H = int(min(300, max(170, (W - 2 * pad) * min(aspect, 1.0) * 0.55 + 2 * pad)))
    sc = min((W - 2 * pad) / max(maxx - minx, 1e-9), (H - 2 * pad) / max(maxy - miny, 1e-9))
    sc = min(sc, (W - 2 * pad) / span if span else sc)
    ox = (W - (maxx - minx) * sc) / 2
    oy = (H - (maxy - miny) * sc) / 2

    def pt(i: int) -> tuple[float, float]:
        return ox + (xs[i] - minx) * sc, H - (oy + (lats[i] - miny) * sc)

    parts = [f'<svg class="map" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
             f'role="img" aria-label="Schematic route across {len(stops)} stops">',
             '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
             'markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="#333"/></marker></defs>']
    for i in range(1, len(stops)):
        (x1, y1), (x2, y2) = pt(i - 1), pt(i)
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     'stroke="#333" stroke-width="1.6" marker-end="url(#ar)"/>')
    labelled: set[str] = set()
    for i, (cid, _) in enumerate(stops):
        x, y = pt(i)
        first, last = i == 0, i == len(stops) - 1
        fill = "#1b5e20" if first else "#b00020" if last else "#fff"
        txt = "#fff" if (first or last) else "#111"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10" fill="{fill}" stroke="#111" '
                     'stroke-width="1.4"/>'
                     f'<text x="{x:.1f}" y="{y + 3.6:.1f}" font-size="10" font-weight="700" '
                     f'text-anchor="middle" fill="{txt}">{i + 1}</text>')
        if cid not in labelled:
            labelled.add(cid)
            parts.append(f'<text x="{x + 13:.1f}" y="{y - 8:.1f}" font-size="9.5" '
                         f'fill="#222">{_e(cid)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_html(t: dict[str, Any]) -> str:
    rows, cams, stills = t["rows"], t["cameras"], t["stills"]
    wl = t["watchlist"] or {}
    in_force = [e for e in wl.get("entries") or [] if e.get("in_force")]
    if in_force:
        e = in_force[0]
        cat = str(e.get("category", "")).replace("_", " ")
        banner = (f'<div class="banner listed">ON WATCHLIST at {_e(_ist_short(t["generated_ist"]))}'
                  f' — {_e(cat)} · {_e(e.get("priority"))} · {_e(e.get("reason"))}'
                  f' · on the word of {_e(e.get("authority") or e.get("source_system") or "—")}</div>')
    elif wl.get("checked") is False:
        banner = (f'<div class="banner unchecked">Watchlist not checked: '
                  f'{_e(wl.get("reason"))}</div>')
    else:
        banner = (f'<div class="banner clear">Not on any active watchlist at '
                  f'{_e(_ist_short(t["generated_ist"]))}. This is a statement about that '
                  'moment, not a finding about the vehicle.</div>')

    first = rows[0] if rows else None
    last = rows[-1] if rows else None
    n_cams = len({r["camera_id"] for r in rows})
    kpis = [(len(rows), "reads"), (n_cams, "cameras"), (t["confirmed"], "confirmed reads"),
            (t["leads"], "single-frame leads"), (t["flagged_legs"], "legs to check")]
    kpi_html = "".join(f'<div class="kpi"><div class="n">{n}</div><div class="l">{_e(lbl)}</div></div>'
                       for n, lbl in kpis)

    out = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
           f"<title>Vehicle trace {_e(t['plate'])} — {_e(t['report_id'])}</title>",
           f"<style>{_CSS}</style></head><body>",
           '<div class="head"><div>',
           '<div class="meta">SAAKSHYA · Gujarat Police · Vehicle trace report</div>',
           f'<h1>Movement of <span class="mono">{_e(t["plate"])}</span></h1>',
           f'<div class="meta">Report <b class="mono">{_e(t["report_id"])}</b> · generated '
           f'<b>{_e(_ist_short(t["generated_ist"]))}</b> by <b>{_e(t["user"])}</b> '
           f'({_e(t["role"])}) · jurisdiction <b>{_e(t["jurisdiction"])}</b></div>',
           f'<div class="meta">Case <b class="mono">{_e(t["case_id"] or "—")}</b> · purpose '
           f'recorded: <b>{_e(t["purpose"] or "—")}</b></div>',
           f'</div><div class="plate mono">{_e(t["plate"])}</div></div>',
           banner, f'<div class="kpis">{kpi_html}</div>']

    if not rows:
        out.append(f'<h2>Sightings</h2><div class="empty">No read of <b class="mono">'
                   f'{_e(t["plate"])}</b> on any camera in this jurisdiction. That is an '
                   'answer: the vehicle has not passed a camera that reads plates, or was read '
                   'with different characters — search near matches before closing the '
                   'line of enquiry.</div>')
    else:
        out.append(f'<div class="meta" style="margin-top:8px">First read <b>'
                   f'{_e(_ist_short(first["timestamp_ist"]))}</b> at <b>{_e(first["camera_name"])}'
                   f'</b> · last read <b>{_e(_ist_short(last["timestamp_ist"]))}</b> at <b>'
                   f'{_e(last["camera_name"])}</b></div>')
        svg = _map_svg(rows, cams)
        if svg:
            out.append("<h2>Route (schematic, not to road)</h2>" + svg +
                       '<div class="note">Green is the first stop, red the last. Straight '
                       'lines join stops in time order; they are not the road taken.</div>')
        if t["legs"]:
            out.append("<h2>Legs between cameras</h2><table><tr><th>#</th><th>From</th>"
                       "<th>To</th><th>Left</th><th>Arrived</th><th>Straight line</th>"
                       "<th>Elapsed</th><th>Implied speed</th><th>Check</th></tr>")
            for i, g in enumerate(t["legs"], 1):
                km = "—" if g["km"] is None else f"{g['km']:.2f} km"
                kmh = "—" if g["kmh"] is None else f"{g['kmh']:.0f} km/h"
                chk = (f'<span class="bad">{_e(g["flag"])} — possible misread or cloned plate; '
                       'compare the stills</span>' if g["flag"] else '<span class="ok">plausible</span>')
                out.append(f"<tr><td>{i}</td><td class=\"mono\">{_e(g['from'])}</td>"
                           f"<td class=\"mono\">{_e(g['to'])}</td>"
                           f"<td>{_e(_ist_short(g['from_ist']))}</td>"
                           f"<td>{_e(_ist_short(g['to_ist']))}</td><td>{km}</td>"
                           f"<td>{_dur(g['seconds'])}</td><td>{kmh}</td><td>{chk}</td></tr>")
            out.append("</table>")
        out.append("<h2>Every read, oldest first</h2><table><tr><th>#</th><th>Time (IST)</th>"
                   "<th>Camera</th><th>District</th><th>Read</th><th>Confidence</th>"
                   "<th>Frames agreeing</th><th>Standing</th><th>Evidence</th></tr>")
        for i, r in enumerate(rows, 1):
            stand = ('<span class="ok">confirmed</span>' if r["confirmed"] == "yes"
                     else '<span class="lead">lead — verify on the still</span>')
            fmt = "" if r["plate_format_valid"] == "yes" else (
                f'<div class="bad">format: {_e(r["plate_format_note"])}</div>')
            ev = r.get("evidence_id") or ""
            st = stills.get(ev, {})
            ev_cell = (f'<span class="mono">{_e(ev)}</span><div>{_e(st.get("status", ""))}</div>'
                       if ev else '<span class="muted">not sealed</span>')
            out.append(f"<tr><td>{i}</td><td>{_e(_ist_short(r['timestamp_ist']))}</td>"
                       f"<td><b>{_e(r['camera_name'])}</b><div class=\"mono\">{_e(r['camera_id'])}</div></td>"
                       f"<td>{_e(r['district'])}</td><td class=\"mono\">{_e(r['plate'])}{fmt}</td>"
                       f"<td>{_e(r['confidence'] or '—')}</td><td>{_e(r['votes'])}</td>"
                       f"<td>{stand}</td><td>{ev_cell}</td></tr>")
        out.append("</table>")
        shown = [(r, stills[r["evidence_id"]]) for r in rows
                 if r.get("evidence_id") and "uri" in stills.get(r["evidence_id"], {})]
        seen: set[str] = set()
        cards = []
        for r, st in shown:
            if r["evidence_id"] in seen:
                continue
            seen.add(r["evidence_id"])
            cards.append(f'<div class="still"><img src="{st["uri"]}" alt="Sealed still, '
                         f'{_e(r["camera_id"])} at {_e(r["timestamp_ist"])}">'
                         f'<div class="cap"><b>{_e(_ist_short(r["timestamp_ist"]))}</b> · '
                         f'{_e(r["camera_id"])}<br>SHA-256 <span class="mono">'
                         f'{_e(st["sha256"][:24])}…</span> · {_e(st["status"])}</div></div>')
        if cards:
            out.append('<h2>Sealed stills</h2><div class="stills">' + "".join(cards) + "</div>"
                       '<div class="note">Each still is re-hashed when this report is made and '
                       'compared with the digest sealed at capture. A still that no longer '
                       'matches is withheld and named in the table above.</div>')

    out.append('<h2>Reading this report</h2><div class="note">Registration marks are machine '
               'reads. A <b>confirmed</b> read was agreed across two or more frames of one '
               'pass; a <b>lead</b> rests on a single frame and must be checked against the '
               'still before it is relied on. A read is evidence that a vehicle bearing these '
               'characters passed the camera — not of who was driving it. Legs are timed from '
               'camera clocks normalised to IST; implied speeds use straight-line distance and '
               'are therefore the slowest the vehicle could have gone.</div>')
    out.append('<div class="sign"><div>Prepared by (name, rank, belt no.)</div>'
               '<div>Checked by (name, rank) and date</div></div>')
    out.append(f'<div class="foot">Report digest (SHA-256 over every read: observation, time, '
               f'camera, characters, confidence, frames agreeing and evidence id): '
               f'<span class="mono">{_e(t["digest"])}</span>. Regenerating this report for the '
               'same jurisdiction from the same store gives the same digest; a different '
               'digest means the record changed. Each evidence id is bound to its still by '
               'the sealed, hash-chained manifest. Generation is written to the audit '
               'log.</div>')
    out.append("</body></html>")
    return "".join(out)
