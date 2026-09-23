"""Inference backends.

The rest of the application asks for a *task* — detect, ocr, embed — and never
learns whether the work happened on a CPU, a CUDA GPU, or a remote endpoint.
That is the whole point: business logic, confidence maths and event semantics
are written once, and the execution environment is swapped underneath.

Backends implement transport and execution only. Pre/post-processing that
affects *meaning* — resolution normalisation, plate voting, confidence
calibration — lives in the analytics layer, above this interface, so it cannot
drift between profiles.
"""
from __future__ import annotations

import abc
import contextlib
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saakshya.runtime.profile import RuntimeContext, context

log = logging.getLogger("saakshya.runtime.backend")

#: PyTorch's Metal backend keeps a lazily-populated shader cache
#: (`at::native::mps::MetalShaderLibrary`) that is **not thread-safe**. Six
#: camera workers calling MPS operations concurrently corrupted its hash table
#: and the process died with SIGSEGV inside `exec_unary_kernel` — no Python
#: traceback, no error, twenty-two minutes of live government capture lost.
#: It is a race, which is why one camera always worked and eight sometimes did.
#:
#: The GPU is a single serial resource. Concurrent submission from Python
#: threads buys nothing on this device and costs the process, so MPS inference
#: is serialised here — at the one funnel every backend call already passes
#: through, so no call site can forget.
#:
#: CPU and ONNX Runtime are left concurrent: both are thread-safe, and holding
#: this lock for them would throw away real parallelism on a machine with ten
#: cores.
_MPS_LOCK = threading.Lock()
_NULL_LOCK = contextlib.nullcontext()


def _device_lock(device: str) -> Any:
    return _MPS_LOCK if device == "mps" else _NULL_LOCK


#: A deployment on a government network has no route to huggingface.co, and this
#: system is explicitly built to run without one. `from_pretrained` reaches for
#: the hub before falling back to the cache, and when the host can open a socket
#: but nothing answers, that reach does not time out promptly — a tool was
#: observed sitting at 0% CPU for twelve minutes with the model never loaded.
#:
#: Weights are pinned by revision, so the network offers nothing the cache does
#: not already have. Cache first, therefore, and treat the network as a
#: deliberate fallback for a machine that is genuinely fetching a model for the
#: first time. `SAAKSHYA_MODELS_OFFLINE=1` removes the fallback entirely, which
#: is the correct setting for an air-gapped deployment: a missing model should
#: fail immediately and say so, not hang.
def _load_cached_first(loader: Any, hub_id: str, revision: str | None) -> Any:
    try:
        return loader.from_pretrained(hub_id, revision=revision,
                                      local_files_only=True)
    except Exception as cached_miss:
        if os.environ.get("SAAKSHYA_MODELS_OFFLINE", "") not in ("", "0", "false"):
            raise RuntimeError(
                f"{hub_id}@{revision or 'main'} is not in the local cache and "
                "SAAKSHYA_MODELS_OFFLINE is set, so no download was attempted"
            ) from cached_miss
        log.info("%s not cached locally; fetching from the hub", hub_id)
        return loader.from_pretrained(hub_id, revision=revision)


def quiet_transformers() -> None:
    """Silence the per-load banner transformers prints to stdout.

    Loading an RT-DETR checkpoint prints a LOAD REPORT marking `class_embed.*`
    and `bbox_embed.*` as MISSING — "newly initialized ... Consider training on
    your downstream task". It is benign (those names are aliases of tensors the
    checkpoint stores under `model.decoder.*`, and the activation gate's
    WEIGHTS check proves bit-identical binding against the pinned commit), but
    on a console it reads exactly like a detector loading with a random head.

    It is suppressed rather than left to be explained away in the moment, and
    the claim it appears to make is instead *tested*, in
    `saakshya.models.validation._check_weights`. Progress bars go too: a
    process writing eight of them at once is unreadable, and on a non-tty they
    are pure noise.
    """
    try:
        from transformers.utils import logging as hf_logging
    except ImportError:                       # pragma: no cover - no transformers
        return
    hf_logging.set_verbosity_error()
    hf_logging.disable_progress_bar()

    # Setting the library verbosity is not sufficient on its own: the report is
    # emitted by `transformers.utils.loading_report` through a logger of its
    # own, and whether a level set on the parent reaches it depends on when the
    # child logger was created and on what the host application did to logging
    # afterwards. A filter on the emitting logger does not depend on any of
    # that — the record is dropped where it is made.
    quiet = logging.getLogger("transformers.utils.loading_report")
    quiet.setLevel(logging.ERROR)
    if not any(getattr(f, "saakshya_load_report", False) for f in quiet.filters):
        drop = lambda record: False           # noqa: E731 - a filter, not a name
        drop.saakshya_load_report = True      # type: ignore[attr-defined]
        quiet.addFilter(drop)
    quiet.propagate = False

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Detection:
    box: tuple[int, int, int, int]      # xyxy, full-resolution coordinates
    score: float
    label: str = "object"


@dataclass(slots=True)
class OcrResult:
    text: str
    confidence: float


@dataclass
class InferenceStats:
    calls: int = 0
    failures: int = 0
    total_ms: float = 0.0
    last_error: str | None = None

    def record(self, ms: float, ok: bool = True, err: str | None = None) -> None:
        self.calls += 1
        self.total_ms += ms
        if not ok:
            self.failures += 1
            self.last_error = err

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0

    def snapshot(self) -> dict[str, Any]:
        return {"calls": self.calls, "failures": self.failures,
                "mean_ms": round(self.mean_ms, 2), "last_error": self.last_error}


class InferenceBackend(abc.ABC):
    """One execution environment for one loaded model."""

    #: Human-readable, goes into event provenance.
    name: str = "abstract"

    def __init__(self, ctx: RuntimeContext | None = None) -> None:
        self.ctx = ctx or context()
        self.stats = InferenceStats()

    @abc.abstractmethod
    def load(self, record: Any) -> None:
        """Materialise the model. Must be idempotent."""

    @property
    @abc.abstractmethod
    def loaded(self) -> bool: ...

    def detect(self, image: np.ndarray) -> list[Detection]:
        raise NotImplementedError(f"{self.name} does not implement detect")

    def ocr(self, image: np.ndarray) -> OcrResult | None:
        raise NotImplementedError(f"{self.name} does not implement ocr")

    def embed(self, image: np.ndarray) -> np.ndarray:
        raise NotImplementedError(f"{self.name} does not implement embed")

    def describe(self, image: np.ndarray, prompt: str) -> str:
        raise NotImplementedError(f"{self.name} does not implement describe")

    # -- shared instrumentation -------------------------------------------- #
    def _timed(self, fn, *a, **kw):
        t0 = time.perf_counter()
        try:
            with _device_lock(getattr(self, "_device", "cpu")):
                out = fn(*a, **kw)
        except Exception as exc:
            self.stats.record((time.perf_counter() - t0) * 1000, False,
                              f"{type(exc).__name__}: {exc}"[:200])
            raise
        self.stats.record((time.perf_counter() - t0) * 1000, True)
        return out


class FastAlprBackend(InferenceBackend):
    """Plate detection + OCR via the ONNX models measured in the ANPR work.

    Chosen for DEV_CPU and as the CPU fallback everywhere. Both underlying
    models are MIT-licensed and ship as ONNX, so this backend has no torch
    dependency and starts in well under a second.
    """

    name = "fast-alpr/onnx"

    def __init__(self, ctx: RuntimeContext | None = None) -> None:
        super().__init__(ctx)
        self._detector: Any = None
        self._ocr: Any = None
        self._record: Any = None

    def load(self, record: Any) -> None:
        if self._detector is not None:
            return
        from fast_alpr.default_detector import DefaultDetector
        from fast_alpr.default_ocr import DefaultOCR

        self._record = record
        providers = list(self.ctx.providers)
        self._detector = DefaultDetector(
            model_name=record.detector_hub_id,
            conf_thresh=record.detector_conf,
            providers=providers,
        )
        self._ocr = DefaultOCR(hub_ocr_model=record.ocr_hub_id, providers=providers)
        log.info("loaded %s (%s) on %s", record.name, record.version, providers[0])

    @property
    def loaded(self) -> bool:
        return self._detector is not None

    def detect(self, image: np.ndarray) -> list[Detection]:
        def _run() -> list[Detection]:
            out = []
            for d in self._detector.predict(image):
                b = d.bounding_box
                out.append(Detection(box=(int(b.x1), int(b.y1), int(b.x2), int(b.y2)),
                                     score=float(d.confidence), label="plate"))
            return out

        return self._timed(_run)

    def ocr(self, image: np.ndarray) -> OcrResult | None:
        def _run() -> OcrResult | None:
            res = self._ocr.predict(image)
            if not res:
                return None
            if isinstance(res, list):
                text, conf = res[0].text, res[0].confidence
            else:
                text, conf = getattr(res, "text", None), getattr(res, "confidence", None)
            if not text:
                return None
            if isinstance(conf, (list, tuple, np.ndarray)):
                arr = np.asarray(conf, dtype=float)
                conf = float(arr.mean()) if arr.size else 0.0
            return OcrResult(text=str(text), confidence=float(conf or 0.0))

        return self._timed(_run)


class TransformersBackend(InferenceBackend):
    """HF ``transformers`` models — detection and embedding.

    Used on GPU profiles and for CPU evaluation of licence-clean alternatives
    (RT-DETR for vehicles, DINOv2 for appearance). Torch is imported lazily so
    a DEV_CPU run that never touches this backend does not pay for it.
    """

    name = "transformers"

    def __init__(self, ctx: RuntimeContext | None = None) -> None:
        super().__init__(ctx)
        self._model: Any = None
        self._processor: Any = None
        self._record: Any = None
        self._device = "cpu"

    def load(self, record: Any) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoImageProcessor, AutoModel, AutoModelForObjectDetection

        self._record = record
        if self.ctx.is_gpu and torch.cuda.is_available():
            self._device = "cuda"
        elif (self.ctx.hardware.has_mps
              and os.environ.get("SAAKSHYA_FORCE_CPU", "").strip().lower()
              not in {"1", "true", "yes", "on"}):
            # Measured 3.5x over CPU for RT-DETRv2-R18 on this hardware.
            self._device = "mps"
        else:
            self._device = "cpu"
        rev = record.revision
        # Transformers prints a LOAD REPORT naming any parameter it initialised
        # rather than read from the checkpoint. For RT-DETR that is the
        # auxiliary per-decoder-layer heads, which the published checkpoint
        # omits because they exist only for training.
        #
        # This code used to raise verbosity to WARNING here so the report always
        # printed, on the reasoning that it was the diagnostic which caught the
        # CR-006 P0. That reasoning is now obsolete: the activation gate's
        # WEIGHTS check compares the live task head against the checkpoint file
        # at the pinned commit and reports `51/51 bit-identical`. A proof beats
        # a banner — and the banner had a real cost, printing eight copies of
        # "class_embed … MISSING … Consider training on your downstream task"
        # at the start of every run, which reads exactly like a broken detector
        # to anyone who has not been told otherwise.
        #
        # So it is suppressed, and the diagnostic it used to serve is now the
        # WEIGHTS check, which is stronger: it compares tensors rather than
        # asking a reader to interpret a list of key names.
        #
        # An env-var escape hatch was written here to restore the banner on
        # demand and then removed: it could not be shown to work — the report
        # would not print under it in a real run or in isolation — and an
        # unverified switch documented as working is worse than no switch.
        import transformers
        _prev_verbosity = transformers.logging.get_verbosity()
        quiet_transformers()
        from saakshya.models.registry import DETECTION_TASKS
        loader = (AutoModelForObjectDetection if record.task in DETECTION_TASKS
                  else AutoModel)
        self._processor = _load_cached_first(AutoImageProcessor, record.hub_id, rev)
        self._model = _load_cached_first(loader, record.hub_id, rev)
        self._model.to(self._device).eval()
        transformers.logging.set_verbosity(_prev_verbosity)
        log.info("loaded %s@%s on %s", record.hub_id, (rev or "main")[:8], self._device)

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def detect(self, image: np.ndarray) -> list[Detection]:
        def _run() -> list[Detection]:
            import torch

            rgb = np.ascontiguousarray(image[:, :, ::-1])  # torch rejects negative strides
            inputs = self._processor(images=rgb, return_tensors="pt").to(self._device)
            with torch.no_grad():
                outputs = self._model(**inputs)
            h, w = image.shape[:2]
            post = self._processor.post_process_object_detection(
                outputs, target_sizes=torch.tensor([[h, w]]).to(self._device),
                threshold=self._record.detector_conf,
            )[0]
            id2label = getattr(self._model.config, "id2label", {}) or {}
            # One device-to-host copy per tensor. Iterating the tensors and
            # calling .tolist() per box forced a GPU sync for every detection:
            # on MPS that was 175 ms of a 261 ms frame, against 75 ms for the
            # model itself. Measured in tools/bench/detector_device.py.
            scores = post["scores"].tolist()
            labels = post["labels"].tolist()
            boxes = post["boxes"].tolist()
            out = []
            for score, label, box in zip(scores, labels, boxes, strict=False):
                x1, y1, x2, y2 = (int(v) for v in box)
                out.append(Detection(box=(x1, y1, x2, y2), score=float(score),
                                     label=str(id2label.get(int(label), int(label)))))
            return out

        return self._timed(_run)

    def embed(self, image: np.ndarray) -> np.ndarray:
        def _run() -> np.ndarray:
            import torch

            rgb = np.ascontiguousarray(image[:, :, ::-1])  # torch rejects negative strides
            inputs = self._processor(images=rgb, return_tensors="pt").to(self._device)
            with torch.no_grad():
                out = self._model(**inputs)
            vec = (out.pooler_output if getattr(out, "pooler_output", None) is not None
                   else out.last_hidden_state.mean(dim=1))
            v = vec.squeeze(0).float().cpu().numpy()
            n = np.linalg.norm(v)
            return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)

        return self._timed(_run)


class RemoteBackend(InferenceBackend):
    """Optional HTTP backend for cloud evaluation.

    Exists so GPU-tier models can be *benchmarked* without a local GPU. It is
    never on the critical path: the core evaluation must run with no internet
    connection, so this backend is opt-in and always has a local fallback.
    """

    name = "remote/http"

    def __init__(self, endpoint: str, token: str | None = None,
                 ctx: RuntimeContext | None = None, timeout_s: float = 30.0,
                 retries: int = 2) -> None:
        super().__init__(ctx)
        self.endpoint = endpoint.rstrip("/")
        self._token = token
        self.timeout_s = timeout_s
        self.retries = retries
        self._record: Any = None

    def load(self, record: Any) -> None:
        self._record = record

    @property
    def loaded(self) -> bool:
        return self._record is not None

    def _post(self, path: str, image: np.ndarray, extra: dict | None = None) -> dict:
        import base64

        import httpx
        from PIL import Image

        if not self.ctx.allow_remote_inference:
            raise RuntimeError(
                "Remote inference is disabled. Set SAAKSHYA_ALLOW_REMOTE=1 to enable "
                "it for benchmarking; it must never be required for evaluation."
            )
        import io

        buf = io.BytesIO()
        Image.fromarray(image[:, :, ::-1]).save(buf, format="JPEG", quality=90)
        payload = {
            "request_id": str(uuid.uuid4()),
            "model": getattr(self._record, "hub_id", None),
            "image_b64": base64.b64encode(buf.getvalue()).decode(),
            **(extra or {}),
        }
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = httpx.post(f"{self.endpoint}{path}", json=payload,
                               headers=headers, timeout=self.timeout_s)
                r.raise_for_status()
                return r.json()
            except Exception as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 4))
        raise RuntimeError(f"remote inference failed after {self.retries + 1} attempts: {last}")

    def detect(self, image: np.ndarray) -> list[Detection]:
        def _run() -> list[Detection]:
            data = self._post("/inference/detect", image)
            return [Detection(box=tuple(d["box"]), score=float(d["score"]),  # type: ignore[arg-type]
                              label=d.get("label", "object"))
                    for d in data.get("detections", [])]

        return self._timed(_run)

    def ocr(self, image: np.ndarray) -> OcrResult | None:
        def _run() -> OcrResult | None:
            data = self._post("/inference/ocr", image)
            if not data.get("text"):
                return None
            return OcrResult(text=data["text"], confidence=float(data.get("confidence", 0.0)))

        return self._timed(_run)

    def embed(self, image: np.ndarray) -> np.ndarray:
        def _run() -> np.ndarray:
            data = self._post("/inference/embed", image)
            return np.asarray(data["embedding"], dtype=np.float32)

        return self._timed(_run)

    def describe(self, image: np.ndarray, prompt: str) -> str:
        def _run() -> str:
            return self._post("/inference/vlm", image, {"prompt": prompt}).get("text", "")

        return self._timed(_run)


@dataclass
class BackendRegistry:
    """Caches one backend instance per (backend class, model) pair."""

    _cache: dict[str, InferenceBackend] = field(default_factory=dict)

    def get(self, record: Any, ctx: RuntimeContext | None = None) -> InferenceBackend:
        key = f"{record.runtime}:{record.name}:{record.version}"
        if key in self._cache:
            return self._cache[key]
        ctx = ctx or context()
        if record.runtime == "fast-alpr":
            be: InferenceBackend = FastAlprBackend(ctx)
        elif record.runtime == "transformers":
            be = TransformersBackend(ctx)
        elif record.runtime == "remote":
            import os as _os

            be = RemoteBackend(
                endpoint=_os.getenv("SAAKSHYA_INFERENCE_ENDPOINT", "http://localhost:9000"),
                token=_os.getenv("SAAKSHYA_INFERENCE_TOKEN"), ctx=ctx,
            )
        else:
            raise ValueError(f"unknown runtime {record.runtime!r} for {record.name}")
        be.load(record)
        self._cache[key] = be
        return be

    def stats(self) -> dict[str, dict]:
        return {k: v.stats.snapshot() for k, v in self._cache.items()}


BACKENDS = BackendRegistry()
