# Adapter and connector architecture

Model 3 asks for an "adapter/plugin architecture for VMS vendors", a metadata
exchange bus, cross-system event correlation, and extensible connectors. This
document describes what SAAKSHYA federates **today**, the contract a connector
must meet, how a new VMS vendor is added, and — honestly — what is a seam rather
than a finished connector, with the shortest path across each seam.

Every claim below cites the file that backs it. Where something is a placeholder
that deliberately does not pretend to work, it is called out as a seam.

---

## 1. What the platform ingests today

Model 1 is compulsory: both source paths register identity, GIS and governance
there. **Model 2 connects directly** to reachable cameras/NVRs or departmental
systems over RTSP/ONVIF, without a federation middleware layer. **Model 3 uses
VMS federation middleware** between departmental VMS APIs/SDKs and the unified
platform. Transport adapters alone do not prove departmental VMS federation.
The connector contract and DEMO/TEST implementations are in `docs/ADAPTERS.md`;
no live departmental VMS integration is claimed. Selected central analytics
is the Model 4 part of this hybrid (official FAQ Q12–Q23).


The platform is vendor-neutral by construction: nothing above the adapter
boundary knows a camera's transport or its owning system. Five source types are
wired in.

| Source | Transport | Where | Provenance label |
|---|---|---|---|
| Government camera grid (Sentinel sandbox) | RTSP/TCP (AI), WHEP (browser), HLS (dashboards) | `live/grid.py`, `live/credentials.py`, `ingest/stream.py` | `GOVERNMENT` |
| Own / participant feeds and local files | RTSP or a recorded file replayed locally | `command/domain.py` (`GOLDEN_OWN_FEEDS`), `live/snapshot.py` (`local_media_url`) | `OWN_FEED` |
| MediaMTX simulation / archival-replay relay | Sentinel RTSP in → local HLS/WHEP/RTSP/JPEG out | `live/relay.py`, `live/simulation.py` | source-dependent |
| CSV / JSON / API onboarding | not a stream — registry metadata | `api/routes_registry.py` | any |
| Synthetic / evaluation control slots | logical only, never a live feed | `command/domain.py` (`SYNTHETIC_CONTROL`) | `SYNTHETIC_CONTROL` |

Provenance is never inferred from silence. Every camera resolves to one of three
domains — `GOVERNMENT`, `OWN_FEED`, `SYNTHETIC_CONTROL` — through
`command/domain.py::classify_source_domain`: the stored `source_domain` wins, and
where a row has none the camera id pattern decides. The three are never mixed in
a label or a count (`command/domain.py`, module docstring).

A note on the government grid: the documented catalogue endpoint
(`GET /api/ingest`) is not served to participants on this sandbox
(`docs/SENTINEL_SANDBOX.md`), so cameras are discovered by probing the documented
id pattern and onboarded into the registry labelled `source="probe"`. The parser
already accepts the documented catalogue JSON, so making the catalogue
authoritative is configuration, not a rewrite.

The MediaMTX relay is an optional local **video** plane (`live/relay.py`).
Default government viewing uses direct WHEP through authenticated signalling:
CONTROL ROOM up to 30 sessions / OPTIMIZED VIEW at most 12, staggered 400 ms;
the optimized policy prefetches 600 px and releases sessions after 15 s off
screen (`ui/app.js`). These are local policies, not Sentinel limits. Selected
AI workers consume RTSP/TCP separately. Relay configuration and its local cap
are documented in `SENTINEL_SUPPORT_CLARIFICATION.md`. The simulation catalogue is an
archival-replay definition — four looped four-minute clips across the demo fleet
— and says so; it is `NOT_MEASURED` until a real worker attaches
(`live/simulation.py`).

---

## 2. The adapter contract

There are two adapter seams, at two levels, and they are deliberately separate.

### 2a. Camera transport adapters (`ingest/adapters.py`)

Resolve one catalogue entry into a validated stream source. Nothing more — the
stream worker owns decoding, PTS, reconnects and fan-out, so a new transport
never re-implements the reliability layer.

```python
class CameraAdapter(Protocol):
    protocol: str
    def resolve(self, entry: dict[str, object]) -> CameraSource: ...

@dataclass(frozen=True, slots=True)
class CameraSource:
    camera_id: str          # stable identity — the spine of everything downstream
    url: str
    protocol: str
    options: dict[str, str]  # e.g. rtsp_transport=tcp, discovery=onvif, vendor=…
```

Shipped implementations: `RTSPAdapter`, `HLSAdapter`, `WebRTCAdapter`,
`ONVIFAdapter`, `VendorAdapter`, keyed in the `ADAPTERS` registry and fetched by
`adapter_for(protocol)`. Each validates the scheme and **raises `ValueError`
rather than inventing a URL** — `VendorAdapter` refuses any entry that has not
already been resolved to a media URL.

### 2b. VMS / system adapters (`federation/adapters.py`)

The federation seam. A `VMSAdapter` represents an entire departmental system,
not one camera, and "must not pretend to own the VMS" (docstring):

```python
class VMSAdapter(Protocol):
    system_id: str; department: str; vendor: str; protocol: str; provenance: str
    def discover_cameras(self) -> list[dict]: ...
    def get_camera_status(self, camera_id: str) -> dict: ...
    def get_stream_url(self, camera_id: str) -> str | None: ...
    def get_metadata(self, camera_id: str) -> dict: ...
    def subscribe_events(self) -> list[dict]: ...
    def health_check(self) -> VMSHealth: ...
```

`_BaseSystem` provides the default behaviour; `RTSPAdapter`, `ONVIFAdapter` and
`GenericVMSAdapter` wrap the matching transport adapter from §2a for URL
resolution. `demo_connected_systems()` produces the operator "connected systems"
rows shown on the command dashboard (`api/routes_command.py`,
`copilot/tools.py`), each carrying `provenance="DEMO/TEST"` so a demo connector is
never presented as a live government VMS.

### 2c. The frame / metadata a connector must yield

Whatever the transport, once decoded every component consumes exactly one type
(`ingest/frame.py::Frame`):

- **A stable `camera_id`** and per-`(camera, segment)` `segment_id`.
- **`pts_s`** — presentation timestamp in seconds, "ground truth for timing".
  `t_norm` is the projected normalised timeline for cross-camera reasoning;
  `t_ingest` (arrival) is diagnostics only and must never drive motion.
- **`image`** — a BGR24 `HxWx3` array — with `width`, `height`, `codec`.
- **`warmup`** — true while the join is replaying a buffered GOP faster than real
  time; consumers must not open tracks or compute velocity on those frames.

A source that cannot provide real PTS supplies **pre-decoded stills** instead,
through the snapshot/preview path (`live/snapshot.py`, `live/preview.py`); such a
tile is never labelled `LIVE` (`command/domain.py::tile_status`).

Required metadata fields carried into the registry and observations: `camera_id`
(only truly required field), `department`, `district`, `lat`/`lon` with a
`location_basis`/`location_precision`, `vendor`, `vms`, `codec`, and the offered
transport URLs (`store/schema.py::cameras`, `api/routes_registry.py::FIELDS`).

---

## 3. Adding a new VMS vendor

Adding "Vendor X" is bounded, and the reliability layer is never touched.

1. **Transport.** If Vendor X speaks RTSP/HLS/WHEP, reuse the existing adapter.
   If it needs an SDK/API login, write a small client that authenticates and
   returns a resolved media URL plus metadata, then feed that URL through
   `VendorAdapter` (it requires the resolved URL and refuses to guess). Register
   any genuinely new transport in `ADAPTERS` (`ingest/adapters.py`).
2. **System federation.** Implement `VMSAdapter` — usually by subclassing
   `_BaseSystem` (`federation/adapters.py`) — mapping the vendor's inventory API
   onto `discover_cameras`/`get_metadata`, its status API onto
   `get_camera_status`, and its event feed onto `subscribe_events`.
3. **Registration.** Cameras enter the registry via the onboarding endpoints
   (`POST /registry/cameras/import`, `import.csv`) or a discovery pass; the
   connected-system row appears through the `demo_connected_systems()`-style
   listing. There is no central plugin manifest today — a connector is registered
   by being constructed and listed (see the "shortest path" note in §6).
4. **Health and capability, measured not declared.**
   `health_check() -> VMSHealth(system_id, state, cameras, last_sync, detail,
   provenance)` reports the system's reachability. Per-camera transport health is
   the live counter set in `store/schema.py::camera_health`; per-camera
   **capability** (can this camera actually read a plate, and in which time band)
   is measured continuously into `camera_capability` and is `UNKNOWN` until there
   is enough evidence — grades are never fabricated (`registry/models.py`,
   `CapabilityVector`).

The federation layer's own resilience is measured, not asserted:
`command/certify.py::measure_adapters` builds N synthetic systems, kills one and
then 10%, and checks the survivors still answer — per-system isolation, so one
dead VMS never takes the federation down.

---

## 4. The metadata / event bus

Federation exchanges metadata on two cooperating planes.

**Durable plane — the `observations` table.** An observation is the atom of the
whole system: one vehicle (or person) seen once by one camera at one time
(`store/repository.py::VehicleObservation`). Search, trajectory, watchlist and
evidence are all functions over these. Idempotency is structural:
`observations.dedup_key` is `UNIQUE` and inserts upsert-keep-first, so an offline
district replaying its queue "cannot create duplicate observations, and that
property is tested rather than assumed" (`store/schema.py`,
`store/repository.py::add_observations`). District/department are denormalised
onto each row so district-scoped access control is an index hit, not a join.

**Streaming plane — `federation/bus.py`.** An in-process `EventBus`
(topic → FIFO of `FederatedEvent`) with a publish/subscribe contract "the same
one a later NATS/Kafka adapter would implement". `FederatedEvent` is the
operator-facing envelope; `EventBus.from_canonical` and `observation_event` lift
a stored observation into it. Measured in process at ~thousands of events/s
(`command/certify.py::measure_bus`); the production broker is the labelled seam,
not a claim that Kafka has been run here.

**Edge replay — `edge/`.** An edge node keeps working with the uplink down:
"loss of the uplink degrades reporting, never detection" (`edge/node.py`). It
writes observations locally first, enqueues them in a durable
store-and-forward queue (`edge_queue`, `edge_nodes` in `store/schema.py`), and on
reconnect drains to the centre. The queued event carries the **same `dedup_key`**
as its observation, so a replayed batch collapses onto the same central row —
at-least-once delivery with idempotent application, "rather than exactly-once
delivery, which does not exist over an unreliable link" (`store/schema.py`).
Events are acknowledged, never deleted on send, so a lost ack replays instead of
dropping.

---

## 5. Cross-system correlation

Because every source lands as a uniform observation keyed on a stable
`camera_id`, correlation works identically across systems — that is the entire
payoff of federating at the observation layer.

- **Search** (`store/repository.py::search`, `search_plate`): "where has this
  registration mark been", across every camera and department, filtered by
  district/department/time/quality. The report generated by
  `tools/reports/federated_report.py` reads exactly this plane and shows, per
  source domain, the plates seen under **more than one** domain — the vehicles
  federation actually correlated.
- **Trajectory** (`camera_transitions`, `transition_samples` — the Camera Link
  Model): learned inter-camera travel-time distributions that bootstrap with no
  survey, so a route can be reconstructed across cameras from different systems.
- **Watchlist at ingest**: matched on the edge locally (`edge/node.py::match`,
  plate-only by design) and centrally by the alert engine
  (`watchlist/alerts.py`), so a hit fires wherever the vehicle appears.
- **Time honesty**: cross-camera correlation is gated on measured timebase
  agreement (`camera_timebase`, `time_clusters`). Cameras whose clocks are not
  established are **not** correlated, so federation never presents "a journey
  spanning seven weeks" as evidence (`store/schema.py`, camera_timebase notes).

```
                         ┌──────────────────────────────────────────────┐
  SOURCES                │  CONNECTORS / ADAPTERS                         │
                         │                                               │
  Gov RTSP/WHEP/HLS ───► │  ingest/adapters.py                           │
  Own feed / file    ───►│    RTSP · HLS · WebRTC · ONVIF* · Vendor*     │
  MediaMTX relay     ───►│    (resolve entry -> CameraSource)            │
  CSV / API onboard  ───►│  federation/adapters.py                       │
  (Vendor SDK)       ┄┄►?│    VMSAdapter: discover/status/url/meta/health │
                         └───────────────────┬───────────────────────────┘
                                             │ Frame(camera_id, pts_s, image, warmup)
                                             ▼
                               ingest/stream.py  (decode · PTS · reconnect+backoff · fan-out)
                                             │
                    ┌────────────────────────┴───────────────────────────┐
                    ▼                                                      ▼
          observations table  ◄── edge/ store-and-forward ──►     federation/bus.py
          (dedup_key UNIQUE,       (edge_queue, same dedup_key,    EventBus / FederatedEvent
           idempotent replay)       ack-not-delete)                 (Kafka/NATS-shaped seam)
                    │
                    ▼
          CROSS-SYSTEM CORRELATION
          search · trajectory (Camera Link Model) · watchlist · time clustering
                    │
                    ▼
          command dashboard · GIS · investigation · alerts

          * ONVIF discovery and Vendor SDK are seams (see §6);  ┄┄►? = not built.
```

---

## 6. What is NOT built (and the shortest path across each seam)

Called out plainly so the architecture is not read as more than it is.

| Seam | Status today | Shortest path to real |
|---|---|---|
| **Vendor SDK adapters** (Milestone / Genetec / Hikvision, etc.) | `VendorAdapter` accepts a *resolved* media URL and refuses to invent one (`ingest/adapters.py`); `GenericVMSAdapter` wraps it. No SDK client exists. | Write a per-vendor client that logs in and returns `{camera_id, url, metadata}`; pass its URL through `VendorAdapter` and its inventory through a `VMSAdapter`. No change below the adapter boundary. |
| **ONVIF discovery** | `ONVIFAdapter` is an explicit seam: it accepts a media URL from a discovery client and rejects entries that skipped that step (`ingest/adapters.py` docstring). It does **not** do WS-Discovery or device probing. | Add an ONVIF discovery client (e.g. `onvif-zeep`) that performs the device exchange and yields profile media URLs; feed those into the existing `ONVIFAdapter`. |
| **Live `/api/ingest` catalogue** | Parser accepts the documented shape; the sandbox does not serve it, so probe + registry is used (`docs/SENTINEL_SANDBOX.md`). | Configuration: point the loader at a reachable catalogue endpoint. |
| **Message broker (Kafka/NATS)** | In-process `EventBus` only, with the broker-shaped publish/subscribe contract (`federation/bus.py`). | Implement the same `publish`/`subscribe`/`drain` against a broker client; publishers and subscribers are unchanged. |
| **Detached-signature watchlist verification** | `DetachedSignatureVerifier` raises `NotImplementedError` on purpose — "a verifier that returned True would be worse than no verifier" (`edge/node.py`). HMAC and hash-only verifiers ship and are honest about what they prove. | Stand up an issuing authority, key custody, public-key distribution and revocation, then implement the verifier against the existing `BundleVerifier` protocol. |
| **Central plugin manifest / registration** | Connectors are registered by being constructed and listed (`demo_connected_systems`), not through a discovered plugin registry. | Add an entry-point / config-driven loader that instantiates `VMSAdapter`s by name; the adapter contract itself does not change. |
| **Control-plane writes to a source** | Consume-only by policy — nothing publishes to the government gateway (`docs/SENTINEL_SANDBOX.md`, "DON'T publish to the gateway"). | Out of scope by design, not a gap to close. |

---

*The design point of Model 3 here is federation at the observation layer: a
stable camera id, real PTS or an honest still, one idempotent metadata bus, and
provenance carried with every figure — so a new vendor is a connector, not a
rebuild, and a government count is never inflated by own-feed or control data.*
