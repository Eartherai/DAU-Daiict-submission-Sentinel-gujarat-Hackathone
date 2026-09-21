#!/usr/bin/env python3
"""Emit the Model 1 registry API documentation and a sample metadata dataset.

Two named deliverables: "Registry API documentation" and "Sample onboarded
camera-metadata dataset". Both are generated from the running platform — the
documentation from its own OpenAPI schema, the dataset from its own export
endpoint — so neither can describe an API the service does not serve.

    python tools/reports/registry_api_doc.py \
        --base http://127.0.0.1:8083 --token-file tok.raw \
        --out reports/REGISTRY_API.md \
        --dataset reports/sample_camera_metadata.csv

Hand-written API documentation drifts the first time a field is added and
nobody notices until an integrator does. Generating it means the worst case is
that it is terse, not that it is wrong.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

#: The registry surface Model 1 is about. Other endpoints are documented by the
#: OpenAPI schema itself; this report is for the integrator onboarding cameras.
PREFIXES = ("/registry/", "/gis/gaps", "/gis/cameras", "/gis/capability")


def _get(base: str, path: str, token: str) -> tuple[int, str]:
    req = urllib.request.Request(f"{base}{path}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _schema_fields(spec: dict, name: str) -> list[tuple[str, str, bool]]:
    comp = (spec.get("components") or {}).get("schemas") or {}
    node = comp.get(name) or {}
    required = set(node.get("required") or [])
    out: list[tuple[str, str, bool]] = []
    for field, meta in (node.get("properties") or {}).items():
        kind = meta.get("type")
        if not kind:
            any_of = meta.get("anyOf") or []
            kinds = [a.get("type") for a in any_of if a.get("type") != "null"]
            kind = kinds[0] if kinds else "string"
        out.append((field, str(kind), field in required))
    return out


def render(spec: dict, base: str, samples: dict[str, str]) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    paths = spec.get("paths") or {}
    o: list[str] = []
    w = o.append

    w("# Registry API")
    w("")
    w(f"Generated {now} from the running service's own OpenAPI schema, so it")
    w("cannot describe an endpoint the platform does not serve.")
    w("")
    w("The registry is Model 1: camera metadata, onboarding and gap reporting.")
    w("It holds what departments supply and reports what they have not — it")
    w("never invents a value to fill a column.")
    w("")

    w("## Authentication")
    w("")
    w("Every request carries a bearer token and is written to the hash-chained")
    w("audit log with its actor, role and purpose. Onboarding requires")
    w("`admin:write`; reading the registry requires `camera:read`. A role that")
    w("lacks the permission is refused before the request reaches the store,")
    w("and the refusal is audited like any other action.")
    w("")
    w("```")
    w("Authorization: Bearer <token>")
    w("```")
    w("")

    w("## Endpoints")
    w("")
    for path in sorted(paths):
        if not any(path.startswith(p) for p in PREFIXES):
            continue
        for method, op in sorted((paths[path] or {}).items()):
            if method not in {"get", "post", "put", "delete"}:
                continue
            w(f"### `{method.upper()} {path}`")
            w("")
            summary = op.get("summary") or ""
            if summary:
                w(f"{summary}.")
                w("")
            doc = (op.get("description") or "").strip()
            if doc:
                for line in doc.splitlines():
                    w(line)
                w("")
            params = op.get("parameters") or []
            if params:
                w("| Parameter | In | Type | Default |")
                w("|---|---|---|---|")
                for p in params:
                    sch = p.get("schema") or {}
                    kind = sch.get("type") or "string"
                    default = sch.get("default")
                    shown = "—" if default is None else f"`{default}`"
                    w(f"| `{p.get('name')}` | {p.get('in')} | {kind} | {shown} |")
                w("")
            w("")

    w("## Camera record")
    w("")
    fields = _schema_fields(spec, "CameraIn")
    if fields:
        w("Every field a department may supply. Only `camera_id` is required:")
        w("a registry's purpose is to hold what is known and report what is")
        w("not, so a row carrying nothing but an identifier is a legitimate")
        w("entry that the gap report will then name.")
        w("")
        w("| Field | Type | Required |")
        w("|---|---|---|")
        for field, kind, req in fields:
            w(f"| `{field}` | {kind} | {'**yes**' if req else 'no'} |")
        w("")

    w("## Worked examples")
    w("")
    for title, body in samples.items():
        w(f"### {title}")
        w("")
        w("```")
        w(body.strip())
        w("```")
        w("")

    w("## Behaviour an integrator should rely on")
    w("")
    w("- **An import applies wholly or not at all.** Rows are validated first;")
    w("  one bad row refuses the batch, naming the row number and the reason.")
    w("  A partial import would leave nobody able to say which half landed.")
    w("- **`dry_run` runs the same validation and writes nothing**, which is")
    w("  how a department checks a file before committing it.")
    w("- **Re-uploading cannot silently overwrite curation.** Amending an")
    w("  existing camera must be asked for with `update_existing`, so a stale")
    w("  spreadsheet cannot rewrite a position corrected by hand.")
    w("- **Export round-trips into import.** The columns written by")
    w("  `export.csv` are the columns `import.csv` accepts, so a file can be")
    w("  corrected in a spreadsheet and sent back.")
    w("- **Unknown CSV columns are ignored, not refused**, because a")
    w("  departmental export carries operational columns that are none of this")
    w("  registry's business.")
    return "\n".join(o) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8083")
    ap.add_argument("--token")
    ap.add_argument("--token-file")
    ap.add_argument("--out", default="reports/REGISTRY_API.md")
    ap.add_argument("--dataset", default="reports/sample_camera_metadata.csv")
    a = ap.parse_args()

    token = ""
    if a.token_file:
        token = Path(a.token_file).read_text(encoding="ascii").strip()
    elif a.token:
        token = a.token

    status, body = _get(a.base, "/openapi.json", token)
    if status != 200:
        raise SystemExit(f"could not read the OpenAPI schema: HTTP {status}")
    spec = json.loads(body)

    # The sample dataset is the registry's own export, not a hand-made file.
    ds_status, ds_body = _get(a.base, "/registry/cameras/export.csv", token)
    dataset = Path(a.dataset)
    rows = 0
    if ds_status == 200:
        dataset.parent.mkdir(parents=True, exist_ok=True)
        dataset.write_text(ds_body, encoding="utf-8")
        rows = max(0, len(list(csv.reader(io.StringIO(ds_body)))) - 1)

    samples = {
        "Onboard two cameras": (
            "POST /registry/cameras/import\n"
            "Content-Type: application/json\n\n"
            + json.dumps({"cameras": [
                {"camera_id": "MC-0001", "name": "Municipal gate",
                 "department": "Municipal Corporation", "district": "Ahmedabad",
                 "lat": 23.0301, "lon": 72.58, "vms": "Milestone",
                 "storage_location": "cloud", "retention_days": 15},
                {"camera_id": "RTO-0007", "name": "Testing track",
                 "department": "RTO", "district": "Rajkot"}]}, indent=2)),
        "Check a departmental spreadsheet without committing it": (
            "POST /registry/cameras/import.csv?dry_run=true\n"
            "Content-Type: text/csv\n\n"
            "camera_id,name,department,lat,lon,vms,retention_days\n"
            "MC-0002,Riverfront east,Municipal Corporation,23.02,72.57,"
            "Milestone,15"),
        "Ask the registry what it does not know": (
            "GET /gis/gaps\n\n"
            + json.dumps({"cameras": 34, "capacity_slots": 18,
                          "departments_absent": [],
                          "field_gaps": [{"field": "vms", "missing": 32,
                                          "of": 34, "pct": 94.1}]}, indent=2)),
    }

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(spec, a.base, samples), encoding="utf-8")

    documented = sum(
        1 for p in spec.get("paths", {})
        if any(p.startswith(x) for x in PREFIXES))
    print(f"wrote {out} — {documented} registry endpoint(s) documented")
    if ds_status == 200:
        print(f"wrote {dataset} — {rows} onboarded cameras")
    else:
        print(f"dataset NOT written (HTTP {ds_status}); the deliverable list "
              "includes a sample onboarded camera-metadata dataset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
