"""Structured logging and metrics.

Written rather than pulled in, for one reason: an offline district node must
work with no metrics backend, no log shipper and no network, and it must still
be able to answer "what happened on this box last Tuesday". A dependency that
assumes a scrape endpoint is reachable is a dependency that fails exactly when
the system is under the conditions it was built for.

The output formats are deliberately standard — JSON lines for logs, Prometheus
text for metrics — so a deployment that *does* have the infrastructure can point
existing tooling at it without a translation layer.

Latency is stored as reservoir samples rather than as pre-bucketed histograms.
At this request volume an exact p99 from the retained window is both cheap and
correct, and it avoids the usual trap of discovering that the bucket boundaries
were chosen before anyone knew what the latencies were.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Correlation identifiers, carried through every log line and every response.
#: `investigation_id` is separate from `request_id` on purpose: an investigation
#: spans many requests, and the question an oversight body asks is about the
#: investigation, not the HTTP call.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
investigation_id_var: ContextVar[str | None] = ContextVar("investigation_id", default=None)
actor_var: ContextVar[str | None] = ContextVar("actor", default=None)


class JsonFormatter(logging.Formatter):
    """One JSON object per line. No multi-line tracebacks in the message field."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, var in (("request_id", request_id_var),
                         ("investigation_id", investigation_id_var),
                         ("actor", actor_var)):
            v = var.get()
            if v:
                payload[key] = v
        for k, v in getattr(record, "extra_fields", {}).items():
            payload[k] = v
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None, *, json_output: bool | None = None
                      ) -> None:
    """Idempotent. Safe to call from the app, a tool, or a test."""
    lvl = (level or os.environ.get("SAAKSHYA_LOG_LEVEL", "INFO")).upper()
    if json_output is None:
        json_output = os.environ.get("SAAKSHYA_LOG_FORMAT", "json").lower() == "json"
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_saakshya", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler._saakshya = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter() if json_output else logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(lvl)


def log_event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    logger.log(level, msg, extra={"extra_fields": fields})


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
@dataclass
class Timing:
    """Latency samples for one operation."""

    name: str
    #: Bounded so a long-running node cannot grow without limit. 4096 samples
    #: is ample for a stable p99 and costs ~32 KB.
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=4096))
    count: int = 0
    total_s: float = 0.0
    errors: int = 0

    def observe(self, seconds: float, *, error: bool = False) -> None:
        self.samples.append(seconds)
        self.count += 1
        self.total_s += seconds
        if error:
            self.errors += 1

    def percentiles(self) -> dict[str, float | int | None]:
        if not self.samples:
            return {"count": self.count, "errors": self.errors,
                    "p50_ms": None, "p95_ms": None, "p99_ms": None, "max_ms": None}
        s = sorted(self.samples)

        def pct(p: float) -> float:
            # Nearest-rank. Exact for the retained window, and it never invents
            # a value that was not measured, which linear interpolation does.
            k = max(0, min(len(s) - 1, round(p / 100.0 * len(s) + 0.5) - 1))
            return s[k] * 1000.0

        return {
            "count": self.count, "errors": self.errors,
            "p50_ms": round(pct(50), 2), "p95_ms": round(pct(95), 2),
            "p99_ms": round(pct(99), 2), "max_ms": round(s[-1] * 1000.0, 2),
            "mean_ms": round(self.total_s / self.count * 1000.0, 2),
        }


class Metrics:
    """Process-local counters and timings. Thread-safe; no I/O on the hot path."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._timings: dict[str, Timing] = {}
        self.started_at = time.time()

    def incr(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = _key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[_key(name, labels)] = value

    def observe(self, name: str, seconds: float, *, error: bool = False,
                **labels: str) -> None:
        key = _key(name, labels)
        with self._lock:
            t = self._timings.get(key)
            if t is None:
                t = self._timings[key] = Timing(key)
            t.observe(seconds, error=error)

    def timer(self, name: str, **labels: str) -> _Timer:
        return _Timer(self, name, labels)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "uptime_s": round(time.time() - self.started_at, 1),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timings": {k: v.percentiles() for k, v in self._timings.items()},
            }

    def prometheus(self) -> str:
        """Prometheus text exposition. Percentiles are exported as gauges — they
        are computed here rather than server-side, which is the honest way to
        expose a windowed quantile without pretending it aggregates across
        instances."""
        out: list[str] = []
        snap = self.snapshot()
        out.append("# TYPE saakshya_uptime_seconds gauge")
        out.append(f"saakshya_uptime_seconds {snap['uptime_s']}")
        for k, v in sorted(snap["counters"].items()):
            name, labels = _split(k)
            out.append(f"# TYPE saakshya_{name} counter")
            out.append(f"saakshya_{name}{labels} {v}")
        for k, v in sorted(snap["gauges"].items()):
            name, labels = _split(k)
            out.append(f"# TYPE saakshya_{name} gauge")
            out.append(f"saakshya_{name}{labels} {v}")
        for k, p in sorted(snap["timings"].items()):
            name, labels = _split(k)
            base = f"saakshya_{name}"
            out.append(f"# TYPE {base}_count counter")
            out.append(f"{base}_count{labels} {p['count']}")
            out.append(f"# TYPE {base}_errors counter")
            out.append(f"{base}_errors{labels} {p['errors']}")
            for q in ("p50", "p95", "p99"):
                if p.get(f"{q}_ms") is not None:
                    lbl = _merge(labels, f'quantile="0.{q[1:]}"')
                    out.append(f"{base}_latency_ms{lbl} {p[f'{q}_ms']}")
        return "\n".join(out) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._timings.clear()


class _Timer:
    def __init__(self, m: Metrics, name: str, labels: dict[str, str]) -> None:
        self.m, self.name, self.labels = m, name, labels
        self.t0 = 0.0
        self.error = False

    def __enter__(self) -> _Timer:
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.m.observe(self.name, time.perf_counter() - self.t0,
                       error=self.error or exc_type is not None, **self.labels)


def _key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{parts}}}"


def _split(key: str) -> tuple[str, str]:
    if "{" not in key:
        return key, ""
    name, rest = key.split("{", 1)
    return name, "{" + rest


def _merge(labels: str, extra: str) -> str:
    if not labels:
        return "{" + extra + "}"
    return labels[:-1] + "," + extra + "}"


#: One registry per process.
METRICS = Metrics()
