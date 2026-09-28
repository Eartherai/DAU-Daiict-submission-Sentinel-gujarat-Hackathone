"""The serve targets' default basemap template must reach the app intact.

sh ends ``${VAR:-word}`` at the first ``}`` inside ``word``, so a default of
``.../{z}/{x}/{y}.png`` written inline arrived as ``.../{z/{x}/{y}.png}`` and
every OpenStreetMap tile request failed with 400: maps drew over a blank canvas.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def test_no_brace_default_inside_a_parameter_expansion():
    assert ":-https://tile.openstreetmap.org" not in (ROOT / "Makefile").read_text()


def test_default_template_survives_the_shell():
    text = (ROOT / "Makefile").read_text()
    osm = [ln.strip().rstrip("\\").strip() for ln in text.splitlines()
           if ln.strip().startswith("osm=")]
    assert len(osm) == 2 and text.count('SAAKSHYA_MAP_TILES="$${SAAKSHYA_MAP_TILES:-$$osm}"') == 2
    env = {k: v for k, v in os.environ.items() if k != "SAAKSHYA_MAP_TILES"}
    script = osm[0] + ' X="${SAAKSHYA_MAP_TILES:-$osm}"; printf %s "$X"'
    out = subprocess.run(["/bin/sh", "-c", script], env=env, capture_output=True, text=True)
    assert out.stdout == TEMPLATE
    env["SAAKSHYA_MAP_TILES"] = "https://tiles.example.invalid/{z}/{x}/{y}.png"
    out = subprocess.run(["/bin/sh", "-c", script], env=env, capture_output=True, text=True)
    assert out.stdout == env["SAAKSHYA_MAP_TILES"]
