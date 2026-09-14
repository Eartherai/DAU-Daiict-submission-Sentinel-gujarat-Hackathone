"""Copilot endpoint. Optional, read-only, and never in the mandatory chain."""
from __future__ import annotations

import os
from io import BytesIO
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from saakshya.api.deps import AuthDep, ConcurrencyGuard, StateDep, access_error
from saakshya.security import AccessError, Permission

router = APIRouter(prefix="/copilot", tags=["copilot"])


class Ask(BaseModel):
    #: Bounded because an unbounded prompt is both a cost and an injection
    #: surface. Long questions are a sign the officer wants a report, not a chat.
    question: str = Field(min_length=3, max_length=2000)


class Scene(BaseModel):
    camera_id: str = Field(min_length=1, max_length=64)


def _backend_for(request: Request | None):
    """Per-request provider. The header is a session switch, not a secret.

    `X-AI-Provider: local` keeps government data on this host. `gemini` uses
    the configured keys. Anything else follows the process default.
    """
    from saakshya.copilot.backends import backend_from_header
    value = None
    if request is not None:
        value = request.headers.get("x-ai-provider")
    return backend_from_header(value)


def _copilot(state: StateDep, request: Request | None = None):
    """One copilot per application, built lazily.

    Held on `AppState` as a declared field rather than stashed by name, so the
    attribute exists whether or not anyone has asked for a copilot yet. A
    request that names a provider gets its own orchestrator so two officers
    toggling Gemini do not steal each other's backend.
    """
    from saakshya.copilot import Copilot
    header = request.headers.get("x-ai-provider") if request is not None else None
    if header:
        return Copilot(state.investigation, state.cases,
                       backend=_backend_for(request))
    if state.copilot is None:
        state.copilot = Copilot(state.investigation, state.cases)
    return state.copilot


def _vision_enabled() -> bool:
    return os.environ.get("SAAKSHYA_GEMINI_VISION", "").lower() in (
        "1", "true", "yes", "on")


@router.get("/describe", summary="What the copilot is and what it may do")
async def describe(state: StateDep, ctx: AuthDep,
                   request: Request) -> dict[str, Any]:
    return _copilot(state, request).describe()


@router.post("/ask", summary="Ask the copilot a question about an investigation")
async def ask(state: StateDep, ctx: AuthDep, body: Ask,
              request: Request) -> dict[str, Any]:
    """Runs under the caller's own permissions and purpose binding.

    A question that would require a purpose-bound tool without `X-Case-Id` and
    `X-Purpose` produces a refusal from the tool, which the copilot reports as a
    refusal — it does not silently answer from thin air.
    """
    try:
        async with ConcurrencyGuard(state.search_sem, what="searches"):
            answer = _copilot(state, request).ask(ctx, body.question)
    except AccessError as exc:
        raise access_error(exc) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail={
            "code": "NOT_IMPLEMENTED", "message": str(exc)}) from exc
    return answer.to_dict()


@router.post("/scene", summary="Caption one still. Leaves the host. Not evidence.")
async def scene(state: StateDep, ctx: AuthDep, body: Scene) -> dict[str, Any]:
    """Optional Gemini caption of one downscaled ingest still.

    Off unless `SAAKSHYA_GEMINI_VISION=1`. The still is not stored as an
    observation, is not a plate read, and is labelled as having left the
    deployment. Enhancement and identity are refused by the prompt and by the
    copilot's `refuse_imagery` tool; this path does not undo that.
    """
    if not _vision_enabled():
        raise HTTPException(status_code=403, detail={
            "code": "VISION_DISABLED",
            "message": ("Still description is off. Detection and ANPR stay on "
                        "this host. Set SAAKSHYA_GEMINI_VISION=1 only for a "
                        "supervised demo, and say the frame left the deployment.")})
    try:
        ctx.principal.require(Permission.CAMERA_READ)
        cam = state.store.get_camera(body.camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail={
                "code": "NOT_FOUND",
                "message": f"no such camera: {body.camera_id}"})
        ctx.principal.require_scope(cam.get("district"))
    except AccessError as exc:
        raise access_error(exc) from exc

    jpeg = _preview_jpeg(body.camera_id)
    if jpeg is None:
        raise HTTPException(status_code=404, detail={
            "code": "NO_FRAME",
            "message": "no ingest still for this camera; the wall was not opened"})

    from saakshya.copilot.backends import GeminiBackend
    backend = GeminiBackend()
    if not backend.available:
        raise HTTPException(status_code=503, detail={
            "code": "GEMINI_UNCONFIGURED",
            "message": "no Gemini key in the environment"})
    result = backend.describe_still(jpeg, camera_id=body.camera_id)
    if result.get("error"):
        raise HTTPException(status_code=502, detail={
            "code": "GEMINI_FAILED",
            "message": ("the caption could not be produced; the still is "
                        "unchanged on this host"),
            "error": result["error"]})
    ctx.audit(state.store, "copilot_scene", target=body.camera_id,
              result_count=1)
    return result


def _preview_jpeg(camera_id: str) -> bytes | None:
    """Ingest still, downscaled. Never opens RTSP for a caption."""
    from PIL import Image

    from saakshya.live.preview import ingest_is_publishing, read_preview

    age = 3600.0 if ingest_is_publishing() else 90.0
    got = read_preview(camera_id, max_age_s=age)
    if got is None:
        return None
    data, *_rest = got
    image = Image.open(BytesIO(data)).convert("RGB")
    image.thumbnail((512, 512))
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=45, optimize=True)
    return buf.getvalue()
