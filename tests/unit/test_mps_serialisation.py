"""MPS inference is serialised, because PyTorch's Metal shader cache races.

A twenty-two minute live capture of the government grid died with **SIGSEGV**
inside `at::native::mps::MetalShaderLibrary::exec_unary_kernel` — no Python
traceback, no error, no observations. Six camera workers were calling MPS
operations concurrently and corrupting a lazily-populated shader cache that is
not thread-safe. It is a race: one camera always worked, eight sometimes did,
six died. Two captures were lost to it before the crash report was read.

The GPU is a single serial resource, so serialising costs nothing real. CPU and
ONNX Runtime stay concurrent — both are thread-safe, and holding the lock for
them would throw away parallelism on a ten-core machine.
"""
from __future__ import annotations

import contextlib
import threading
import time

from saakshya.runtime import backend as bk


def test_mps_work_takes_the_lock():
    assert bk._device_lock("mps") is bk._MPS_LOCK


def test_cpu_and_onnx_work_does_not():
    for device in ("cpu", "cuda", ""):
        lock = bk._device_lock(device)
        assert lock is not bk._MPS_LOCK, f"{device} must not serialise"


def test_two_mps_callers_never_overlap():
    """The property that matters: no two MPS calls are ever in flight at once."""
    inside = 0
    overlapped = False

    def work():
        nonlocal inside, overlapped
        with bk._device_lock("mps"):
            inside += 1
            if inside > 1:
                overlapped = True
            time.sleep(0.01)
            inside -= 1

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not overlapped


def test_cpu_callers_do_overlap():
    """Proves the lock is genuinely not held for CPU work, rather than the
    previous test passing because nothing ran concurrently at all."""
    inside = 0
    overlapped = False
    gate = threading.Barrier(4)

    def work():
        nonlocal inside, overlapped
        with bk._device_lock("cpu"):
            inside += 1
            gate.wait(timeout=2)
            if inside > 1:
                overlapped = True
            inside -= 1

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlapped


def test_the_lock_is_released_when_inference_raises():
    """A failing frame must not wedge every camera behind it."""
    class Boom(bk.InferenceBackend):
        _device = "mps"

        def load(self, record):  # pragma: no cover - not used
            pass

        def detect(self, image):
            return self._timed(self._explode)

        def ocr(self, image):  # pragma: no cover - not used
            return None

        def embed(self, image):  # pragma: no cover - not used
            raise NotImplementedError

        @property
        def loaded(self):  # pragma: no cover - not used
            return True

        @staticmethod
        def _explode():
            raise ValueError("bad crop")

    b = Boom()
    for _ in range(3):
        with contextlib.suppress(ValueError):
            b.detect(None)
    assert bk._MPS_LOCK.acquire(timeout=1), "the lock was not released"
    bk._MPS_LOCK.release()
