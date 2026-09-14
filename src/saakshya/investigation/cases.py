"""Cases: the container that makes a search accountable.

Deliberately small. This is not case management — there is no workflow engine,
no assignment, no SLA, no approvals chain. A real force already owns CCTNS for
that, and rebuilding it here would be both wasted effort and a worse product.

What a case exists for here is narrower and load-bearing: it is the thing a
purpose-bound search attaches to. Without it, "why was this vehicle's movement
history retrieved" has no answer that survives the officer who ran it. With it,
every search, every trajectory and every evidence export carries a case id into
the hash-chained audit log, and the case itself records who opened it and why.

Attached items are stored as snapshots rather than as live references. A
trajectory attached on Tuesday must still read as it did on Tuesday, even after
more observations arrive and the solver ranks the hypotheses differently — an
investigator's note about "hypothesis A" is worthless if hypothesis A silently
changes underneath it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update

from saakshya.security import AuthContext, Permission
from saakshya.store import schema as S
from saakshya.store.repository import Store, from_us, now_us

ITEM_TYPES = ("target", "observation", "trajectory", "alert", "evidence", "camera")


def _iso(t: datetime | None) -> str | None:
    """A stored timestamp should never be NULL, but a case export must not fail
    on one — the export is what an oversight body reads."""
    return t.isoformat() if t else None


@dataclass
class Case:
    case_id: str
    title: str
    purpose: str
    opened_by: str
    fir_number: str | None = None
    district: str | None = None
    classification: str | None = None
    status: str = "OPEN"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "title": self.title, "purpose": self.purpose,
            "opened_by": self.opened_by, "fir_number": self.fir_number,
            "district": self.district, "classification": self.classification,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseService:
    def __init__(self, store: Store) -> None:
        self.store = store

    # -- lifecycle ---------------------------------------------------------- #
    def create(self, ctx: AuthContext, *, case_id: str, title: str, purpose: str,
               fir_number: str | None = None, district: str | None = None,
               classification: str | None = None) -> Case:
        ctx.authorise(Permission.CASE_WRITE, district=district)
        if len(purpose.strip()) < AuthContext.MIN_PURPOSE_CHARS:
            raise ValueError("a case must state a purpose of at least "
                             f"{AuthContext.MIN_PURPOSE_CHARS} characters")
        with self.store.engine.begin() as c:
            if c.execute(select(S.cases.c.case_id)
                         .where(S.cases.c.case_id == case_id)).first():
                raise ValueError(f"case {case_id} already exists")
            t = now_us()
            c.execute(insert(S.cases).values(
                case_id=case_id, title=title, purpose=purpose,
                fir_number=fir_number, district=district,
                classification=classification, status="OPEN",
                opened_by=ctx.principal.user_id, created_at_us=t, updated_at_us=t))
        ctx.audit(self.store, "case_open", target=case_id)
        return self.get(ctx, case_id)  # type: ignore[return-value]

    def get(self, ctx: AuthContext, case_id: str) -> Case | None:
        ctx.principal.require(Permission.CASE_READ)
        with self.store.engine.connect() as c:
            r = c.execute(select(S.cases).where(S.cases.c.case_id == case_id)).first()
        if not r:
            return None
        m = r._mapping
        # Object-level authorisation, not just endpoint-level: holding
        # CASE_READ does not entitle a district officer to another district's case.
        if m["district"]:
            ctx.principal.require_scope(m["district"])
        return Case(case_id=m["case_id"], title=m["title"], purpose=m["purpose"],
                    opened_by=m["opened_by"], fir_number=m["fir_number"],
                    district=m["district"], classification=m["classification"],
                    status=m["status"], created_at=from_us(m["created_at_us"]),
                    updated_at=from_us(m["updated_at_us"]))

    def list_cases(self, ctx: AuthContext, *, status: str | None = None,
                   limit: int = 100) -> list[Case]:
        ctx.principal.require(Permission.CASE_READ)
        q = select(S.cases)
        if status:
            q = q.where(S.cases.c.status == status)
        scope = ctx.principal.scope_filter()
        if scope is not None:
            q = q.where(S.cases.c.district.in_(list(scope)))
        with self.store.engine.connect() as c:
            rows = list(c.execute(q.order_by(S.cases.c.updated_at_us.desc()).limit(limit)))
        return [Case(case_id=m["case_id"], title=m["title"], purpose=m["purpose"],
                     opened_by=m["opened_by"], fir_number=m["fir_number"],
                     district=m["district"], classification=m["classification"],
                     status=m["status"], created_at=from_us(m["created_at_us"]),
                     updated_at=from_us(m["updated_at_us"]))
                for m in (r._mapping for r in rows)]

    def close(self, ctx: AuthContext, case_id: str, *, reason: str) -> None:
        ctx.authorise(Permission.CASE_WRITE)
        with self.store.engine.begin() as c:
            c.execute(update(S.cases).where(S.cases.c.case_id == case_id).values(
                status="CLOSED", closed_by=ctx.principal.user_id,
                closed_reason=reason, updated_at_us=now_us()))
        ctx.audit(self.store, "case_close", target=case_id)

    # -- attachments -------------------------------------------------------- #
    def attach(self, ctx: AuthContext, case_id: str, *, item_type: str,
               item_ref: str, payload: dict[str, Any] | None = None,
               note: str | None = None) -> dict[str, Any]:
        ctx.authorise(Permission.CASE_WRITE)
        if item_type not in ITEM_TYPES:
            raise ValueError(f"item_type must be one of {ITEM_TYPES}")
        if self.get(ctx, case_id) is None:
            raise ValueError(f"no such case: {case_id}")
        row = {
            "case_id": case_id, "item_type": item_type, "item_ref": item_ref,
            "payload": json.dumps(payload or {}, default=str),
            "added_by": ctx.principal.user_id, "note": note,
            "created_at_us": now_us(),
        }
        with self.store.engine.begin() as c:
            exists = c.execute(select(S.case_items.c.id).where(
                S.case_items.c.case_id == case_id,
                S.case_items.c.item_type == item_type,
                S.case_items.c.item_ref == item_ref)).first()
            if exists:
                # Re-attaching refreshes the snapshot rather than duplicating it.
                c.execute(update(S.case_items).where(S.case_items.c.id == exists[0])
                          .values(payload=row["payload"], note=note,
                                  created_at_us=row["created_at_us"]))
            else:
                c.execute(insert(S.case_items).values(**row))
            c.execute(update(S.cases).where(S.cases.c.case_id == case_id)
                      .values(updated_at_us=now_us()))
        ctx.audit(self.store, "case_attach", target=f"{case_id}:{item_type}:{item_ref}")
        return {"case_id": case_id, "item_type": item_type, "item_ref": item_ref,
                "replaced": bool(exists)}

    def items(self, ctx: AuthContext, case_id: str,
              item_type: str | None = None) -> list[dict[str, Any]]:
        ctx.principal.require(Permission.CASE_READ)
        q = select(S.case_items).where(S.case_items.c.case_id == case_id)
        if item_type:
            q = q.where(S.case_items.c.item_type == item_type)
        with self.store.engine.connect() as c:
            rows = list(c.execute(q.order_by(S.case_items.c.created_at_us)))
        out = []
        for r in rows:
            m = dict(r._mapping)
            m["payload"] = json.loads(m["payload"] or "{}")
            created = from_us(m.pop("created_at_us"))
            m["created_at"] = created.isoformat() if created else None
            out.append(m)
        return out

    def note(self, ctx: AuthContext, case_id: str, body: str) -> dict[str, Any]:
        ctx.authorise(Permission.CASE_WRITE)
        if not body.strip():
            raise ValueError("an empty note is not a note")
        with self.store.engine.begin() as c:
            c.execute(insert(S.case_notes).values(
                case_id=case_id, author=ctx.principal.user_id,
                body=body.strip(), created_at_us=now_us()))
            c.execute(update(S.cases).where(S.cases.c.case_id == case_id)
                      .values(updated_at_us=now_us()))
        ctx.audit(self.store, "case_note", target=case_id)
        return {"case_id": case_id, "author": ctx.principal.user_id}

    def notes(self, ctx: AuthContext, case_id: str) -> list[dict[str, Any]]:
        ctx.principal.require(Permission.CASE_READ)
        with self.store.engine.connect() as c:
            rows = list(c.execute(select(S.case_notes)
                                  .where(S.case_notes.c.case_id == case_id)
                                  .order_by(S.case_notes.c.created_at_us)))
        return [{"author": m["author"], "body": m["body"],
                 "created_at": _iso(from_us(m["created_at_us"]))}
                for m in (r._mapping for r in rows)]

    # -- export -------------------------------------------------------------- #
    def export(self, ctx: AuthContext, case_id: str) -> dict[str, Any]:
        """A case file: everything attached, plus the audit trail for this case.

        The audit trail is included in the export rather than kept elsewhere,
        because the value of the export to a court or an oversight body is that
        it shows what was done *and* by whom, in one document.
        """
        ctx.authorise(Permission.CASE_READ)
        case = self.get(ctx, case_id)
        if case is None:
            raise ValueError(f"no such case: {case_id}")
        with self.store.engine.connect() as c:
            audit = [dict(r._mapping) for r in c.execute(
                select(S.audit_log).where(S.audit_log.c.case_id == case_id)
                .order_by(S.audit_log.c.id))]
        for a in audit:
            a["t"] = _iso(from_us(a.pop("t_us")))
        chain_ok, chain_err = self.store.verify_audit_chain()
        ctx.audit(self.store, "case_export", target=case_id, result_count=len(audit))
        return {
            "case": case.to_dict(),
            "items": self.items(ctx, case_id),
            "notes": self.notes(ctx, case_id),
            "audit_trail": audit,
            "audit_chain_verified": chain_ok,
            "audit_chain_error": chain_err,
            "exported_by": ctx.principal.user_id,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "caveat": ("Attached items are snapshots taken when they were "
                       "attached. Re-running a search today may produce a "
                       "different result as more observations arrive."),
        }
