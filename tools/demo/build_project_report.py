#!/usr/bin/env python3
"""Build the portal's 10-section project report: Markdown answers and a PDF.

    python tools/demo/build_project_report.py

Writes submission/form/FORM_ANSWERS.md and submission/form/SAAKSHYA_Project_Report.pdf.
Every figure below is one already certified in reports/FINAL_SUBMISSION_CERTIFICATION.md.
"""
from __future__ import annotations

import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "submission" / "form"
IMG = ROOT / "docs" / "readme" / "films"

SECTIONS: list[tuple[str, str]] = [
    ("Synopsis / Abstract", """
SAAKSHYA (साक्ष्य, "evidence") is a federated CCTV intelligence and evidence platform for Gujarat Police,
built for the Sentinel Camera Grid challenge as a hybrid of all four reference models, 1 + 2 + 3 + 4, all built.
Model 1 onboards any existing camera into one registry and GIS with measured capability grades. Model 2 views the
government grid directly over RTSP and WebRTC (WHEP). Model 3 federates departmental VMS systems through adapters.
Model 4 runs central AI analytics on the cameras that measurably deserve it; it ran live on the government grid on
28 September 2026 (four deep-inference slots, 4,465 observations, 200 plate reads).

Every vehicle sighting becomes a timestamped, geolocated, hash-chained observation. Officers search by plate,
partial or near-match plate and attributes, follow a vehicle's movement on the map, receive automatic real-time
watchlist alerts, and export sealed evidence. Every search requires a case number and a stated purpose and is
written to a tamper-evident audit log. Video stays at the camera; only about 1.3 kB of metadata per observation
moves, which keeps a statewide rollout to about 80,000 cameras affordable.
"""),
    ("Literature Review", """
City-surveillance programmes (Safe City projects, command-and-control centres) have mostly centralised video from
one vendor's VMS. That model does not fit an estate spread over 26 departments, many vendors and two decades of
hardware: at 2 Mbps per camera, 80,000 cameras need about 160 Gbps and 30 days of storage need about 52 PB.
Federated and edge-first designs keep video at the source and move only events and metadata.

Object detection has moved from two-stage detectors to real-time single-stage and transformer detectors: the YOLO
family (for example YOLOv9, Wang et al., 2024) and RT-DETR (Zhao et al., "DETRs Beat YOLOs on Real-time Object
Detection", CVPR 2024), with RT-DETRv2 improving it further. Multi-object tracking by detection (for example
ByteTrack, Zhang et al., ECCV 2022) associates low- and high-confidence boxes to keep identities through occlusion.

For number plates, open ANPR stacks (for example fast-alpr) pair a plate detector with an OCR model. Indian plates
are hard for generic OCR: mixed formats, two-line plates on two-wheelers, dirt and low resolution. OCR models such
as PaddleOCR's PP-OCR family (Du et al., 2020) can be fine-tuned on Indian plates. Awiros-ANPR-OCR is one such
model, trained on about 558,000 Indian plates. Voting across the frames of one track reduces single-frame misreads.

National systems (CCTNS/ICJS, VAHAN and SARATHI) hold the watchlist and vehicle records that alerts must be checked
against. The Bharatiya Sakshya Adhiniyam 2023 (s.63) sets the certificate requirements for electronic evidence, and
the Digital Personal Data Protection Act 2023 governs personal data. Our design follows these: sealed and hashed
records, a certificate draft that humans sign, purpose-bound and audited access, and no face recognition on
government data.
"""),
    ("Your Approach", """
1. Measure before building. We measured the government grid first: all 30 camera IDs produced RTSP frames in the
   census, 15 were reachable by direct WHEP and 15 needed an H.264 bridge. We also graded each camera's plate-reading
   capability from its own stream.
2. Hybrid of all four models. Model 1 (registry and GIS) is the spine every other part reads from. Model 2 views
   the government grid directly through our authenticated WHEP signalling proxy, with CONTROL ROOM (30 tiles) and
   OPTIMIZED VIEW session policies. Model 3 federates departmental VMS systems through an adapter contract.
   Model 4 is central analytics on selected cameras: four deep-inference slots ranked by measured capability.
3. One analytics pipeline everywhere. The steps are RT-DETRv2 detection of vehicles and people, tracking,
   YOLOv9 plate detection on full-resolution tiles, and Awiros-ANPR-OCR (ported to PyTorch, 6.6 ms per plate
   batched). A plate is published only when the frames of one track agree.
4. Watchlist correlation. Each observation is matched against representative stolen, wanted, missing, blacklisted
   and suspect lists as it is written. Alerts are grouped into one decision per vehicle, prioritised, shown on the
   map, and moved through acknowledge, investigate and resolve with an audit record.
5. Evidence and accountability. Every record is sealed with SHA-256 and chained to the one before; the chain is
   re-verified on demand. Every search needs a case and a purpose. Four authorisation gates check the token, the
   role, the jurisdiction and the purpose.
6. Honest labels. Every number is marked MEASURED, MODELLED, DEMO or DESIGNED. Recorded footage is labelled as
   recorded; the synthetic route corpus is labelled as synthetic.
"""),
    ("Road Map / Flow Diagram", """
The diagram shows the end-to-end workflow (onboard → ingest → analyse → read plates → store → match → alert →
investigate → evidence) and the four-phase rollout: PoC (done), a first district cell, a first region, and
statewide in department waves. Each phase opens only when its measured exit gate passes.
"""),
    ("Tools & Technologies", """
- Languages: Python 3.12, JavaScript, HTML/CSS, SQL, Shell.
- Backend: FastAPI and Uvicorn (REST, OpenAPI), SQLAlchemy.
- Databases: SQLite for the PoC; PostgreSQL + PostGIS for the statewide design.
- Video: PyAV (FFmpeg), MediaMTX (RTSP / WebRTC WHEP gateway), OpenCV.
- AI:
  - PyTorch, ONNX Runtime and Hugging Face Transformers;
  - RT-DETRv2-R18 detector, YOLOv9 licence-plate detector, Awiros-ANPR-OCR (PP-OCRv5 fine-tuned on Indian plates);
  - fast-alpr ONNX OCR and Apple Vision as fallbacks;
  - Gemini 3.5 Flash on Vertex AI for the investigator copilot.
- Maps: OpenStreetMap tiles and the Google Maps JavaScript API.
- Security: bearer tokens, role and jurisdiction gates, purpose binding, SHA-256 hash-chained evidence and audit.
- Quality: pytest (1,582 tests pass), Playwright for recorded demonstrations, a secret scanner, Git and GitHub.
- Statewide design: Kubernetes district cells, NVIDIA Triton, NATS JetStream, Kafka, Ceph object storage, Trino,
  Keycloak and OPA.
"""),
    ("Challenges & Risks", """
- Shared sandbox availability. During the test window only 6–13 of 30 government cameras delivered video at once,
  and from 28 Sep 12:57 IST the grid rejected our credentials (401). We responded with per-camera isolation,
  backoff, preflight gates that refuse to film a stall, and a full-feature film made on footage recorded earlier,
  clearly labelled.
- Plate readability. Most government mounts are graded UNSUITABLE for ANPR by geometry and light; this is a camera
  finding, not a reader failure. Capability grades tell the state where ANPR can work.
- No cross-camera government match. No plate was read on two government cameras, so there is no real
  multi-camera government route. Route logic is shown on a labelled synthetic corpus.
- OCR errors. Of 56 plates published on a 57-second clip, 4 were wrong. The multi-frame vote and the "verify
  before acting" labels contain this risk.
- Evidence limits. A hash proves the bytes are unchanged, not what the image shows; older stills can show a
  different vehicle. The worker now seals the frame each plate was best read from.
- Statewide scale. Kafka, gateway-session, TURN and GPU capacities are assumptions until the Phase 1 gates measure
  them. Missing department metadata (VMS, storage, retention) is itself a rollout risk.
- Privacy and law. We use no face recognition on government data, blur heads in the own-feed and recorded footage, and bind
  every search to a case and purpose (BSA 2023, DPDP Act 2023).
"""),
    ("Possible Outcome", """
- One investigation screen across the state's existing cameras instead of calls to each department: a plate
  entered once returns every sighting with camera, time and place.
- Automatic real-time alerts for stolen, wanted, missing and blacklisted vehicles, grouped so an operator makes one
  decision per vehicle.
- Evidence that stands scrutiny: sealed, hash-chained records with a draft certificate for signature.
- Affordable statewide scale: video stays local and only metadata moves; only inference compute grows with the
  number of cameras analysed.
- A measured map of which cameras can read plates, guiding where to upgrade.
- Accountability: every query attributed, purpose-bound and audited.
"""),
    ("Work Done Till Date", """
- The working platform, with all four models built:
  - registry, GIS and onboarding (form and bulk CSV);
  - the live government video wall;
  - VMS federation adapters;
  - central analytics that ran live on the grid;
  - ANPR, watchlist alerts, search, trajectory, evidence, cases, audit and the Gemini copilot.
- Measured on the government grid:
  - 1,155,325 observations to 24 Sep; persons on all 30 cameras, vehicles on 29;
  - 901 plate reads, and 200 more read live on 28 Sep;
  - the delivered report holds 1,101 reads with UTC and IST timestamps.
- Three films:
  - own feed, 2:43;
  - government grid recorded live, 5:40;
  - every feature from sign-in, 15:04, on recorded government footage (49 beats, 0 failures).
- Indian plate recogniser: 17 of 21 hand-read plates exact, against 5 of 21 for the previous recogniser.
- Statewide design: 40 district cells, 6 regions, a state data centre and DR, with a capacity model. 80,000
  synthetic registry rows were loaded and queried.
- Quality: 1,582 automated tests pass; the secret scan passes on every file and the full history.
"""),
]

SHOTS = [
    ("tour-recorded-wall.jpg", "Government wall: 14 cameras with per-frame AI boxes, labelled RECORDED"),
    ("tour-model4-analytics.jpg", "Model 4 central analytics output across the estate"),
    ("plates-government-gallery.jpg", "Government number-plate reads with confidence and agreeing reads"),
    ("own-feed-detection.jpg", "Own feed: vehicles boxed, plates drawn only when the vote holds"),
    ("tour-alerts.jpg", "Alert queue grouped per vehicle"),
    ("tour-focus-cam06.jpg", "Focused camera with provenance panel"),
    ("tour-evidence-chain.jpg", "Evidence chain verification"),
    ("tour-copilot.jpg", "Gemini copilot, grounded in stored results"),
    ("tour-estate-map-search.jpg", "Estate map with camera search"),
    ("tour-rbac-refused.jpg", "Role separation: administrator search refused"),
]
DIAGRAMS = [("roadmap-flow.jpg", "End-to-end flow and road map"),
            ("hld-logical.jpg", "Logical architecture: Models 1 + 2 + 3 + 4, all built"),
            ("hld-statewide.jpg", "Statewide target architecture (~80,000 cameras)")]


def markdown() -> str:
    out = ["# SAAKSHYA — project report answers\n",
           "Copy each section into the portal. Images are in `submission/form/`.\n"]
    for i, (head, body) in enumerate(SECTIONS, 1):
        out.append(f"## {i}. {head}\n\n{body.strip()}\n")
        if head.startswith("Road Map"):
            out.append("Image: `submission/form/roadmap_flow_diagram.png`\n")
    out.append("## 9. Solution Screenshots\n\n" + "\n".join(
        f"- `docs/readme/films/{f}`: {c}" for f, c in SHOTS) + "\n")
    out.append("## 10. Project Report (PDF)\n\n`submission/form/SAAKSHYA_Project_Report.pdf`\n")
    return "\n".join(out)


def para_html(body: str) -> str:
    blocks, out = [b for b in body.strip().split("\n\n")], []
    for b in blocks:
        lines = b.split("\n")
        if all(ln.lstrip().startswith(("- ", "1.", "2.", "3.", "4.", "5.", "6.")) or ln.startswith("   ")
               for ln in lines):
            items, cur = [], ""
            for ln in lines:
                if ln.lstrip().startswith(("- ",)) or ln[:2].rstrip(".").isdigit():
                    if cur:
                        items.append(cur)
                    cur = ln.lstrip()[2:].lstrip(" .")
                else:
                    cur += " " + ln.strip()
            items.append(cur)
            out.append("<ul>" + "".join(f"<li>{html.escape(t)}</li>" for t in items) + "</ul>")
        else:
            out.append(f"<p>{html.escape(' '.join(ln.strip() for ln in lines))}</p>")
    return "".join(out)


def report_html() -> str:
    fig = lambda f, c: (f'<figure><img src="{(IMG / f).as_uri()}"><figcaption>{html.escape(c)}</figcaption></figure>')
    parts = ["""<!doctype html><meta charset="utf-8"><style>
@page { size: A4; margin: 16mm 14mm; }
body { font: 10.5pt/1.5 -apple-system, Helvetica, Arial, sans-serif; color: #1a1f26; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; }
.cover h1 { font-size: 40pt; margin: 0; color: #0e1e34; } .cover .dev { color: #c8912f; font-size: 16pt; }
.cover h2 { font-size: 18pt; font-weight: 600; margin: 8mm 0 2mm; } .cover p { color: #5f6872; }
h2.sec { color: #0e1e34; border-bottom: 2px solid #c8912f; padding-bottom: 2mm; margin-top: 8mm; page-break-after: avoid; }
figure { margin: 4mm 0; page-break-inside: avoid; } img { width: 100%; border: 1px solid #d8dde3; }
figcaption { font-size: 9pt; color: #5f6872; margin-top: 1mm; } li { margin: 1mm 0; }
.pb { page-break-before: always; } .kpis { display: flex; gap: 6mm; margin: 6mm 0; }
.kpis div { flex: 1; border-top: 3px solid #c8912f; padding-top: 2mm; } .kpis b { font-size: 20pt; display: block; color: #0e1e34; }
</style>
<div class="cover"><h1>SAAKSHYA</h1><div class="dev">साक्ष्य · evidence</div>
<h2>Federated CCTV Intelligence and Evidence Fabric</h2>
<p>Project report · Gujarat Police Innovation Challenge 2026 · Sentinel Camera Grid<br>DAU (DA-IICT) · 28 September 2026</p>
<div class="kpis"><div><b>1+2+3+4</b>all four models built</div><div><b>1,155,325</b>government observations</div>
<div><b>1,101</b>plate reads delivered</div><div><b>1,582</b>tests passing</div></div>
<p>Figures are labelled MEASURED, MODELLED, DEMO or DESIGNED in the full submission; see
docs/FINAL_SUBMISSION.md and reports/FINAL_SUBMISSION_CERTIFICATION.md in the repository.</p></div>"""]
    for i, (head, body) in enumerate(SECTIONS, 1):
        parts.append(f'<h2 class="sec{" pb" if i > 1 and head.startswith(("Road", "Work")) else ""}">{i}. {html.escape(head)}</h2>')
        parts.append(para_html(body))
        if head.startswith("Road Map"):
            parts += [fig(f, c) for f, c in DIAGRAMS]
    parts.append('<h2 class="sec pb">9. Solution Screenshots</h2>')
    parts += [fig(f, c) for f, c in SHOTS]
    parts.append('<h2 class="sec">10. Project Report</h2><p>This document. Films, deck, HLD, plate reports and '
                 'evidence records are in the repository\'s submission/ folder and the v1.0 release.</p>')
    return "".join(parts)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "FORM_ANSWERS.md").write_text(markdown(), encoding="utf-8")
    page = OUT / "_report.html"
    page.write_text(report_html(), encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(page.as_uri(), wait_until="load")
        pg.pdf(path=str(OUT / "SAAKSHYA_Project_Report.pdf"), format="A4", print_background=True,
               display_header_footer=True, header_template="<span></span>",
               footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#888">'
                               'SAAKSHYA · project report · <span class="pageNumber"></span>/<span class="totalPages"></span></div>',
               margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        b.close()
    page.unlink()
    print(OUT / "SAAKSHYA_Project_Report.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
