"""Camera Link Model — learned transition topology.

Prior art, stated as such: learning inter-camera transition-time distributions
from co-observations is standard in AI City Challenge work (~2019 onward). It is
**N1** on our novelty scale and we do not claim it.

What makes it load-bearing *here* is the estate. Gujarat has no camera
calibration and no surveyed topology across 26 departments, and acquiring either
for 80,000 devices is a multi-year survey programme, not a hackathon task. The
strongest published multi-camera trackers assume bird's-eye-view ground-plane
positions and are therefore unavailable to us. A model that bootstraps itself
from its own observation stream is the only option that scales across this
estate — so the graph carries weight the appearance signal cannot.

That ordering is deliberate and measured. On our corpus a DINOv2 embedding
scored the decoy vehicle *higher* than the target's own other observations. The
graph does not have that failure mode: travel time between two fixed cameras is
a physical fact, and physics does not suffer domain shift.

Two sources, in priority order:

    observed   confident plate co-observations give (from, to, dt) samples
    gis_seed   great-circle distance gives a weak prior before data exists

Observed always wins where it exists. The seed only prevents a cold start.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from saakshya.store import Store, VehicleObservation, now_us

log = logging.getLogger(__name__)

#: Transitions slower than this are not one journey; they are two visits.
MAX_TRANSITION_S = 3600.0
#: A pair needs this many samples before its distribution is trusted for pruning.
MIN_SUPPORT_FOR_PRUNE = 3
#: Assumed plausible road speed for the GIS seed. Deliberately generous: the seed
#: must not exclude a real transition, only rank an unobserved one below observed.
SEED_SPEED_KMH = 45.0
SEED_MIN_S, SEED_MAX_S = 20.0, 2400.0


@dataclass
class Transition:
    from_camera: str
    to_camera: str
    support_count: int = 0
    travel_p05_s: float | None = None
    travel_p50_s: float | None = None
    travel_p95_s: float | None = None
    travel_mean_s: float | None = None
    travel_std_s: float | None = None
    gis_distance_m: float | None = None
    confidence: float = 0.0
    source: str = "observed"

    @property
    def trusted(self) -> bool:
        return self.source == "observed" and self.support_count >= MIN_SUPPORT_FOR_PRUNE

    def feasible(self, dt_s: float) -> bool:
        """Is a journey of this duration physically consistent with this edge?

        Untrusted edges accept anything within the global bound: refusing to
        answer is better than pruning a real transition on three samples.
        """
        if dt_s <= 0 or dt_s > MAX_TRANSITION_S:
            return False
        if not self.trusted or self.travel_p05_s is None:
            return True
        # Tolerance widens the observed window rather than trusting it exactly;
        # traffic is variable and a hard cut discards real journeys.
        lo = self.travel_p05_s * 0.5
        hi = (self.travel_p95_s or self.travel_p50_s or 0.0) * 2.0 + 30.0
        return lo <= dt_s <= hi

    def plausibility(self, dt_s: float) -> float:
        """0..1 score for a journey of this duration. Not a probability."""
        if not self.feasible(dt_s):
            return 0.0
        if not self.trusted or self.travel_p50_s is None:
            return 0.35          # feasible but unevidenced
        p50 = self.travel_p50_s
        spread = max(1.0, (self.travel_p95_s or p50 * 1.5) - (self.travel_p05_s or p50 * 0.5))
        z = abs(dt_s - p50) / spread
        return float(np.clip(math.exp(-z), 0.0, 1.0))

    def explain(self, dt_s: float | None = None) -> str:
        if self.source == "gis_seed":
            d = f"{self.gis_distance_m:.0f} m apart" if self.gis_distance_m else "distance unknown"
            return f"no observed transitions yet; GIS seed ({d})"
        base = (f"{self.support_count} observed transitions, "
                f"typical {self.travel_p50_s:.0f}s "
                f"(p05 {self.travel_p05_s:.0f}s - p95 {self.travel_p95_s:.0f}s)")
        if dt_s is not None:
            base += f"; this journey {dt_s:.0f}s"
            if not self.feasible(dt_s):
                base += " — OUTSIDE the observed envelope"
        return base


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class CameraGraph:
    """In-memory view of the transition model, backed by the store."""

    store: Store
    edges: dict[tuple[str, str], Transition] = field(default_factory=dict)
    cameras: dict[str, dict] = field(default_factory=dict)

    # -- construction ------------------------------------------------------- #
    def load(self) -> CameraGraph:
        self.cameras = {c["camera_id"]: c for c in self.store.list_cameras()}
        self.edges = {}
        for r in self.store.get_transitions():
            t = Transition(
                from_camera=r["from_camera"], to_camera=r["to_camera"],
                support_count=r["support_count"] or 0,
                travel_p05_s=r["travel_p05_s"], travel_p50_s=r["travel_p50_s"],
                travel_p95_s=r["travel_p95_s"], travel_mean_s=r["travel_mean_s"],
                travel_std_s=r["travel_std_s"], gis_distance_m=r["gis_distance_m"],
                confidence=r["confidence"] or 0.0, source=r["source"] or "observed",
            )
            self.edges[(t.from_camera, t.to_camera)] = t
        return self

    def seed_from_gis(self) -> int:
        """Weak prior for every camera pair with coordinates.

        Never overwrites an observed edge. Exists only so the very first query,
        before any data has accumulated, is not answerless.
        """
        cams = {c["camera_id"]: c for c in self.store.list_cameras()
                if c.get("lat") is not None and c.get("lon") is not None}
        written = 0
        for a, ca in cams.items():
            for b, cb in cams.items():
                if a == b or (a, b) in self.edges:
                    continue
                d = haversine_m(ca["lat"], ca["lon"], cb["lat"], cb["lon"])
                est = d / (SEED_SPEED_KMH * 1000 / 3600)
                if est > SEED_MAX_S:
                    continue           # too far apart to be one journey
                est = max(SEED_MIN_S, est)
                t = Transition(a, b, support_count=0, gis_distance_m=d,
                               travel_p05_s=est * 0.4, travel_p50_s=est,
                               travel_p95_s=est * 3.0, confidence=0.15,
                               source="gis_seed")
                self.edges[(a, b)] = t
                self.store.upsert_transition({
                    "from_camera": a, "to_camera": b, "support_count": 0,
                    "travel_p05_s": t.travel_p05_s, "travel_p50_s": t.travel_p50_s,
                    "travel_p95_s": t.travel_p95_s, "gis_distance_m": d,
                    "confidence": 0.15, "source": "gis_seed",
                })
                written += 1
        log.info("seeded %d GIS transitions", written)
        return written

    def learn_from_observations(self, window_s: float = MAX_TRANSITION_S) -> int:
        """Derive transition samples from confident plate co-observations.

        Only plated observations are used as anchors. An unplated observation
        cannot establish that the *same* vehicle moved between two cameras, and
        using appearance for that would build the graph on the signal the graph
        is supposed to protect us from.
        """
        from saakshya.store import SearchFilter

        obs = self.store.search(SearchFilter(limit=200_000))
        by_plate: dict[str, list[VehicleObservation]] = {}
        for o in obs:
            if o.plate:
                by_plate.setdefault(o.plate, []).append(o)

        samples: list[dict] = []
        for plate, group in by_plate.items():
            group.sort(key=lambda o: o.t_norm)
            for i in range(len(group) - 1):
                a, b = group[i], group[i + 1]
                if a.camera_id == b.camera_id:
                    continue
                dt = (b.t_norm - a.t_norm).total_seconds()
                if 0 < dt <= window_s:
                    samples.append({"from_camera": a.camera_id,
                                    "to_camera": b.camera_id, "plate": plate,
                                    "dt_s": dt, "t_norm_us": now_us()})
        if samples:
            self.store.add_transition_samples(samples)
        return self.recompute()

    def recompute(self) -> int:
        """Rebuild every observed edge's distribution from all stored samples.

        Recomputed from raw samples rather than updated incrementally: an
        incremental statistic cannot be audited, and a wrong one is invisible.
        """
        rows = self.store.all_transition_samples()
        grouped: dict[tuple[str, str], list[float]] = {}
        for r in rows:
            grouped.setdefault((r["from_camera"], r["to_camera"]), []).append(r["dt_s"])

        for (a, b), dts in grouped.items():
            arr = np.asarray(sorted(dts), dtype=np.float64)
            t = Transition(
                from_camera=a, to_camera=b, support_count=len(arr),
                travel_p05_s=float(np.percentile(arr, 5)),
                travel_p50_s=float(np.percentile(arr, 50)),
                travel_p95_s=float(np.percentile(arr, 95)),
                travel_mean_s=float(arr.mean()),
                travel_std_s=float(arr.std()) if len(arr) > 1 else 0.0,
                gis_distance_m=self._gis_distance(a, b),
                # Confidence saturates with support; 10 samples is not certainty.
                confidence=float(np.clip(len(arr) / 10.0, 0.05, 0.95)),
                source="observed",
            )
            self.edges[(a, b)] = t
            self.store.upsert_transition({
                "from_camera": a, "to_camera": b, "support_count": t.support_count,
                "travel_p05_s": t.travel_p05_s, "travel_p50_s": t.travel_p50_s,
                "travel_p95_s": t.travel_p95_s, "travel_mean_s": t.travel_mean_s,
                "travel_std_s": t.travel_std_s, "gis_distance_m": t.gis_distance_m,
                "confidence": t.confidence, "source": "observed",
            })
        return len(grouped)

    def _gis_distance(self, a: str, b: str) -> float | None:
        ca, cb = self.cameras.get(a), self.cameras.get(b)
        if not ca or not cb:
            return None
        if ca.get("lat") is None or cb.get("lat") is None:
            return None
        return haversine_m(ca["lat"], ca["lon"], cb["lat"], cb["lon"])

    # -- queries ------------------------------------------------------------ #
    def edge(self, a: str, b: str) -> Transition | None:
        return self.edges.get((a, b))

    def reachable(self, origin: str, t_from: datetime, t_to: datetime
                  ) -> dict[str, Transition]:
        """Cameras a vehicle leaving ``origin`` could plausibly reach in the window.

        This is the prune that protects the appearance stage: candidates outside
        this set are not ranked at all, so a weak embedding can never promote a
        physically impossible observation.
        """
        span = (t_to - t_from).total_seconds()
        out: dict[str, Transition] = {}
        for (a, b), t in self.edges.items():
            if a != origin:
                continue
            if t.feasible(max(1.0, span)) or (t.travel_p05_s or 0) <= span:
                out[b] = t
        return out

    def next_best_cameras(self, origin: str, seen_at: datetime,
                          horizon_s: float = 900.0, limit: int = 10,
                          capability: dict[str, float] | None = None
                          ) -> list[tuple[str, float, str]]:
        """Rank the cameras most worth searching next.

        Turns an investigation from "scan everything" into "scan these, in this
        order, for this reason". At 50 cameras that is a convenience; at 80,000
        it is the difference between a query that returns and one that does not.

        Score combines edge confidence, how well the horizon matches the observed
        travel time, and — when supplied — the camera's measured capability, so
        a camera that cannot support the analytic ranks below one that can.
        """
        ranked: list[tuple[str, float, str]] = []
        for (a, b), t in self.edges.items():
            if a != origin:
                continue
            p = t.plausibility(min(horizon_s, t.travel_p50_s or horizon_s))
            if p <= 0:
                continue
            cap = (capability or {}).get(b, 0.5)
            score = 0.55 * p + 0.25 * t.confidence + 0.20 * cap
            why = t.explain()
            if capability is not None:
                why += f"; camera capability {cap:.2f}"
            ranked.append((b, float(score), why))
        ranked.sort(key=lambda r: -r[1])
        return ranked[:limit]

    def anomalies(self, observations: list[VehicleObservation]
                  ) -> list[dict]:
        """Transitions faster than physically observed.

        Reported as an ambiguity with named alternatives, never as an accusation.
        Cloned plates, OCR errors and clock drift produce the same signature, and
        the system is not in a position to tell them apart.
        """
        out: list[dict] = []
        ordered = sorted(observations, key=lambda o: o.t_norm)
        for i in range(len(ordered) - 1):
            a, b = ordered[i], ordered[i + 1]
            if a.camera_id == b.camera_id:
                continue
            dt = (b.t_norm - a.t_norm).total_seconds()
            e = self.edge(a.camera_id, b.camera_id)
            if e is None or not e.trusted:
                continue
            floor = (e.travel_p05_s or 0) * 0.5
            if dt < floor:
                out.append({
                    "type": "TRAJECTORY_ANOMALY",
                    "from_camera": a.camera_id, "to_camera": b.camera_id,
                    "observed_dt_s": round(dt, 1),
                    "minimum_observed_s": round(e.travel_p05_s or 0, 1),
                    "support_count": e.support_count,
                    "hypotheses": [
                        "OCR error on one of the two reads",
                        "cloned or duplicated registration mark",
                        "camera clock drift or incorrect timestamp",
                    ],
                    "assessment": "AMBIGUOUS — requires operator verification",
                    "explanation": e.explain(dt),
                })
        return out

    def stats(self) -> dict:
        observed = [t for t in self.edges.values() if t.source == "observed"]
        trusted = [t for t in observed if t.trusted]
        return {
            "cameras": len(self.cameras),
            "edges_total": len(self.edges),
            "edges_observed": len(observed),
            "edges_trusted": len(trusted),
            "edges_gis_seed": len(self.edges) - len(observed),
            "total_support": sum(t.support_count for t in observed),
        }
