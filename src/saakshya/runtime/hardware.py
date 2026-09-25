"""Hardware probe.

The system must behave correctly on an Apple Silicon laptop with no GPU, on a
rented CUDA box used for benchmarking, and on the deployment target. That is
only safe if the code *knows* what it is running on rather than assuming, so
every capability below is detected, never configured by hand.

Nothing here imports torch or CUDA libraries eagerly — probing must not cost a
multi-second import on a CPU-only machine.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class GpuInfo:
    index: int
    name: str
    memory_mb: int
    compute_capability: str | None = None


@dataclass(frozen=True)
class Hardware:
    os_name: str
    arch: str
    cpu_count: int
    total_memory_mb: int

    has_cuda: bool = False
    gpus: tuple[GpuInfo, ...] = ()
    cuda_version: str | None = None

    has_tensorrt: bool = False
    has_deepstream: bool = False
    #: Apple Neural Engine / Metal, exposed through ONNX Runtime's CoreML EP.
    has_coreml: bool = False
    #: Apple Metal via torch. Measured 3.5x faster than CPU for RT-DETRv2-R18
    #: (50 ms vs 176 ms p50). Unrelated to the CoreML ONNX EP, which is unsafe here.
    has_mps: bool = False
    onnx_providers: tuple[str, ...] = ()

    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def gpu_memory_mb(self) -> int:
        return sum(g.memory_mb for g in self.gpus)

    @property
    def summary(self) -> str:
        if self.has_cuda and self.gpus:
            g = ", ".join(f"{x.name} ({x.memory_mb} MB)" for x in self.gpus)
            return f"{self.arch} · {self.cpu_count} vCPU · CUDA {self.cuda_version} · {g}"
        accel = " · Apple MPS" if self.has_mps else ""
        return f"{self.arch} · {self.cpu_count} vCPU · no CUDA GPU{accel}"

    def to_dict(self) -> dict:
        return asdict(self)


def _total_memory_mb() -> int:
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names:
            return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e6)
    except (OSError, ValueError, KeyError):
        pass
    try:  # macOS
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                             text=True, timeout=3)
        if out.returncode == 0:
            return int(int(out.stdout.strip()) / 1e6)
    except Exception:
        pass
    return 0


def _probe_nvidia() -> tuple[bool, tuple[GpuInfo, ...], str | None]:
    """Read GPUs from nvidia-smi. Deliberately does not import torch."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False, (), None
    try:
        q = subprocess.run(
            [exe, "--query-gpu=index,name,memory.total,compute_cap",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
        )
        if q.returncode != 0:
            return False, (), None
        gpus = []
        for line in q.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            gpus.append(GpuInfo(
                index=int(parts[0]), name=parts[1], memory_mb=int(float(parts[2])),
                compute_capability=parts[3] if len(parts) > 3 else None,
            ))
        ver = subprocess.run([exe, "--query-gpu=driver_version", "--format=csv,noheader"],
                            capture_output=True, text=True, timeout=8)
        cuda_ver = ver.stdout.strip().splitlines()[0] if ver.returncode == 0 else None
        return bool(gpus), tuple(gpus), cuda_ver
    except Exception:
        return False, (), None


def _probe_mps() -> bool:
    """Apple Metal, for torch models only.

    Deliberately separate from the CoreML ONNX provider: CoreML fails on the
    plate-detector graph, while MPS works well for transformers models. Treating
    them as one capability would lose a measured 3.5x speed-up or reintroduce a
    known crash.
    """
    if importlib.util.find_spec("torch") is None:
        return False
    try:
        import torch

        return bool(torch.backends.mps.is_available())
    except Exception:
        return False


def onnxruntime_offline() -> None:
    """Switch off ONNX Runtime's usage telemetry before its first session.

    ONNX Runtime 1.29 carries Microsoft's telemetry client, which posts usage
    events over HTTPS from a worker thread of its own. Nothing here configured
    it and nothing here wants it: this platform's rule is that detection and
    ANPR stay on the deployment's own hardware, and a police host should not
    make calls nobody asked for. It also crashed interpreter shutdown - that
    thread dispatched an HTTP response after the logger it reports to had been
    destroyed ("recursive_mutex lock failed", about one test run in five; the
    macOS crash report names the telemetry client's HttpClientManager).

    The one exception is an operator who set ORT_DISABLE_TELEMETRY to 0: that
    is a call somebody configured, and saakshya/__init__.py promises to leave
    it alone. This switch used to ignore the variable, so the 0 held only
    until the first model load or provider probe - and not even then as off,
    since the variable had already let the client start at import. Only an
    explicit 0 counts; unset, 1 or anything else is switched off here.
    """
    if os.environ.get("ORT_DISABLE_TELEMETRY") == "0":
        return
    if importlib.util.find_spec("onnxruntime") is None:
        return
    try:
        import onnxruntime as ort

        ort.disable_telemetry_events()
    except Exception:  # an older build without the switch has no client either
        pass


def _onnx_providers() -> tuple[str, ...]:
    if importlib.util.find_spec("onnxruntime") is None:
        return ()
    try:
        import onnxruntime as ort

        onnxruntime_offline()
        return tuple(ort.get_available_providers())
    except Exception:
        return ()


@lru_cache(maxsize=1)
def probe() -> Hardware:
    """Detect the host once per process."""
    notes: list[str] = []
    has_cuda, gpus, cuda_ver = _probe_nvidia()
    providers = _onnx_providers()

    has_trt = has_cuda and (
        importlib.util.find_spec("tensorrt") is not None
        or "TensorrtExecutionProvider" in providers
    )
    has_ds = shutil.which("deepstream-app") is not None

    has_coreml = "CoreMLExecutionProvider" in providers
    has_mps = _probe_mps()
    if has_coreml:
        # Measured: the CoreML EP fails on the plate-detector graph with
        # "dynamic shape ... has zero elements", taking the whole call with it.
        # It is detected but not trusted by default.
        notes.append(
            "CoreML EP present but not enabled by default: it fails on graphs "
            "with zero-element dynamic shapes (observed on the plate detector)."
        )
    if not has_cuda:
        notes.append("No CUDA GPU. GPU-tier models must be benchmarked remotely.")

    return Hardware(
        os_name=platform.system(),
        arch=platform.machine(),
        cpu_count=os.cpu_count() or 1,
        total_memory_mb=_total_memory_mb(),
        has_cuda=has_cuda,
        gpus=gpus,
        cuda_version=cuda_ver,
        has_tensorrt=has_trt,
        has_deepstream=has_ds,
        has_coreml=has_coreml,
        has_mps=has_mps,
        onnx_providers=providers,
        notes=tuple(notes),
    )
