"""tools/db/setup_postgres.sh installs the PostgreSQL and PostGIS the docs name.

The README and the HLD say the script gives PostgreSQL 18 + PostGIS 3.6, and
the PostgreSQL reports were measured on 18.6 + 3.6.4. The script asked
conda-forge for `postgis` with no version, which is whatever was newest on the
day of the install, so a fresh install could be a pair the docs never
described.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _install_specs() -> str:
    script = (ROOT / "tools/db/setup_postgres.sh").read_text().replace("\\\n", " ")
    creates = [ln for ln in script.splitlines() if "micromamba\" create" in ln]
    assert len(creates) == 1, creates
    return creates[0]


def test_the_install_is_pinned_to_the_pair_the_docs_name():
    specs = _install_specs()
    postgis = re.search(r'"postgis=(\d+\.\d+\.\d+)"', specs)
    postgresql = re.search(r'"postgresql=(\d+\.\d+)"', specs)
    assert postgis and postgresql, f"unpinned: {specs.strip()}"
    pg_major = postgresql.group(1).split(".")[0]
    gis_minor = ".".join(postgis.group(1).split(".")[:2])
    named = f"PostgreSQL {pg_major} + PostGIS {gis_minor}"
    for doc in ("README.md", "docs/HLD.md"):
        text = (ROOT / doc).read_text()
        assert named in text or f"PostgreSQL {pg_major} with PostGIS {gis_minor}" in text, (
            f"{doc} does not name {named}")
