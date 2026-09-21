"""Camera onboarding: bulk, manual, and API.

Model 1 is the compulsory model and asks the registry to support bulk import,
manual entry and API-based onboarding, plus export. The platform could grade a
camera's capability and place it on a map, but it had no way to *put one in* —
every camera present had been seeded by a script. A registry you cannot onboard
into is a report, not a registry.

Two rules shape what follows.

An import either applies or it does not. A partial import leaves an operator
unable to say which half of a departmental spreadsheet landed, so rows are
validated first and the whole batch is refused if any row is bad, with the row
number and the reason. `dry_run` runs exactly the same validation and writes
nothing, which is how a department checks a file before committing it.

Onboarding must not quietly overwrite curation. `upsert_camera` already
protects fields a probe cannot see; here the caller has to ask to update an
existing camera by setting `update_existing`, so a re-uploaded spreadsheet
cannot silently rewrite positions that were corrected by hand.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from saakshya.api.deps import AuthDep, StateDep, access_error
from saakshya.security import AccessError, Permission

router = APIRouter(prefix="/registry", tags=["registry"])

#: Everything a department can supply about a camera. `camera_id` is the only
#: required field: a registry's purpose is to hold what is known and report
#: what is not, so a row carrying nothing but an identifier is a legitimate
#: entry that the gap report will then name.
FIELDS = (
    "camera_id", "name", "department", "district", "site", "lat", "lon",
    "vendor", "model_name", "camera_type", "vms", "rtsp_url", "hls_url",
    "whep_url", "codec", "width", "height", "declared_fps",
    "storage_location", "retention_days", "tier", "owner", "region", "road",
    "integration_model", "maintenance_status", "quality_note",
)
_FLOAT = {"lat", "lon"}
_INT = {"width", "height", "declared_fps", "retention_days"}


class CameraIn(BaseModel):
    """One camera as a department describes it."""

    camera_id: str = Field(min_length=1, max_length=64)
    name: str | None = None
    department: str | None = None
    district: str | None = None
    site: str | None = None
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    vendor: str | None = None
    model_name: str | None = None
    camera_type: str | None = None
    vms: str | None = None
    rtsp_url: str | None = None
    hls_url: str | None = None
    whep_url: str | None = None
    codec: str | None = None
    width: int | None = Field(default=None, ge=0, le=65535)
    height: int | None = Field(default=None, ge=0, le=65535)
    declared_fps: int | None = Field(default=None, ge=0, le=1000)
    storage_location: str | None = None
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    tier: str | None = None
    owner: str | None = None
    region: str | None = None
    road: str | None = None
    integration_model: str | None = None
    maintenance_status: str | None = None
    quality_note: str | None = None


class ImportRequest(BaseModel):
    cameras: list[CameraIn] = Field(min_length=1, max_length=20_000)
    #: Refuse rows whose camera_id already exists unless this is set, so a
    #: re-uploaded spreadsheet cannot silently rewrite curated positions.
    update_existing: bool = False
    #: Validate and report, write nothing.
    dry_run: bool = False


def _coerce_csv_row(row: dict[str, str], line: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw in row.items():
        field = (key or "").strip()
        if field not in FIELDS:
            continue
        value = (raw or "").strip()
        if value == "":
            continue
        try:
            if field in _FLOAT:
                out[field] = float(value)
            elif field in _INT:
                out[field] = int(value)
            else:
                out[field] = value
        except ValueError:
            raise HTTPException(status_code=422, detail={
                "code": "BAD_ROW",
                "message": (f"line {line}: {field}={value!r} is not a "
                            f"{'number' if field in _FLOAT else 'whole number'}"),
            }) from None
    return out


def _apply(state: Any, rows: list[CameraIn], *, update_existing: bool,
           dry_run: bool) -> dict[str, Any]:
    """Validate the whole batch, then write it — or neither."""
    seen: set[str] = set()
    created: list[str] = []
    updated: list[str] = []
    for i, cam in enumerate(rows, start=1):
        cid = cam.camera_id.strip()
        if not cid:
            raise HTTPException(status_code=422, detail={
                "code": "BAD_ROW", "message": f"row {i}: camera_id is empty"})
        if cid in seen:
            raise HTTPException(status_code=422, detail={
                "code": "DUPLICATE_ROW",
                "message": f"row {i}: {cid} appears more than once in this batch"})
        seen.add(cid)
        exists = state.store.get_camera(cid) is not None
        if exists and not update_existing:
            raise HTTPException(status_code=409, detail={
                "code": "ALREADY_ONBOARDED",
                "message": (f"row {i}: {cid} is already onboarded. Re-send with "
                            "update_existing=true to amend it."),
            })
        (updated if exists else created).append(cid)

    if not dry_run:
        for cam in rows:
            payload = {k: v for k, v in cam.model_dump().items() if v is not None}
            payload["camera_id"] = cam.camera_id.strip()
            payload.setdefault("enabled", True)
            state.store.upsert_camera(payload)

    return {
        "accepted": len(rows),
        "created": len(created),
        "updated": len(updated),
        "dry_run": dry_run,
        "camera_ids": (created + updated)[:200],
        "note": ("Validated only; nothing was written." if dry_run else
                 "Applied. Fields no department supplied are reported by "
                 "/registry/gaps rather than invented."),
    }


@router.post("/cameras/import", summary="Bulk camera onboarding (JSON)")
async def import_cameras(state: StateDep, ctx: AuthDep, body: ImportRequest
                         ) -> dict[str, Any]:
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
    except AccessError as exc:
        raise access_error(exc) from exc
    return _apply(state, body.cameras,
                  update_existing=body.update_existing, dry_run=body.dry_run)


@router.post("/cameras/import.csv", summary="Bulk camera onboarding (CSV)")
async def import_cameras_csv(
    state: StateDep, ctx: AuthDep, request: Request,
    update_existing: bool = False, dry_run: bool = False,
) -> dict[str, Any]:
    """The same import, from the spreadsheet a department actually holds.

    The header names the columns; unknown columns are ignored rather than
    refused, because a departmental export carries operational columns that are
    none of this registry's business.
    """
    try:
        ctx.principal.require(Permission.ADMIN_WRITE)
    except AccessError as exc:
        raise access_error(exc) from exc
    raw = (await request.body()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "camera_id" not in [
            (f or "").strip() for f in reader.fieldnames]:
        raise HTTPException(status_code=422, detail={
            "code": "NO_CAMERA_ID",
            "message": "the CSV header must include a camera_id column"})
    rows = [CameraIn(**_coerce_csv_row(r, line))
            for line, r in enumerate(reader, start=2)]
    if not rows:
        raise HTTPException(status_code=422, detail={
            "code": "EMPTY", "message": "the CSV carried no rows"})
    return _apply(state, rows, update_existing=update_existing, dry_run=dry_run)


@router.get("/cameras/export.csv", summary="Export the registry",
            response_class=PlainTextResponse)
async def export_cameras(
    state: StateDep, ctx: AuthDep,
    department: str | None = None,
    include_slots: bool = False,
    limit: Annotated[int, Query(ge=1, le=100_000)] = 100_000,
) -> PlainTextResponse:
    """The registry as a file a department can read, check and send back.

    Round-trips with the importer: the columns written here are the columns it
    accepts, so an export can be corrected in a spreadsheet and re-imported.
    """
    try:
        ctx.principal.require(Permission.CAMERA_READ)
    except AccessError as exc:
        raise access_error(exc) from exc

    rows = state.store.list_cameras()
    if not include_slots:
        rows = [r for r in rows
                if not str(r.get("camera_id", "")).startswith("CTL-")]
    if department:
        want = department.strip().lower()
        rows = [r for r in rows
                if (r.get("department") or "").strip().lower() == want]
    rows = rows[:limit]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(FIELDS), extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("" if r.get(k) is None else r.get(k))
                         for k in FIELDS})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="saakshya-registry.csv"'})
