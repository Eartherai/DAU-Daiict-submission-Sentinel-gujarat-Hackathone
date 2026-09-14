"""Versioned model registry.

Every model the system may load is declared here with its licence, exact
revision, hardware requirements and approval status. Nothing is loaded that is
not in this table, and **nothing is swapped silently** — the selected record's
name and version are written into the provenance of every event it produces, so
an investigator can always answer "what produced this result?".

Two fields carry governance rather than engineering meaning:

``approved_for_demo``       cleared for the hackathon submission and evaluation
``approved_for_production``  cleared for a government deployment

They differ. A model can be fine for a demo and unacceptable for production —
usually because of licence terms, or because we have not measured it on real
footage. Nothing here is approved for production on the strength of a synthetic
corpus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Task(StrEnum):
    PLATE_DETECT_OCR = "plate_detect_ocr"   # combined pipeline
    PLATE_DETECT = "plate_detect"
    OCR = "ocr"
    VEHICLE_DETECT = "vehicle_detect"
    EMBED = "embed"
    VLM = "vlm"


#: Tasks whose models need an object-detection head. Declared here, beside the
#: enumeration, so no other module has to compare against a string literal —
#: `record.task == "detect"` silently loaded a detection checkpoint into a bare
#: backbone for every vehicle detector in the registry, because the task is
#: spelled `vehicle_detect`. Most weights initialised at random, the output had
#: no `logits`, and the caller reported "no vehicles".
DETECTION_TASKS: frozenset[str] = frozenset({
    Task.VEHICLE_DETECT, Task.PLATE_DETECT,
})


class LicenceClass(StrEnum):
    PERMISSIVE = "permissive"          # MIT / Apache-2.0 / BSD
    COPYLEFT_STRONG = "copyleft_strong"  # AGPL / GPL — rejected for this build
    RESEARCH_ONLY = "research_only"
    UNCLEAR = "unclear"


class Status(StrEnum):
    ACTIVE = "active"
    CANDIDATE = "candidate"       # in the registry to be benchmarked
    REJECTED = "rejected"         # kept deliberately, with the reason


@dataclass(frozen=True)
class ModelRecord:
    name: str
    version: str
    task: Task

    #: Hugging Face repo id, where applicable.
    hub_id: str | None = None
    #: Exact commit. Pinning a revision is what makes a result reproducible.
    revision: str | None = None
    #: For composite runtimes (fast-alpr) that need two hub ids.
    detector_hub_id: str | None = None
    ocr_hub_id: str | None = None

    runtime: str = "fast-alpr"     # fast-alpr | transformers | remote
    #: Detector operating point. Belongs to the model, not the caller: the
    #: measured confidence distributions differ sharply between checkpoints
    #: (yolo-v9-t-640 peaks ~0.85 where yolo-v9-s-608 peaks ~0.35 on the same
    #: frames), so a single global threshold would be wrong for one of them.
    detector_conf: float = 0.40
    input_size: str | None = None
    precision: str = "fp32"
    params_m: float | None = None
    size_mb: float | None = None

    licence: str = "unknown"
    licence_class: LicenceClass = LicenceClass.UNCLEAR
    weights_source: str | None = None

    requires_gpu: bool = False
    min_vram_mb: int = 0
    #: Soft target used by the router when choosing under a latency budget.
    latency_budget_ms: float | None = None

    #: Only ever a *measured* number from our own harness, or None.
    measured_latency_ms: float | None = None
    #: Publisher-reported figure. Always attributed, never presented as ours.
    reported_benchmark: str | None = None

    status: Status = Status.CANDIDATE
    approved_for_demo: bool = False
    approved_for_production: bool = False
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def licence_ok(self) -> bool:
        return self.licence_class is LicenceClass.PERMISSIVE

    def provenance(self) -> dict[str, str | None]:
        """What gets embedded in an event's model_versions."""
        return {
            "model": self.key,
            "task": str(self.task),
            "hub_id": self.hub_id or self.detector_hub_id,
            "revision": (self.revision or "")[:12] or None,
            "runtime": self.runtime,
            "precision": self.precision,
        }


# --------------------------------------------------------------------------- #
# The registry.
#
# Revisions are the exact commit SHAs read from the Hugging Face API on
# 2026-09-01. Licences are as declared by the publisher on that date.
# --------------------------------------------------------------------------- #
REGISTRY: dict[str, ModelRecord] = {}


def register(rec: ModelRecord) -> ModelRecord:
    if rec.key in REGISTRY:
        raise ValueError(f"duplicate model record {rec.key}")
    REGISTRY[rec.key] = rec
    return rec


# --- ANPR: the measured, working pipeline ---------------------------------- #
ANPR_CPU = register(ModelRecord(
    name="anpr-onnx-cpu", version="1.0.0", task=Task.PLATE_DETECT_OCR,
    runtime="fast-alpr",
    detector_hub_id="yolo-v9-t-640-license-plate-end2end",
    ocr_hub_id="cct-s-v2-global-model",
    detector_conf=0.40,
    input_size="640x640 (detect) / 64x128 (ocr)", precision="fp32",
    size_mb=8.2,
    licence="MIT", licence_class=LicenceClass.PERMISSIVE,
    weights_source="open-image-models + fast-plate-ocr (MIT)",
    requires_gpu=False, latency_budget_ms=120.0, measured_latency_ms=69.2,
    reported_benchmark=None,
    status=Status.ACTIVE, approved_for_demo=True, approved_for_production=False,
    notes=(
        "Measured pairing. yolo-v9-t-640 beat yolo-v9-s-608 (0.83-0.86 vs "
        "0.30-0.44 detector confidence) on the LOCAL SYNTHETIC CORPUS. "
        "cct-s-v2-global has max_plate_slots=10, which is required for a "
        "10-character Indian mark; the fast-alpr default "
        "(global-plates-mobile-vit-v2) has 9 slots and structurally truncates. "
        "Not production-approved: never measured on real Indian CCTV footage."
    ),
    tags=("anpr", "cpu", "default"),
))

ANPR_DEFAULT_REJECTED = register(ModelRecord(
    name="anpr-onnx-fastalpr-default", version="0.0.0", task=Task.PLATE_DETECT_OCR,
    runtime="fast-alpr",
    detector_hub_id="yolo-v9-t-384-license-plate-end2end",
    ocr_hub_id="global-plates-mobile-vit-v2-model",
    licence="MIT", licence_class=LicenceClass.PERMISSIVE,
    requires_gpu=False,
    status=Status.REJECTED, approved_for_demo=False, approved_for_production=False,
    notes=(
        "REJECTED. This is what fast-alpr uses if you accept its defaults. "
        "The OCR model has max_plate_slots=9 and therefore cannot represent a "
        "10-character Indian registration mark: it returns confident "
        "truncations such as 'GJ05AB1' for 'GJ05AB1234'. Kept in the registry "
        "so the rejection is documented rather than forgotten."
    ),
    tags=("anpr", "rejected"),
))

# --- Plate detection alternatives (candidates, to be benchmarked) ----------- #
PLATE_RTDETR = register(ModelRecord(
    name="plate-rtdetrv2", version="0.1.0", task=Task.PLATE_DETECT,
    hub_id="justjuu/rtdetr-v2-license-plate-detection",
    revision="0ca7598f5864", runtime="transformers",
    input_size="640x640", size_mb=171.5,
    licence="Apache-2.0", licence_class=LicenceClass.PERMISSIVE,
    weights_source="huggingface.co/justjuu/rtdetr-v2-license-plate-detection",
    requires_gpu=False, latency_budget_ms=400.0,
    status=Status.CANDIDATE, approved_for_demo=False,
    notes="Licence-clean transformer alternative to the AGPL YOLO plate detectors. "
          "Unbenchmarked by us.",
    tags=("plate", "candidate"),
))

PLATE_YOLO11_REJECTED = register(ModelRecord(
    name="plate-yolov11-morsetech", version="0.0.0", task=Task.PLATE_DETECT,
    hub_id="morsetechlab/yolov11-license-plate-detection",
    revision="251a30d7daed", runtime="transformers",
    licence="AGPL-3.0", licence_class=LicenceClass.COPYLEFT_STRONG,
    status=Status.REJECTED, approved_for_demo=False, approved_for_production=False,
    notes=(
        "REJECTED on licence. Most-downloaded plate detector on the Hub "
        "(68k downloads) and therefore the one a rushed team reaches for. "
        "AGPL-3.0: a network-served government platform would inherit an "
        "obligation over the larger work."
    ),
    tags=("plate", "rejected", "agpl"),
))

# --- Indian-specific OCR ---------------------------------------------------- #
OCR_AWIROS_INDIA = register(ModelRecord(
    name="ocr-awiros-india", version="0.1.0", task=Task.OCR,
    hub_id="Awiros/anpr-ocr", revision="eadbc5ae4faa", runtime="transformers",
    input_size="48x320", size_mb=149.4,
    licence="Apache-2.0", licence_class=LicenceClass.PERMISSIVE,
    weights_source="huggingface.co/Awiros/anpr-ocr",
    requires_gpu=False, latency_budget_ms=60.0,
    reported_benchmark="publisher reports 98.42% on Indian plates "
                       "(98.83% single-row, 96.91% dual-row); not verified by us",
    status=Status.CANDIDATE, approved_for_demo=False,
    notes=(
        "The only India-specific plate OCR found on the Hub with a permissive "
        "licence. PP-OCRv5 architecture — needs PaddlePaddle or an ONNX export, "
        "so it is a candidate rather than a drop-in. Highest-value model to "
        "evaluate: handles dual-row plates, which the generic models do not."
        "\n\n"
        "DOES NOT LOAD through transformers as registered. `make models-validate` "
        "reports: no image processor at Awiros/anpr-ocr — the repository ships "
        "PaddleOCR artefacts, not a transformers-compatible processor. Adopting "
        "it means writing a PaddleOCR or ONNX runtime adapter first, which is "
        "real work rather than a configuration change. Kept as a candidate with "
        "the blocker recorded, because it remains the most valuable OCR "
        "candidate for Indian dual-row plates."
    ),
    tags=("ocr", "india", "candidate", "high-value", "adapter-required"),
))

# --- Vehicle detection ------------------------------------------------------ #
VEHICLE_RTDETR_R18 = register(ModelRecord(
    name="vehicle-rtdetrv2-r18", version="0.1.0", task=Task.VEHICLE_DETECT,
    hub_id="PekingU/rtdetr_v2_r18vd", revision="5650961749fa",
    runtime="transformers", input_size="640x640", size_mb=81.0,
    licence="Apache-2.0", licence_class=LicenceClass.PERMISSIVE,
    weights_source="huggingface.co/PekingU/rtdetr_v2_r18vd",
    requires_gpu=False, latency_budget_ms=500.0,
    reported_benchmark="COCO-pretrained; publisher figures not verified by us",
    status=Status.CANDIDATE, approved_for_demo=False,
    notes=(
        "Primary vehicle-detector candidate. Apache-2.0 and natively supported "
        "by transformers, so it avoids the AGPL problem that YOLO brings. "
        "COCO classes give car/motorcycle/bus/truck directly."
    ),
    tags=("vehicle", "detector", "candidate"),
))

VEHICLE_RFDETR = register(ModelRecord(
    name="vehicle-rfdetr-base", version="0.1.0", task=Task.VEHICLE_DETECT,
    hub_id="Roboflow/rf-detr-base", revision="7b95b089788e",
    runtime="transformers", input_size="560x560", size_mb=129.0,
    licence="Apache-2.0", licence_class=LicenceClass.PERMISSIVE,
    requires_gpu=False, latency_budget_ms=700.0,
    status=Status.CANDIDATE, approved_for_demo=False,
    notes="Alternative Apache-2.0 detector. Benchmark against RT-DETRv2-R18 "
          "before choosing; larger, so likely GPU-tier only.",
    tags=("vehicle", "detector", "candidate"),
))

# --- Appearance embedding (vehicle Re-ID) ----------------------------------- #
EMBED_DINOV2 = register(ModelRecord(
    name="embed-dinov2-base", version="0.1.0", task=Task.EMBED,
    hub_id="facebook/dinov2-base", revision="f9e44c814b77",
    runtime="transformers", input_size="224x224", size_mb=346.0,
    licence="Apache-2.0", licence_class=LicenceClass.PERMISSIVE,
    weights_source="huggingface.co/facebook/dinov2-base",
    requires_gpu=False, latency_budget_ms=800.0,
    measured_latency_ms=34.0,
    status=Status.REJECTED, approved_for_demo=False, approved_for_production=False,
    notes=(
        "MEASURED AND REJECTED for identity use on LOCAL SYNTHETIC CORPUS "
        "(2026-09-01, DEV_CPU/MPS). On ground-truth vehicle crops it did not "
        "separate vehicles: same vehicle across cameras scored 0.400 cosine "
        "(min) while different vehicles scored 0.941 (max) - a margin of "
        "-0.541. It ranked the decoy white car at 0.941 against the target "
        "while scoring the target against itself at 0.412, i.e. it encoded "
        "scene and illumination rather than vehicle identity. Per-crop "
        "illumination normalisation made it worse (-0.581), so this is not a "
        "preprocessing fault. Classical colour attributes scored 7/8 on the "
        "same crops and are shipped instead. "
        "NOT a general claim about DINOv2: our synthetic vehicles are crude "
        "coloured shapes with little texture. MUST be re-measured on "
        "government footage before this verdict is carried forward."
    ),
    tags=("embed", "reid", "measured", "rejected-on-corpus"),
))

EMBED_VEHICLE_SIGLIP2 = register(ModelRecord(
    name="embed-vehicle-siglip2", version="0.1.0", task=Task.EMBED,
    hub_id="occurra/vehicle_reid_siglip2_naflex_512d", revision="857c23afff76",
    runtime="transformers", input_size="512d output", size_mb=377.7,
    licence="Apache-2.0", licence_class=LicenceClass.PERMISSIVE,
    requires_gpu=False, latency_budget_ms=900.0,
    status=Status.CANDIDATE, approved_for_demo=False,
    notes=(
        "Task-specific vehicle Re-ID candidate, ships ONNX. Zero downloads and "
        "no published evaluation, so it is treated as unproven: only adopt if "
        "our own harness shows it beats the DINOv2 baseline on Recall@K."
        "\n\n"
        "DOES NOT LOAD through transformers as registered. `make models-validate` "
        "reports: no image processor at the repository — it ships ONNX weights "
        "without a transformers processor config, so it needs an ONNX Runtime "
        "adapter with hand-written preprocessing. Kept as a candidate with the "
        "blocker recorded rather than quietly removed: the DINOv2 baseline was "
        "measured and rejected, so a working vehicle embedding is still an open "
        "question, and this is one of the few permissively licensed answers."
    ),
    tags=("embed", "reid", "candidate", "unproven", "adapter-required"),
))

# --- Forensic VLM (tier 3 only) --------------------------------------------- #
VLM_QWEN3_4B = register(ModelRecord(
    name="vlm-qwen3-vl-4b", version="0.1.0", task=Task.VLM,
    hub_id="Qwen/Qwen3-VL-4B-Instruct", revision="ebb281ec70b0",
    runtime="transformers", size_mb=8887.0, precision="bf16",
    licence="Apache-2.0", licence_class=LicenceClass.PERMISSIVE,
    requires_gpu=True, min_vram_mb=12000, latency_budget_ms=5000.0,
    status=Status.CANDIDATE, approved_for_demo=False,
    notes=(
        "Tier-3 forensic description only, never a detector and never a "
        "decision-maker. Requires GPU; unavailable on DEV_CPU by design. Its "
        "output is treated as untrusted data, never as instruction."
    ),
    tags=("vlm", "tier3", "gpu-only"),
))


def get(key: str) -> ModelRecord:
    if key not in REGISTRY:
        raise KeyError(f"no model {key!r} in registry")
    return REGISTRY[key]


def by_task(task: Task, *, only_approved: bool = False) -> list[ModelRecord]:
    out = [m for m in REGISTRY.values()
           if m.task == task and m.status is not Status.REJECTED]
    if only_approved:
        out = [m for m in out if m.approved_for_demo]
    return sorted(out, key=lambda m: (not m.approved_for_demo, m.latency_budget_ms or 1e9))


def rejected() -> list[ModelRecord]:
    """Rejected models, kept so the reasoning survives staff turnover."""
    return [m for m in REGISTRY.values() if m.status is Status.REJECTED]


def audit() -> list[str]:
    """Governance problems in the registry itself."""
    problems = []
    for m in REGISTRY.values():
        if m.approved_for_demo and not m.licence_ok:
            problems.append(f"{m.key}: approved for demo but licence is {m.licence}")
        if m.approved_for_production and m.measured_latency_ms is None:
            problems.append(f"{m.key}: approved for production with no measured latency")
        if m.status is Status.ACTIVE and not m.approved_for_demo:
            problems.append(f"{m.key}: ACTIVE but not approved for demo")
    return problems
