# SAAKSHYA — project report answers

Copy each section into the portal. Images are in `submission/form/`.

## 1. Synopsis / Abstract

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

## 2. Literature Review

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

## 3. Your Approach

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

## 4. Road Map / Flow Diagram

The diagram shows the end-to-end workflow (onboard → ingest → analyse → read plates → store → match → alert →
investigate → evidence) and the four-phase rollout: PoC (done), a first district cell, a first region, and
statewide in department waves. Each phase opens only when its measured exit gate passes.

Image: `submission/form/roadmap_flow_diagram.png`

## 5. Tools & Technologies

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

## 6. Challenges & Risks

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

## 7. Possible Outcome

- One investigation screen across the state's existing cameras instead of calls to each department: a plate
  entered once returns every sighting with camera, time and place.
- Automatic real-time alerts for stolen, wanted, missing and blacklisted vehicles, grouped so an operator makes one
  decision per vehicle.
- Evidence that stands scrutiny: sealed, hash-chained records with a draft certificate for signature.
- Affordable statewide scale: video stays local and only metadata moves; only inference compute grows with the
  number of cameras analysed.
- A measured map of which cameras can read plates, guiding where to upgrade.
- Accountability: every query attributed, purpose-bound and audited.

## 8. Work Done Till Date

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

## 9. Solution Screenshots

- `docs/readme/films/tour-recorded-wall.jpg`: Government wall: 14 cameras with per-frame AI boxes, labelled RECORDED
- `docs/readme/films/tour-model4-analytics.jpg`: Model 4 central analytics output across the estate
- `docs/readme/films/plates-government-gallery.jpg`: Government number-plate reads with confidence and agreeing reads
- `docs/readme/films/own-feed-detection.jpg`: Own feed: vehicles boxed, plates drawn only when the vote holds
- `docs/readme/films/tour-alerts.jpg`: Alert queue grouped per vehicle
- `docs/readme/films/tour-focus-cam06.jpg`: Focused camera with provenance panel
- `docs/readme/films/tour-evidence-chain.jpg`: Evidence chain verification
- `docs/readme/films/tour-copilot.jpg`: Gemini copilot, grounded in stored results
- `docs/readme/films/tour-estate-map-search.jpg`: Estate map with camera search
- `docs/readme/films/tour-rbac-refused.jpg`: Role separation: administrator search refused

## 10. Project Report (PDF)

`submission/form/SAAKSHYA_Project_Report.pdf`
