# Government Data Access Checklist

**Date:** 1 September 2026, updated 4 September 2026
**Purpose:** state precisely what is needed to run against the organiser's feeds,
and what is missing today.

The software cannot obtain any of this. No credential may be guessed, shared,
reused, or worked around — if an item below is missing, the correct action is to
obtain it through the official channel, not to route around it.

---

## Status summary

| # | Item | Status | Blocking? |
|---|---|---|---|
| 1 | Portal registration | **ISSUED** (stream access key held in process env, not in repo) | No |
| 2 | Portal login credentials | **PARTIAL** — stream email + access password work on RTSP; CDN catalogue still needs a browser session | Catalogue / GIS / HLS only |
| 3 | Sandbox host address | **HAVE** — RTSP `103.250.160.189:8554` | No |
| 4 | Camera catalogue (`/api/ingest`) | **MISSING on RTSP host** (MEASURED 404); CDN `cameras.json` still login-gated | GIS / authoritative ids |
| 5 | RTSP access | **WORKING** with `SENTINEL_GRID_EMAIL` / `SENTINEL_GRID_PASSWORD` | No |
| 6 | HLS fallback URL | CDN session still required; documented `/live/stream/<id>/index.m3u8` on the RTSP host is 404 | No — fallback only |
| 7 | WHEP/WebRTC URL | Host open; same stream credential as RTSP | No — preview only |
| 8 | Network path to RTSP/8554 | **VERIFIED** 4 Sep 2026 | No |
| 9 | Target registration number | Supplied on the day | No |
| 10 | Ground truth for the feeds | **Assume none** | No |
| 11 | Watchlist format | Own representative data permitted | No |
| 12 | Submission upload | **NOT DONE** | **Yes — official last date 15 Sep 2026** |

See `docs/SENTINEL_SANDBOX.md` for the integrator mapping. Do not write the
access password into this repository.

---

## 1–2. Registration and login

**What is needed:** an account on `https://sentinel.gujarat.gov.in`, and the
resulting login.

**Why it blocks everything:** the portal's own FAQ states that camera details,
resources and live feeds are available **after registration**, via the Resources
page. Without it there is no catalogue, no stream, and no submission.

**Note on timing:** registration and submission share the **same deadline —
15 September 2026**. Registering is not a step that can be deferred until the
build is ready.

**Action:** register at the portal. Nobody but the team can do this.

---

## 3–5. Sandbox host, catalogue and RTSP

**What is needed:**

| Item | Form expected | Where it comes from |
|---|---|---|
| Sandbox host | hostname or IP | Resources page, after login |
| Catalogue | `GET http://<host>/api/ingest` | documented in the Integrator's Guide |
| RTSP | `rtsp://<host>:8554/stream/<id>` | catalogue `urls.rtsp` |

**How the system consumes them — no code change required:**

```bash
make government-profile CATALOGUE=http://<host>/api/ingest
make government-run     CATALOGUE=http://<host>/api/ingest
```

The catalogue is treated as the contract. Camera ids, the camera set, codecs,
resolutions and frame rates are all read from it at runtime, and the importer
normalises several plausible JSON shapes so an unexpected field layout is a
mapping change rather than a rewrite.

**If the API requires a bearer token:** pass `--token`, or set it in the
environment. It must not be written into any file in this repository.

---

## 6–7. HLS and WHEP

HLS matters only as a **fallback when RTSP/8554 is blocked** — a realistic
outcome on a corporate or government network. WHEP is browser preview and is not
used for analytics.

**Action if RTSP is blocked:** capture the HLS URL from the catalogue; the
ingest layer already carries all three transports per camera.

---

## 8. Network path

**Unverified and worth checking early**, because it fails silently and late.
From the machine that will run the evaluation:

```bash
curl -s http://<host>/api/ingest | head
```

If port 8554 is unreachable, the fallback is HLS, and that decision is better
made days before the evaluation than during it.

---

## 9. Target registration number

Supplied by the organisers **on the day**. This is why the system contains no
target-specific code and why the end-to-end test selects its target from the
data rather than from a constant — a plate hard-coded anywhere would be both a
correctness bug and a disqualifying one.

---

## 10. Ground truth

**Assume none is provided.** Consequences we have already designed around:

- Accuracy on government feeds can only be reported as **per-camera yield**
  (detections, valid reads, abstentions), not as accuracy against truth.
- Confidence stays an **engineering score**. Calling it a calibrated probability
  requires a labelled held-out set, which without ground truth does not exist.
- A small hand-labelled validation set could be built from the feeds if time
  permits. If it is not built, that is stated rather than papered over.

---

## 11. Watchlist

The challenge explicitly permits participants to create and use their own
representative watchlist. We do that, and every entry records
`source_system: REPRESENTATIVE` so the distinction survives into every alert.

**We hold no credentials for VAHAN, SARATHI, eGujCop, AFIS or NAFIS**, and claim
no integration with any of them. Adapter interfaces exist and raise
`NotImplementedError` naming exactly what would be required:

| Source | Required before implementation |
|---|---|
| VAHAN | authorised API endpoint, service credentials, data-sharing approval, purpose-limitation agreement |
| eGujCop (CCTNS) | SCRB authorisation, CCTNS interface specification, network path |
| SARATHI / AFIS / NAFIS | equivalent authorisation, not yet specified |

---

## 12. Submission

Per the portal, the submission comprises:

- Solution Presentation (PPT/PDF), with the chosen model **and its justification**
- Technical Proposal / High-Level Design
- Own-feed demonstration — **2–3 minute** screen recording, hard cap
- Government-feed demonstration, **plus an output report** of detected
  vehicles/plates with timestamps
- Unlisted YouTube link, or Drive/OneDrive with viewer access enabled
- *Optional:* hosted URL with working test credentials, and a repository link

Mock-ups, animations and concept videos are explicitly not accepted.

---

## What proceeds without any of this

Everything except contact with the real feed. Currently working and measured on
the local replica:

- ingest, tracking, ANPR, observations, persistence
- plate search, camera graph, trajectory, watchlist, alerts, evidence
- the intake and profiling tools above, validated end-to-end against the replica

The moment a host address exists, `make government-profile` characterises the
cameras and `make government-run` ingests them. Nothing in the pipeline needs to
change to accept them.

---

## Rules

1. **No credential enters this repository.** Enforced by a secret scan over
   tracked files *and* full git history, run in `make verify`.
2. **No bypass.** If access is refused, the answer is to obtain authorisation,
   not to find another route.
3. **No fabrication.** The system never invents a feed, a camera, or a result to
   stand in for real data. Where data is absent, output says so.
