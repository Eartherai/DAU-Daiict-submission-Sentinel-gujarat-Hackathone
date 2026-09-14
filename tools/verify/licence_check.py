#!/usr/bin/env python3
"""Licence policy gate.

Enforces the policy recorded in `docs/OPEN_SOURCE_LANDSCAPE.md` against what is
*actually installed*, not against what we intended to install. Transitive
dependencies are the risk: a permissive package can pull in a copyleft one, and
nobody notices until a procurement review.

Policy:
  * AGPL / GPL / BSL in the **runtime dependency graph** is a failure.
  * A small allowlist covers packages used as separately-deployed services or
    build-time tools, each with a written reason.

Also emits a CycloneDX-style SBOM to var/reports/sbom.json.
"""
from __future__ import annotations

import json
import sys
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BLOCKED_TOKENS = ("AGPL", "GPL-3", "GPLv3", "GPL-2", "GPLv2",
                  "Business Source", "BUSL", "SSPL", "Commons Clause")
#: LGPL is permitted: we link dynamically and do not modify.
PERMITTED_TOKENS = ("LGPL",)

#: Artefacts that are NOT Python distributions and are therefore invisible to any
#: PyPI licence scan. This is the blind spot that fails procurement reviews:
#: `imageio-ffmpeg` declares BSD-2-Clause for its wrapper while shipping a GPL
#: FFmpeg binary. Enumerated by hand because no tool will find them for us.
NON_PYPI_ARTEFACTS = [
    {
        "artefact": "FFmpeg 7.1 binary (bundled by imageio-ffmpeg)",
        "licence": "GPL-2.0-or-later (built --enable-gpl with libx264/libx265)",
        "use": "External process. Corpus rendering and test-stream publishing.",
        "distributed_with_product": False,
        "risk": "None while invoked as a separate binary and not shipped. If "
                "corpus media or the binary are ever redistributed, re-examine.",
    },
    {
        "artefact": "MediaMTX 1.20.1 binary",
        "licence": "MIT",
        "use": "Local sandbox replica and own-feed demo server.",
        "distributed_with_product": False,
        "risk": "None. MIT, and dev/test only.",
    },
    {
        "artefact": "yolo-v9-t-640 plate detector weights (open-image-models)",
        "licence": "MIT",
        "use": "Plate detection. ACTIVE.",
        "distributed_with_product": True,
        "risk": "None.",
    },
    {
        "artefact": "cct-s-v2-global OCR weights (fast-plate-ocr)",
        "licence": "MIT",
        "use": "Plate OCR. ACTIVE.",
        "distributed_with_product": True,
        "risk": "None.",
    },
    {
        "artefact": "Model weights fetched from Hugging Face at runtime",
        "licence": "Per-model; audited in docs/MODEL_BENCHMARK.md",
        "use": "Registry-gated. ModelRouter refuses non-permissive licences.",
        "distributed_with_product": False,
        "risk": "Controlled by the model registry, enforced by "
                "test_router_never_returns_a_copyleft_model.",
    },
]

ALLOWLIST: dict[str, str] = {
    # Package -> written justification. Nothing gets in here silently.
    "imageio-ffmpeg": (
        "Ships a GPL FFmpeg *binary* invoked as an external process for corpus "
        "generation and test-stream publishing. Not linked, not distributed with "
        "the product. Build-time tool only."
    ),
}


def norm(text: str | None) -> str:
    return (text or "").replace("\n", " ").strip()


def licence_of(dist) -> str:
    md = dist.metadata
    lic = norm(md.get("License"))
    if lic and lic.lower() not in {"unknown", "license"} and len(lic) < 120:
        return lic
    classifiers = [c for c in md.get_all("Classifier") or []
                   if c.startswith("License ::")]
    if classifiers:
        return "; ".join(c.split("::")[-1].strip() for c in classifiers)
    expr = norm(md.get("License-Expression"))
    return expr or "UNKNOWN"


def main() -> int:
    rows = []
    for d in distributions():
        name = d.metadata.get("Name")
        if not name or name == "saakshya":
            continue
        rows.append({"name": name, "version": d.version, "licence": licence_of(d)})
    rows.sort(key=lambda r: r["name"].lower())

    violations, allowed, unknown = [], [], []
    for r in rows:
        lic = r["licence"]
        # LGPL contains "GPL"; check the permitted form first.
        if any(t in lic for t in PERMITTED_TOKENS) and "AGPL" not in lic:
            continue
        if any(t in lic for t in BLOCKED_TOKENS):
            (allowed if r["name"] in ALLOWLIST else violations).append(r)
        elif lic == "UNKNOWN":
            unknown.append(r)

    sbom = {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "metadata": {"component": {"type": "application", "name": "saakshya"}},
        "components": [
            {"type": "library", "name": r["name"], "version": r["version"],
             "licenses": [{"license": {"name": r["licence"]}}]} for r in rows
        ] + [
            {"type": "application", "name": a["artefact"], "version": "n/a",
             "licenses": [{"license": {"name": a["licence"]}}],
             "properties": [{"name": "shipped",
                             "value": str(a["distributed_with_product"])},
                            {"name": "use", "value": a["use"]}]}
            for a in NON_PYPI_ARTEFACTS
        ],
    }
    out = ROOT / "var" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sbom.json").write_text(json.dumps(sbom, indent=2))

    print(f"LICENCE CHECK: {len(rows)} installed distributions")
    print(f"  + {len(NON_PYPI_ARTEFACTS)} non-PyPI artefacts (invisible to a package scan):")
    for a in NON_PYPI_ARTEFACTS:
        ship = "SHIPPED" if a["distributed_with_product"] else "not shipped"
        print(f"    {a['artefact'][:52]:<54} {a['licence'][:34]:<36} {ship}")
    if allowed:
        print("  allowlisted copyleft (with recorded justification):")
        for r in allowed:
            print(f"    {r['name']} {r['version']} — {r['licence']}")
            print(f"      reason: {ALLOWLIST[r['name']][:100]}")
    if unknown:
        print(f"  licence not declared ({len(unknown)}): "
              f"{', '.join(r['name'] for r in unknown[:8])}"
              f"{' …' if len(unknown) > 8 else ''}")
        print("    -> not a failure, but each must be resolved before release")
    if violations:
        print("\nLICENCE CHECK: FAIL — copyleft/BSL in the dependency graph:")
        for r in violations:
            print(f"    {r['name']} {r['version']}: {r['licence']}")
        print("  Either remove the dependency or add a justified ALLOWLIST entry.")
        return 1
    print("  SBOM -> var/reports/sbom.json")
    print("LICENCE CHECK: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
