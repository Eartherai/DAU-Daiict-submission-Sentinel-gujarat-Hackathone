"""Saakshya — Federated CCTV Intelligence & Evidence Fabric."""
import os as _os

# ONNX Runtime 1.29 starts Microsoft's usage-telemetry client when it is
# imported, and uploads a queue it keeps under ~/Library/Application Support.
# Nothing here asked for that: detection and ANPR stay on the deployment's own
# hardware, and a police host should make no call nobody configured. Its
# worker thread also crashed interpreter shutdown about one run in four. The
# switch is read at import, so it is set before any module can import the
# runtime; an operator who wants telemetry can still set it to 0.
_os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

__version__ = "0.1.0"
PIPELINE_VERSION = f"saakshya@{__version__}"
