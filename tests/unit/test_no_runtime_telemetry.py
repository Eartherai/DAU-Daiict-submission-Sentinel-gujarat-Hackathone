"""No inference runtime phones home.

ONNX Runtime 1.29 starts Microsoft's usage-telemetry client when it is
imported and uploads a queue kept under ~/Library/Application Support. The
package sets ORT_DISABLE_TELEMETRY before anything can import the runtime, and
hardware.onnxruntime_offline() switches the client off before the first
session.

Both tests here first read only os.environ in a subprocess that never imports
onnxruntime, so removing the runtime switch changed nothing they could see.
The switch itself is now exercised against a stand-in module.

The package promises an operator who sets the variable to 0 that the choice
stands, but the runtime switch never read it and turned telemetry off at the
first model load anyway. It now honours an explicit 0, and nothing else.
"""
from __future__ import annotations

import importlib.machinery
import os
import subprocess
import sys
import types

from saakshya.runtime import hardware


def test_importing_the_package_switches_runtime_telemetry_off() -> None:
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    out = subprocess.run(
        [sys.executable, "-c",
         "import saakshya, os; print(os.environ.get('ORT_DISABLE_TELEMETRY'))"],
        env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1"


def test_the_import_leaves_an_operators_own_setting_alone() -> None:
    # The runtime switch's half of that promise is held by the stand-in tests
    # below: an explicit 0 leaves disable_telemetry_events() uncalled.
    env = {**os.environ, "ORT_DISABLE_TELEMETRY": "0"}
    out = subprocess.run(
        [sys.executable, "-c",
         "import saakshya, os; print(os.environ.get('ORT_DISABLE_TELEMETRY'))"],
        env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0"


def _stand_in_onnxruntime(monkeypatch, setting: str | None = "1") -> list[str]:
    if setting is None:
        monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    else:
        monkeypatch.setenv("ORT_DISABLE_TELEMETRY", setting)
    calls: list[str] = []
    ort = types.ModuleType("onnxruntime")
    ort.__spec__ = importlib.machinery.ModuleSpec("onnxruntime", loader=None)
    ort.disable_telemetry_events = lambda: calls.append("disable_telemetry_events")
    ort.get_available_providers = lambda: calls.append("providers") or [
        "CPUExecutionProvider"]
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    return calls


def test_the_runtime_switch_turns_the_client_off(monkeypatch) -> None:
    calls = _stand_in_onnxruntime(monkeypatch)
    hardware.onnxruntime_offline()
    assert calls == ["disable_telemetry_events"]


def test_the_provider_probe_turns_the_client_off_before_it_asks(monkeypatch) -> None:
    # The probe is the first thing on this host to touch the runtime.
    calls = _stand_in_onnxruntime(monkeypatch)
    assert hardware._onnx_providers() == ("CPUExecutionProvider",)
    assert calls == ["disable_telemetry_events", "providers"]


def test_the_switch_fails_closed_without_an_explicit_zero(monkeypatch) -> None:
    # Unset, empty, or any spelling but 0 is not an operator's choice of
    # telemetry, and the switch turns the client off.
    for setting in (None, "", "false", "00"):
        calls = _stand_in_onnxruntime(monkeypatch, setting)
        hardware.onnxruntime_offline()
        assert calls == ["disable_telemetry_events"], setting


def test_an_operators_zero_survives_the_runtime_switch(monkeypatch) -> None:
    calls = _stand_in_onnxruntime(monkeypatch, "0")
    hardware.onnxruntime_offline()
    assert calls == []


def test_an_operators_zero_survives_the_provider_probe(monkeypatch) -> None:
    calls = _stand_in_onnxruntime(monkeypatch, "0")
    assert hardware._onnx_providers() == ("CPUExecutionProvider",)
    assert calls == ["providers"]
