"""No inference runtime phones home.

ONNX Runtime 1.29 starts Microsoft's usage-telemetry client when it is
imported and uploads a queue kept under ~/Library/Application Support. The
package sets ORT_DISABLE_TELEMETRY before anything can import the runtime.
"""
from __future__ import annotations

import os
import subprocess
import sys


def test_importing_the_package_switches_runtime_telemetry_off() -> None:
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    out = subprocess.run(
        [sys.executable, "-c",
         "import saakshya, os; print(os.environ.get('ORT_DISABLE_TELEMETRY'))"],
        env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1"


def test_an_operator_can_still_choose_otherwise() -> None:
    env = {**os.environ, "ORT_DISABLE_TELEMETRY": "0"}
    out = subprocess.run(
        [sys.executable, "-c",
         "import saakshya, os; print(os.environ.get('ORT_DISABLE_TELEMETRY'))"],
        env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0"
