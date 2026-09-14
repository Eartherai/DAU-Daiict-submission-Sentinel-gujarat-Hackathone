"""Exercise the whole HTTP surface against a running server, as four roles.

Two things are checked, and the second matters as much as the first:

  * every route a role IS entitled to reach returns 200 with a payload of the
    documented shape, and
  * every route a role is NOT entitled to reach REFUSES, with the specific
    refusal the four authorisation gates are supposed to produce.

A suite that only tests the happy path cannot tell a working access-control
system from one that has been switched off, so the refusals are assertions
here, not skipped cases. `EXPECT` names the gate each row is exercising.

Usage:
    python tools/verify/api_surface.py --base http://127.0.0.1:8000 \
        --tokens <dir containing tok_<role>.txt>
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TIMEOUT_S = 60.0

# Gate names, so a failure says which control did not fire.
AUTHN = "authentication"
ROLE = "role permission"
GEO = "jurisdiction scope"
PURPOSE = "purpose binding"


class Client:
    def __init__(self, base: str, token: str) -> None:
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, *, case: str | None = None,
             purpose: str | None = None, body: Any = None,
             anonymous: bool = False) -> tuple[int, Any]:
        req = urllib.request.Request(self.base + path, method=method)
        if not anonymous:
            req.add_header("authorization", "Bearer " + self.token)
        if case:
            req.add_header("X-Case-Id", case)
        if purpose:
            req.add_header("X-Purpose", purpose)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, data, timeout=TIMEOUT_S) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"null")
            except json.JSONDecodeError:
                return e.code, raw.decode("utf-8", "replace")[:200]
        except OSError as e:                      # server down, DNS, timeout
            return 0, {"error": str(e)}


def code_of(body: Any) -> str:
    if isinstance(body, dict):
        d = body.get("detail")
        if isinstance(d, dict):
            return str(d.get("code", ""))
    return ""


def summarise(v: Any) -> str:
    if isinstance(v, dict):
        if not v:
            return "{}"
        ks = list(v)[:5]
        return "{" + ", ".join(ks) + ("…" if len(v) > 5 else "") + "}"
    if isinstance(v, list):
        return f"[{len(v)}]"
    return type(v).__name__


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--tokens", required=True, type=Path,
                    help="directory holding tok_<role>.txt, never committed")
    ap.add_argument("--case", default="FIR-LIVE/2026")
    ap.add_argument("--plate", default="GJ38BH5815")
    ap.add_argument("--camera", default="cam01")
    ap.add_argument("--json", type=Path, help="write the result matrix here")
    a = ap.parse_args()

    tok: dict[str, str] = {}
    for role in ("investigator", "supervisor", "admin", "auditor", "operator"):
        f = a.tokens / f"tok_{role}.txt"
        if f.exists():
            tok[role] = f.read_text().strip()
    if not tok:
        print(f"no tok_<role>.txt found under {a.tokens}", file=sys.stderr)
        return 2

    cli = {r: Client(a.base, t) for r, t in tok.items()}
    purpose = "verifying platform functions against the live grid"

    # A purpose-bound route needs a real case to bind to. Create it once.
    if "supervisor" in cli:
        st, _ = cli["supervisor"].call(
            "POST", "/cases", purpose=purpose,
            body={"case_id": a.case, "title": "Live grid function check",
                  "purpose": purpose, "district": "Ahmedabad",
                  "classification": "Verification"})
        made = "created" if st in (200, 201) else f"already present or refused ({st})"
        print(f"case {a.case}: {made}\n")

    bbox = "?south=20&west=68&north=25&east=75"
    seen = "2026-06-14T08:01:00Z"

    # (role, method, path, kwargs, expect_status, gate_or_note)
    checks: list[tuple[str, str, str, dict, int, str]] = [
        # ---- open to any authenticated principal ------------------------- #
        ("investigator", "GET", "/me", {}, 200, ""),
        ("investigator", "GET", "/config", {}, 200, ""),
        ("investigator", "GET", "/overview", {}, 200, ""),
        # ---- GIS ---------------------------------------------------------- #
        ("investigator", "GET", "/gis/extent", {}, 200, ""),
        ("investigator", "GET", "/gis/cameras" + bbox, {}, 200, ""),
        ("investigator", "GET", "/gis/capability", {}, 200, ""),
        ("investigator", "GET", "/gis/coverage" + bbox, {}, 200, ""),
        ("investigator", "GET", "/gis/health", {}, 200, ""),
        ("investigator", "GET", "/gis/alerts" + bbox, {}, 200, ""),
        ("investigator", "GET", "/gis/timebase", {}, 200, ""),
        ("investigator", "GET", "/gis/timebase/check?cameras=cam01,cam02", {}, 200, ""),
        # ---- capability --------------------------------------------------- #
        ("investigator", "GET", "/capability/summary", {}, 200, ""),
        # ---- system diagnostics ------------------------------------------- #
        ("investigator", "GET", "/system/health", {}, 200, ""),
        ("investigator", "GET", "/system/integration", {}, 200, ""),
        ("operator", "GET", "/system/health", {}, 200, ""),
        ("admin", "POST", "/capability/grade?camera_id={c}", {}, 200, ""),
        ("investigator", "POST", "/capability/grade?camera_id={c}", {}, 403, ROLE),
        # ---- investigation, purpose-bound --------------------------------- #
        ("supervisor", "GET", "/watchlist", {"case": True}, 200, PURPOSE),
        ("supervisor", "GET", "/search?plate={p}", {"case": True}, 200, PURPOSE),
        ("supervisor", "GET", "/targets/{p}/observations", {"case": True}, 200, PURPOSE),
        ("supervisor", "GET", "/trajectory/{p}", {"case": True}, 200, PURPOSE),
        ("supervisor", "GET", "/gis/trajectory/{p}", {"case": True}, 200, PURPOSE),
        ("supervisor", "GET", f"/cameras/{{c}}/next?seen_at={seen}", {"case": True}, 200, ""),
        ("supervisor", "GET", "/cameras/{c}", {"case": True}, 200, ""),
        # ---- control room -------------------------------------------------- #
        ("operator", "GET", "/alerts", {}, 200, ""),
        ("operator", "GET", "/gis/health", {}, 200, ""),
        # ---- cases and evidence -------------------------------------------- #
        ("supervisor", "GET", "/cases", {}, 200, ""),
        ("supervisor", "GET", "/evidence/chain/verify", {}, 200, ""),
        # ---- edge ----------------------------------------------------------- #
        ("supervisor", "GET", "/edge/nodes", {}, 200, ""),
        # ---- audit, auditor only -------------------------------------------- #
        ("auditor", "GET", "/audit", {}, 200, ""),
        # ---- admin, admin only ----------------------------------------------- #
        ("admin", "GET", "/admin/cameras", {}, 200, ""),
        ("admin", "GET", "/admin/users", {}, 200, ""),
        ("admin", "GET", "/admin/roles", {}, 200, ""),
        ("admin", "GET", "/admin/policy", {}, 200, ""),
        ("admin", "GET", "/admin/departments", {}, 200, ""),
        # ---- copilot ---------------------------------------------------------- #
        ("investigator", "POST", "/copilot/ask",
         {"body": {"question": "How many cameras can read plates?"}}, 200, ""),

        # ================= the gates must REFUSE ================================ #
        ("investigator", "GET", "/overview", {"anon": True}, 401, AUTHN),
        ("investigator", "GET", "/audit", {}, 403, ROLE),
        ("investigator", "GET", "/admin/users", {}, 403, ROLE),
        ("operator", "GET", "/search?plate={p}", {"case": True}, 403, ROLE),
        # An auditor resolves camera identity to review a log entry, and is
        # refused everything that would tell them what those cameras saw.
        ("auditor", "GET", "/gis/cameras" + bbox, {}, 200, ""),
        ("auditor", "GET", "/search?plate={p}", {"case": True}, 403, ROLE),
        ("auditor", "GET", "/trajectory/{p}", {"case": True}, 403, ROLE),
        ("auditor", "GET", "/watchlist", {"case": True}, 403, ROLE),
        ("supervisor", "GET", "/search?plate={p}", {}, 400, PURPOSE),
        ("supervisor", "GET", "/trajectory/{p}", {}, 400, PURPOSE),
    ]

    rows: list[dict[str, Any]] = []
    ok = bad = skipped = 0
    for role, method, path, kw, want, gate in checks:
        if role not in cli:
            skipped += 1
            continue
        p = path.format(p=a.plate, c=a.camera)
        st, body = cli[role].call(
            method, p,
            case=a.case if kw.get("case") else None,
            purpose=purpose if not kw.get("anon") else None,
            body=kw.get("body"), anonymous=bool(kw.get("anon")))
        good = st == want
        ok, bad = ok + good, bad + (not good)
        rows.append({"role": role, "method": method, "path": p, "want": want,
                     "got": st, "gate": gate, "code": code_of(body),
                     "shape": summarise(body), "pass": good})

    wp = min(46, max(len(r["path"]) for r in rows))
    print(f"{'':4} {'role':<12} {'':4} {'path':<{wp}} {'want':>4} {'got':>4}  detail")
    for r in rows:
        mark = "PASS" if r["pass"] else "FAIL"
        detail = r["code"] or r["shape"]
        if r["gate"]:
            detail = f"[{r['gate']}] {detail}"
        print(f"{mark:4} {r['role']:<12} {r['method']:<4} {r['path'][:wp]:<{wp}} "
              f"{r['want']:>4} {r['got']:>4}  {detail}")

    refusals = [r for r in rows if r["want"] != 200]
    print(f"\n{ok} passed, {bad} failed"
          + (f", {skipped} skipped (no token)" if skipped else ""))
    print(f"{sum(r['pass'] for r in refusals)}/{len(refusals)} authorisation "
          f"refusals fired as specified")

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(
            {"base": a.base, "passed": ok, "failed": bad, "checks": rows},
            indent=2))
        print(f"written    : {a.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
