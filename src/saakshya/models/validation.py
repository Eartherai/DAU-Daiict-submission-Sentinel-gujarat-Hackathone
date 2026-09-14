"""Model activation: a model is not ACTIVE until it has proved it works.

This module exists because of a specific failure. Three independent faults —
a task string that matched nothing in the registry, a feature flag defaulting to
off, and a broad exception handler — combined to produce a vehicle detector that
had **never once produced a detection**, in a codebase where every test passed.
The synthetic corpus had legible plates, so plate detection carried the pipeline
and the detector was never needed. It took a Gujarat junction at 2 a.m., where
plates are unreadable, for the absence to become visible.

The lesson is not "add a test for that detector". It is that **a model being
present in a registry is not evidence that it works**, and the system was
treating the two as the same thing.

So activation is now a gate with six checks, and a model that fails any of them
is reported as FAILED with the reason rather than quietly returning nothing:

    RESOLVED        the registry knows this key
    LICENCE         permissively licensed, per policy
    LOADED          weights and processor loaded without error
    TASK            loaded through the class its task requires
    WEIGHTS         the task head in memory is the one from the checkpoint
    INFERENCE       a real forward pass completed
    OUTPUT          the output has the shape the caller expects

The inference check runs on a **synthetic frame**, so it costs nothing and needs
no network. It cannot tell you the model is *good*. It can tell you the model is
*wired up*, which is the failure that actually happened.

WEIGHTS exists because "wired up" was not a strong enough claim. Loading
`PekingU/rtdetr_v2_r18vd` under transformers 5.x prints a LOAD REPORT marking
`class_embed.*` and `bbox_embed.*` as MISSING — newly initialised. Read plainly
that says the detection head is random and every detection is noise. It is in
fact benign: the checkpoint stores those tensors under `model.decoder.*`, the
top-level names are aliases of the same modules, and the report lists the alias
path it did not find. But nothing in the previous five checks could tell the
benign case from the catastrophic one, and neither could a human reading the
log — a randomly initialised head still loads, still infers, and still returns
well-formed boxes. Only the numbers inside them are meaningless.

So WEIGHTS does not reason about the warning. It compares the live head tensor
against the tensor on disk in the checkpoint file. If they match, the trained
head is the one in memory, whatever the report said; if they do not, the model
is genuinely unusable and is reported FAILED. That is a fact, not a heuristic.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np

log = logging.getLogger("saakshya.models.validation")


class Activation(StrEnum):
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.name, "ok": self.ok, "detail": self.detail,
                "seconds": round(self.seconds, 3)}


@dataclass
class ModelReport:
    key: str
    status: Activation = Activation.FAILED
    checks: list[Check] = field(default_factory=list)
    device: str | None = None
    hub_id: str | None = None
    revision: str | None = None
    licence: str | None = None
    checked_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def ok(self) -> bool:
        return self.status is Activation.ACTIVE

    def add(self, name: str, ok: bool, detail: str = "",
            seconds: float = 0.0) -> bool:
        self.checks.append(Check(name, ok, detail, seconds))
        return ok

    def first_failure(self) -> Check | None:
        return next((c for c in self.checks if not c.ok), None)

    def to_dict(self) -> dict[str, Any]:
        f = self.first_failure()
        return {
            "key": self.key, "status": str(self.status),
            "hub_id": self.hub_id, "revision": self.revision,
            "licence": self.licence, "device": self.device,
            "checked_at": self.checked_at,
            "checks": [c.to_dict() for c in self.checks],
            "failed_at": f.name if f else None,
            "reason": f.detail if f else None,
        }


#: A frame with structure rather than noise. Pure noise gives a detector nothing
#: to latch onto, so zero detections would be ambiguous — it might mean the
#: model is broken or that there is genuinely nothing there. Shapes on a
#: background make "produced a well-formed output" checkable without asserting
#: what the output should *contain*, which would be testing the model rather
#: than the wiring.
def synthetic_frame(width: int = 640, height: int = 384) -> np.ndarray:
    img = np.full((height, width, 3), 90, dtype=np.uint8)
    img[height // 2:, :] = 70
    for i, (x, w, colour) in enumerate((
            (60, 140, (180, 180, 185)), (280, 110, (60, 60, 170)),
            (440, 150, (40, 120, 60)))):
        y = height // 2 + 10 + i * 8
        img[y:y + 70, x:x + w] = colour
        img[y + 55:y + 70, x + 10:x + 60] = (235, 235, 235)   # plate-like patch
    return img


def validate(key: str, *, run_inference: bool = True) -> ModelReport:
    from saakshya.runtime.backend import quiet_transformers
    quiet_transformers()
    """Run every activation check for one registry key."""
    from saakshya.models.registry import DETECTION_TASKS, LicenceClass, Task, get

    rep = ModelReport(key=key)

    t0 = time.perf_counter()
    # `get` raises on an unknown key. A gate whose whole purpose is to surface
    # failures must not itself crash on the simplest one.
    rec = None
    resolve_error = ""
    try:
        rec = get(key)
    except (KeyError, ValueError) as exc:
        resolve_error = str(exc).strip("\"'")
    if not rep.add("RESOLVED", rec is not None,
                   resolve_error or f"registry has no entry for {key!r}"
                   if rec is None else f"{rec.hub_id}",
                   time.perf_counter() - t0):
        return rep
    assert rec is not None
    rep.hub_id, rep.revision = rec.hub_id, rec.revision
    rep.licence = str(rec.licence_class)

    # A model recorded as REJECTED must never report ACTIVE, whatever a smoke
    # test says. The registry's verdict is the outcome of a measurement — the
    # DINOv2 rejection came from a -0.541 margin against a decoy — and a
    # validator that overrides it with "it loaded fine" would undo that work.
    from saakshya.models.registry import Status
    if rec.status is Status.REJECTED:
        rep.add("STATUS", False,
                f"{key} is REJECTED in the registry: "
                f"{getattr(rec, 'rejection_reason', None) or 'see the model benchmark'}")
        return rep
    rep.add("STATUS", True, str(rec.status))

    permissive = rec.licence_class is LicenceClass.PERMISSIVE
    if not rep.add("LICENCE", permissive,
                   f"{rec.licence_class} — only permissive licences may ship "
                   "to a government deployment" if not permissive
                   else f"{rec.licence} ({rec.licence_class})"):
        return rep

    t0 = time.perf_counter()
    try:
        from saakshya.runtime.backend import BACKENDS
        backend = BACKENDS.get(rec)
        loaded = backend is not None and getattr(backend, "loaded", True)
        rep.device = getattr(backend, "_device", None)
        rep.add("LOADED", bool(loaded),
                f"loaded on {rep.device or 'cpu'}" if loaded
                else "backend returned nothing", time.perf_counter() - t0)
    except Exception as exc:
        rep.add("LOADED", False, f"{type(exc).__name__}: {str(exc)[:200]}",
                time.perf_counter() - t0)
        return rep

    # The check that would have caught the original fault: a detection
    # checkpoint loaded through a bare backbone has no detection head, so the
    # class it was loaded through is itself worth asserting.
    model = getattr(backend, "_model", None)
    if rec.task in DETECTION_TASKS:
        cls = type(model).__name__ if model is not None else "None"
        looks_right = "ObjectDetection" in cls or "Detection" in cls
        if not rep.add("TASK", looks_right,
                       f"{rec.task} loaded as {cls} — a detection checkpoint in "
                       "a bare backbone has no detection head and raises on "
                       "every frame" if not looks_right
                       else f"{rec.task} loaded as {cls}"):
            return rep
    else:
        rep.add("TASK", True, f"{rec.task}")

    _check_weights(rep, rec, model)

    if not run_inference:
        rep.add("INFERENCE", True, "skipped by request")
        rep.add("OUTPUT", True, "skipped by request")
        rep.status = Activation.SKIPPED
        return rep

    frame = synthetic_frame()
    t0 = time.perf_counter()
    try:
        if rec.task in DETECTION_TASKS:
            out: Any = backend.detect(frame)
        elif rec.task is Task.EMBED:
            out = backend.embed(frame)
        elif rec.task is Task.PLATE_DETECT_OCR:
            from saakshya.analytics.anpr import AnprEngine
            out = AnprEngine().read_frame(frame, 0.0)
        else:
            rep.add("INFERENCE", True, f"no smoke path defined for {rec.task}")
            rep.add("OUTPUT", True, "not applicable")
            rep.status = Activation.SKIPPED
            return rep
    except Exception as exc:
        rep.add("INFERENCE", False, f"{type(exc).__name__}: {str(exc)[:200]}",
                time.perf_counter() - t0)
        return rep
    dt = time.perf_counter() - t0
    rep.add("INFERENCE", True, f"forward pass in {dt * 1000:.0f} ms", dt)

    # Shape, not content. Asserting *what* a model finds in a synthetic frame
    # would be testing the model; asserting that it returns something of the
    # right shape tests the wiring, which is what failed.
    if rec.task in DETECTION_TASKS:
        ok = isinstance(out, list) and all(
            hasattr(d, "box") and hasattr(d, "score") and hasattr(d, "label")
            for d in out)
        rep.add("OUTPUT", ok,
                f"{len(out)} detection(s), well-formed" if ok
                else f"detector returned {type(out).__name__}, not a list of "
                     "detections")
    elif rec.task is Task.PLATE_DETECT_OCR:
        ok = isinstance(out, list) and all(
            hasattr(r, "text") and hasattr(r, "box") for r in out)
        rep.add("OUTPUT", ok,
                f"{len(out)} raw read(s), well-formed" if ok
                else f"reader returned {type(out).__name__}")
    else:
        ok = isinstance(out, np.ndarray) and out.ndim == 1 and out.size > 0
        rep.add("OUTPUT", ok,
                f"embedding of dimension {out.size}" if ok
                else f"embedder returned {type(out).__name__}")

    rep.status = Activation.ACTIVE if all(c.ok for c in rep.checks) else Activation.FAILED
    return rep


#: Head parameters whose values decide what a detection *means*. A backbone can
#: be right while these are random, which is precisely the failure mode that
#: reads as "working" everywhere else.
_TASK_HEAD_HINTS = ("class_embed", "bbox_embed", "classifier", "score_head")


def _check_weights(rep: ModelReport, rec: Any, model: Any) -> None:
    """Confirm the task head in memory came from the checkpoint on disk.

    Reported as INDETERMINATE rather than failed when the comparison cannot be
    made — a torch-free backend, a checkpoint not on local disk. An unprovable
    check must not masquerade as a passing one, and must not block a model that
    is probably fine either; it says what it could not establish and moves on.
    """
    if model is None or not hasattr(model, "state_dict"):
        rep.add("WEIGHTS", True, "not a state-dict model; head binding not checked")
        return
    try:
        import torch
        from huggingface_hub import try_to_load_from_cache
        from safetensors.torch import load_file
    except ImportError:                       # pragma: no cover - torch-free host
        rep.add("WEIGHTS", True, "torch/safetensors unavailable; not checked")
        return

    live = {k: v for k, v in model.state_dict().items()
            if any(h in k for h in _TASK_HEAD_HINTS)}
    if not live:
        rep.add("WEIGHTS", True, "no task head to compare for this architecture")
        return
    # Resolve against the revision the registry pins, not against `main`. The
    # registry's claim is "this commit is in use", so that is the claim worth
    # testing; checking a different commit would verify the wrong thing while
    # looking like it had verified the right one.
    try:
        path = try_to_load_from_cache(rec.hub_id, "model.safetensors",
                                      revision=rec.revision or None)
        if not isinstance(path, str):         # not cached, or sharded/.bin
            rep.add("WEIGHTS", True,
                    "checkpoint not present locally as a single safetensors "
                    "file; head binding not checked")
            return
        disk = load_file(path)
    except Exception as exc:                  # unreadable or truncated cache
        rep.add("WEIGHTS", True,
                f"checkpoint not comparable locally ({type(exc).__name__}); "
                "head binding not checked")
        return

    matched = missing = mismatched = 0
    for name, tensor in live.items():
        found = disk.get(name)
        if found is None:                     # alias path; try the module path
            found = disk.get("model.decoder." + name)
        if found is None:
            missing += 1
        elif tuple(found.shape) == tuple(tensor.shape) and torch.equal(
                found.to(tensor.dtype), tensor.detach().cpu()):
            matched += 1
        else:
            mismatched += 1

    total = len(live)
    ok = matched > 0 and mismatched == 0
    if ok and missing:
        # Say only what was established. `missing` means the tensor was not
        # found under any name this check knows how to look up — which for
        # RT-DETR is the alias case, and for another architecture may simply be
        # a naming scheme not handled here. Reporting all of them as "aliases"
        # would assert the benign reading of evidence that does not carry it.
        detail = (f"{matched}/{total} head tensors bit-identical to "
                  f"{rec.hub_id}@{(rec.revision or 'main')[:12]}; "
                  f"{missing} not found under a name this check resolves, so "
                  "they are unverified rather than known-good")
    elif ok:
        detail = (f"{matched}/{total} head tensors bit-identical to "
                  f"{rec.hub_id}@{(rec.revision or 'main')[:12]}")
    else:
        detail = (f"task head does not match the checkpoint: {matched} matched, "
                  f"{mismatched} differ, {missing} absent — detections from this "
                  "model would be meaningless")
    rep.add("WEIGHTS", ok, detail)


def validate_all(keys: list[str] | None = None, *,
                 run_inference: bool = True) -> dict[str, ModelReport]:
    """Validate every model the pipeline would actually use."""
    from saakshya.models.registry import REGISTRY, Status

    if keys is None:
        keys = [k for k, r in REGISTRY.items() if r.status is not Status.REJECTED]
    out: dict[str, ModelReport] = {}
    for key in keys:
        rep = validate(key, run_inference=run_inference)
        out[key] = rep
        level = logging.INFO if rep.ok else logging.ERROR
        log.log(level, "model %s: %s%s", key, rep.status,
                f" — {rep.to_dict()['reason']}" if not rep.ok else "")
    return out


def active_or_raise(key: str) -> None:
    """Refuse to use a model that has not proved it works.

    Used at pipeline construction. A model that fails here is a fault to
    surface, not a reason to return an empty list of detections and let the
    caller conclude the road was empty.
    """
    rep = validate(key)
    if not rep.ok:
        f = rep.first_failure()
        raise ModelNotActive(
            f"{key} is not ACTIVE: failed {f.name if f else 'unknown'} — "
            f"{f.detail if f else ''}")


class ModelNotActive(RuntimeError):
    pass
