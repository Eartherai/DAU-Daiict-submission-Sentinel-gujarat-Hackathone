# Production System Benchmark

**Date:** 1 September 2026
**Purpose:** establish what is already commoditised, so we do not claim it.

Sources are TIER 1 (official government / vendor / standards) where marked ▲,
TIER 2 (journalism, analyst, technical blog) where marked ◆. No TIER 3
(community) source is used for any claim in this document.

---

## 1. System-by-system

### Singapore — PolCam / Police Operations Command Centre ▲

| Dimension | Finding |
|---|---|
| Scale | **90,000+ cameras** installed since 2012 in housing estates, neighbourhood centres, hawker centres, car parks, transport linkways. **200,000 planned by mid-2030s.** |
| Video plane | Centralised to POCC |
| Metadata plane | Video analytics for missing persons, suspect tracking, anomalous events |
| ANPR | Present, not the centre of gravity |
| Edge | PolCam 2.0 cameras carry PTZ and 360° FOV with on-device anomaly detection |
| Operational workflow | **Humans still monitor.** Assistant Watch Officers (full-time Police National Servicemen) watch feeds at the POCC |
| Estate character | **Purpose-installed.** Every camera was sited by police, for policing |
| Known limitation for us | Nothing transfers directly: the whole system assumes a homogeneous, purpose-chosen estate |

**What this tells us:** even the most advanced municipal camera programme in the
world keeps humans in the monitoring loop at scale. An architecture that
promises autonomous alerting without human verification is *less* credible than
one that designs for the officer.

### United Kingdom — National ANPR Service ▲

| Dimension | Finding |
|---|---|
| Scale | **~90 million reads per day** from England, Wales, Scotland forces |
| Video plane | **Not centralised.** Only reads move |
| Metadata plane | Central read store; **12-month retention** unless retained under CPIA/RIPA |
| Enrichment | Make, model, colour joined from DVLA |
| Search | Geo-temporal search across up to 12 months |
| Alerting | Live "vehicles of interest" alarming |
| Governance | Home Office national standards; UK GDPR / DPA 2018; purpose limitation; RBAC; audited access |
| Known limitation for us | ANPR-only, purpose-built readers, single national vehicle registry |

**What this tells us:** the metadata-first thesis is **not a hypothesis, it is
the proven national-scale pattern.** We should present it as such and claim no
novelty for it. It also gives us a defensible retention precedent (12 months for
the searchable tier).

### United States — NYPD Domain Awareness System ◆

Federated fusion of cameras, licence-plate readers, sensors and records into one
analyst-facing platform. Relevant as an *operational workflow* precedent
(analyst-centric, case-centric) rather than an architecture we can copy: the
legal framework and the procurement model do not transfer to India.

### Commercial — Genetec, Motorola, Axon, Milestone ▲/◆

| Vendor | Capability that matters to us |
|---|---|
| **Genetec AutoVu Cloudrunner** | Vehicle-centric investigation using colour, type and behaviour **with partial or absent plate**; direction filters; 30-day plate activity insights; heatmaps |
| **Axon Fusus** | Federation of third-party and private cameras; locate a vehicle "whether it's a full license plate or a unique attribute" |
| **Motorola CommandCentral / Vigilant** | Plate-read aggregation, hotlists, alerting |
| **Milestone XProtect** | Federation, RBAC, evidence export, mature adapter ecosystem |

**All four assume you deployed their readers, or at least cameras chosen for the
task.** That assumption is precisely what does not hold in Gujarat.

### India — Smart Cities ICCC, Safe City, CCTNS/ICJS ▲

ICCC deployments integrate ITMS, ANPR, RLVD and VAHAN. CCTNS/ICJS provide the
records backbone. These are the systems our platform must be *compatible with*,
not compete with.

### Gujarat — TRINETRA, VISWAS, NETRAM, ITMS ▲

| Element | Finding |
|---|---|
| TRINETRA | State-level i3C at Police Bhavan, Gandhinagar; integrates 7,000+ CCTV, 10,000+ body-worn, ~21 drone systems |
| VISWAS | ~7,000 cameras at ~1,200 junctions across 41 locations incl. 34 district HQs, 6 pilgrimage centres, Statue of Unity; 52 municipalities; ~80 interstate entry/exit points. Phase 2 adds ~12,500 cameras across 54 cities |
| NETRAM | **34 district-level command centres** |
| ITMS | ANPR + RLVD in Ahmedabad, Surat, Vadodara, Rajkot; ICCC integrated with VAHAN and SARATHI; automated e-challan |
| Awards | National eGovernance Gold (2022), FICCI SMART Policing (2022), Skoch Gold (2019, 2022) |

**This is the incumbent, and it is competent.** Any proposal that demonstrates
basic ANPR is demonstrating a capability Gujarat Police already operates in four
cities. Our architecture must be positioned as *complementing* TRINETRA/NETRAM —
feeding the existing command hierarchy, not replacing it.

### Dubai — Oyoon ◆

| Dimension | Finding |
|---|---|
| Scale | Ruler of Dubai: **more than 300,000 cameras** (Gulf News; Mashable ME). Earlier programme statements spoke of linking ~10,000 then "thousands" of agency cameras into one command room. |
| Video plane | **Centralised** to a Dubai Police command centre. Government and private cameras under one umbrella. |
| Analytics | Published design includes **face recognition** and behavioural flags. Fines still go through human verification. |
| Known limitation for us | Copying Oyoon is Model 4 plus a biometric pipeline. This build refuses both: 160 Gbps we cannot ingest, and no face recognition by decision. |

### China — Skynet / Sharp Eyes / Safe Cities ◆ / ▲

| Dimension | Finding |
|---|---|
| Official (2018 CSRC reply) | Government departments had deployed **more than 30 million** cameras — "the world's largest image sensor network" in that document. |
| Industry estimates | Skynet ~200 million (2019 reporting); later commercial tallies are higher. **Not treated as official.** |
| Video plane | Centralised public-security video; Sharp Eyes aimed at 100% coverage of key public spaces. |
| Analytics | Face recognition and big-data fusion are the centre of gravity. |
| Known limitation for us | Different legal regime, purpose-installed public-security cameras. Importing that stack would be central video plus biometrics, both rejected here. |

---

## 2. NOT OUR INNOVATION

Anything in this list is commoditised. We may build it; we may not claim it.

| Capability | Production precedent |
|---|---|
| Camera federation across vendors | Milestone, Genetec, Axon Fusus |
| Unified GIS map of cameras | Every ICCC in India |
| ALPR / ANPR | UK NAS (~90M reads/day); Gujarat ITMS |
| Hotlists / vehicles of interest | UK NAS |
| Video wall, multi-camera grid | Every VMS since ~2005 |
| Vehicle search by colour / type | Genetec AutoVu Cloudrunner |
| **Vehicle search with partial or no plate** | **Genetec Cloudrunner; Axon Fusus** |
| Cross-camera vehicle tracking | AI City Challenge; commercial MTMC |
| Camera link / transition models | AI City Challenge literature since ~2019 |
| Adaptive per-camera analytics configuration | Chameleon (MSR), VideoStorm |
| Self-healing stream pipelines | Published GStreamer CCTV practice |
| Cloud VMS | Genetec, Eagle Eye, Verkada |
| Command-centre dashboards | Every ICCC |
| Basic alerting, evidence export, audit logs | All major VMS |
| Natural-language search over video | Every major vendor is shipping one |
| Facial recognition | Mature; legally fraught in India |

**Claiming any of the above as innovation is the fastest way to lose credibility
with a jury that includes DA-IICT and NFSU evaluators.**

---

## 3. What no benchmarked system solves

| Gap | Why it exists |
|---|---|
| **Intelligence from an accidental estate** | Every benchmarked system was built on cameras chosen for the job. Gujarat's 26 departments installed cameras for local supervision. |
| **Per-camera capability as published, auditable metadata** | Vendors tune configuration silently; none publish "this camera cannot do ANPR at night" as an inspectable property. |
| **Confidence discounted by source quality, shown to the user** | Vendors show model confidence. None show source quality alongside it. |
| **Evidence prepared to a national statutory format** | BSA s.63 has been in force in India since 1 July 2024. No VMS generates the certificate. |
| **Calibration-free multi-camera operation at state scale** | The strongest MTMC methods assume BEV/calibrated cameras. 80,000 uncalibrated cameras across 26 departments will not be surveyed. |
