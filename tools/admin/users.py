#!/usr/bin/env python3
"""User and token administration. Host-side only, on purpose.

There is no credential-issuing HTTP endpoint. Minting a token is minting a
credential, and requiring shell access on the host to do it is a materially
higher bar than requiring an ADMIN session on the network.

A minted token is printed once and never stored in recoverable form — only its
SHA-256 digest reaches the database. If it is lost, mint another and revoke the
old one; there is no recovery path, and that is the intended property.

    python tools/admin/users.py list
    python tools/admin/users.py add   --user officer.ahd --role INVESTIGATOR \\
                                      --districts Ahmedabad --name "PSI A Patel"
    python tools/admin/users.py token --user officer.ahd --days 7
    python tools/admin/users.py disable --user officer.ahd
    python tools/admin/users.py roles
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.security import ROLE_PERMISSIONS, Role, TokenService
from saakshya.store import Store

STATEWIDE_ONLY = {Role.ADMIN, Role.SUPERVISOR, Role.AUDITOR, Role.SERVICE}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("SAAKSHYA_DB",
                                                   "sqlite:///var/saakshya.db"))
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="users, roles and jurisdictions")
    sub.add_parser("roles", help="the role → permission table")

    a = sub.add_parser("add", help="create or update a user")
    a.add_argument("--user", required=True)
    a.add_argument("--role", required=True, choices=[str(r) for r in Role])
    a.add_argument("--name", default="")
    a.add_argument("--department", default=None)
    a.add_argument("--districts", default="",
                   help="comma-separated; omit only for statewide roles")
    a.add_argument("--badge", default=None)

    t = sub.add_parser("token", help="mint a bearer token (printed once)")
    t.add_argument("--user", required=True)
    t.add_argument("--days", type=float, default=7.0)
    t.add_argument("--label", default="")

    d = sub.add_parser("disable", help="disable a user; existing tokens stop working")
    d.add_argument("--user", required=True)

    args = ap.parse_args()
    store = Store(args.db)
    store.create_all()
    ts = TokenService(store)

    if args.command == "list":
        rows = ts.list_users()
        if not rows:
            print("no users. Create one with `add`.")
            return 0
        print(f"{'user':24} {'role':13} {'jurisdiction':22} {'enabled':8} name")
        for u in rows:
            scope = ", ".join(u["districts"]) if u["districts"] else "STATE"
            print(f"{u['user_id']:24} {u['role']:13} {scope:22} "
                  f"{'yes' if u['enabled'] else 'NO':8} {u['display_name']}")
        return 0

    if args.command == "roles":
        for role, perms in ROLE_PERMISSIONS.items():
            print(f"\n{role}")
            for p in sorted(str(x) for x in perms):
                print(f"  {p}")
        print("\nADMIN holds no search permission and AUDITOR holds no evidence "
              "permission.\nRunning the estate and investigating people are "
              "different jobs.")
        return 0

    if args.command == "add":
        role = Role(args.role)
        districts = tuple(d.strip() for d in args.districts.split(",") if d.strip())
        if not districts and role not in STATEWIDE_ONLY:
            print(f"REFUSED: {role} may not hold statewide scope. Name the "
                  f"districts with --districts.", file=sys.stderr)
            return 2
        p = ts.upsert_user(args.user, role, display_name=args.name,
                           department=args.department, districts=districts,
                           badge_no=args.badge)
        scope = ", ".join(p.districts) if p.districts else "STATE"
        print(f"{p.user_id}: {p.role}, jurisdiction {scope}")
        print(f"permissions: {', '.join(sorted(str(x) for x in p.permissions))}")
        print("\nMint a token with:  "
              f"python tools/admin/users.py token --user {p.user_id}")
        return 0

    if args.command == "token":
        try:
            token = ts.mint(args.user, label=args.label,
                            ttl=timedelta(days=args.days) if args.days else None)
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(f"\n{args.user} — valid for {args.days:g} day(s)\n")
        print(f"  {token}\n")
        print("Shown once. Only its SHA-256 digest is stored, so it cannot be "
              "recovered.\nDo not write it into any file in this repository.")
        return 0

    if args.command == "disable":
        ts.disable_user(args.user)
        print(f"{args.user} disabled; existing tokens will no longer authenticate")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
