"""Language-model backends for the copilot.

The copilot is the only component in this system that depends on a language
model, and it is optional by construction: with no model configured the API
still answers, and it says plainly that the assistant is unavailable and the
deterministic tools are not. Nothing in the mandatory chain — ingest, search,
graph, trajectory, watchlist, alert, evidence, verification — imports anything
from this module.

No credential is ever read from a file in this repository. The key comes from
the environment or it does not exist.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger("saakshya.copilot.backends")

#: Measured 22 Sep 2026 against the Gemini Enterprise Agent Platform project
#: supplied for this submission. `gemini-3.5-flash` answered text and vision;
#: `gemini-3-flash-preview` and `gemini-2.5-flash` likewise; `gemini-2.5-pro`
#: answered text. `gemini-3.5-pro`, `gemini-3-pro-preview`, `gemini-flash-latest`
#: and `gemini-2.0-flash` are not published to this project and return 404.
#: The older aliases stay in the list because a deployment holding an AI Studio
#: key reaches a different catalogue, and the loop simply walks past a 404.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_MODEL_FALLBACKS = (
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-2.0-flash",
)
GEMINI_VISION_MODEL = "gemini-3.5-flash"
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"

#: Two different Google products answer to the name "Gemini API", and a key
#: minted for one is refused by the other. An AI Studio key (`AIza…`) belongs
#: to the Gemini Developer API. A console-link or express-mode key (`AQ.…`)
#: belongs to the Gemini Enterprise Agent Platform, which serves the same
#: `generateContent` shape from Vertex hostnames. Sending the Enterprise key to
#: the Developer API returns `API_KEY_SERVICE_BLOCKED`, which reads like a dead
#: key and is not one — so the endpoint is chosen from the key, not assumed.
GEMINI_DEVELOPER_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_ENTERPRISE_HOST = "https://aiplatform.googleapis.com/v1"
ENTERPRISE_KEY_PREFIX = "AQ."


def _enterprise_key(key: str) -> bool:
    return key.startswith(ENTERPRISE_KEY_PREFIX)


def gemini_endpoint(model: str, key: str) -> str:
    """The `generateContent` URL for this key's platform.

    Measured 22 Sep 2026: the Enterprise platform's unqualified
    `/publishers/google/models/…` path is load-balanced across regions, and the
    published model set differs per region — the same request for
    `gemini-3.5-flash` returned 200, then 404 naming `asia-southeast1`, then 200
    again. Pinning `locations/global` was 6/6 on two models where
    `us-central1` was 0/6 on one of them. A demonstration cannot rest on which
    region a request happens to land in, so the project-qualified global path is
    used whenever the project is known, and the unqualified path only as a
    fallback for a deployment that has not set one.
    """
    if not _enterprise_key(key):
        return f"{GEMINI_DEVELOPER_BASE}/models/{model}:generateContent"
    project = (os.environ.get("SAAKSHYA_GEMINI_PROJECT") or "").strip()
    location = (os.environ.get("SAAKSHYA_GEMINI_LOCATION") or "global").strip()
    if project:
        return (f"{GEMINI_ENTERPRISE_HOST}/projects/{project}/locations/"
                f"{location}/publishers/google/models/{model}:generateContent")
    return (f"{GEMINI_ENTERPRISE_HOST}/publishers/google/models/"
            f"{model}:generateContent")

_GEMINI_TYPE = {
    "object": "OBJECT", "string": "STRING", "number": "NUMBER",
    "integer": "INTEGER", "boolean": "BOOLEAN", "array": "ARRAY",
}


def collect_gemini_keys(explicit: str | None = None) -> list[str]:
    """Keys from the environment only. Never from a file in this repository."""
    found: list[str] = []
    if explicit and explicit.strip():
        found.append(explicit.strip())
    for name in ("SAAKSHYA_GEMINI_KEY", "GEMINI_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            found.append(value)
    for part in (os.environ.get("SAAKSHYA_GEMINI_KEYS") or "").split(","):
        value = part.strip()
        if value:
            found.append(value)
    seen: set[str] = set()
    unique: list[str] = []
    for key in found:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def gemini_configured() -> bool:
    return bool(collect_gemini_keys())


def backend_from_header(value: str | None) -> LLMBackend:
    """Per-request switch from `X-AI-Provider`. Unknown values follow default.

    `local` / `rules` / `off` keep data on this host. `gemini` uses the
    configured keys and falls back to rules if none are present. This is a
    session preference, not a credential.
    """
    choice = (value or "").strip().lower()
    if choice in ("local", "rules", "off"):
        return RuleBackend()
    if choice == "disabled":
        return UnavailableBackend()
    if choice == "gemini":
        backend = GeminiBackend()
        return backend if backend.available else RuleBackend()
    if choice == "anthropic":
        backend = AnthropicBackend()
        return backend if backend.available else RuleBackend()
    return default_backend()


def _gemini_schema(node: Any) -> Any:
    """Gemini function declarations want uppercase JSON-schema types."""
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "type" and isinstance(value, str):
            out[key] = _GEMINI_TYPE.get(value.lower(), value.upper())
        elif key == "properties" and isinstance(value, dict):
            out[key] = {pk: _gemini_schema(pv) for pk, pv in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = _gemini_schema(value)
        elif key == "default":
            continue
        else:
            out[key] = value
    return out


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    #: Gemini 3 echoes this on the next turn or the request is 400.
    thought_signature: str | None = None


@dataclass
class Turn:
    """One model turn: either tool calls, or a final answer. Never both used."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end"
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMBackend(Protocol):
    name: str
    available: bool

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> Turn: ...


class UnavailableBackend:
    """The default. Refuses clearly rather than degrading into guesswork."""

    name = "unavailable"
    available = False
    reason = ("No language model is configured. Set SAAKSHYA_LLM_KEY (and "
              "optionally SAAKSHYA_LLM_MODEL) in the environment to enable the "
              "copilot. Every deterministic capability — search, trajectory, "
              "watchlist, alerts, evidence, verification — is unaffected.")

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> Turn:
        return Turn(text=self.reason, stop_reason="unavailable")


class ScriptedBackend:
    """Deterministic backend for tests and offline demonstration.

    It exists so the copilot's *orchestration* — tool dispatch, argument
    validation, grounding verification, injection handling — can be tested
    exhaustively and repeatably without a network call or a model's whims. The
    behaviour under test is ours; the model's job is only to choose tools.
    """

    name = "scripted"
    available = True

    def __init__(self, script: list[Turn]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> Turn:
        self.calls.append({"system": system, "messages": messages,
                           "tools": [t["name"] for t in tools]})
        if not self.script:
            return Turn(text="(scripted backend exhausted)", stop_reason="end")
        return self.script.pop(0)


class AnthropicBackend:
    """Anthropic Messages API over httpx. No SDK dependency.

    Kept small deliberately: this layer translates a tool schema and a response
    shape, and nothing else. All judgement about what is safe to say lives in
    the orchestrator, where it is testable without a model.
    """

    name = "anthropic"

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 timeout_s: float = 60.0) -> None:
        self.api_key = api_key or os.environ.get("SAAKSHYA_LLM_KEY") or ""
        self.model = model or os.environ.get("SAAKSHYA_LLM_MODEL",
                                             "claude-sonnet-4-5-20250929")
        self.timeout_s = timeout_s
        self.available = bool(self.api_key)

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> Turn:
        if not self.available:
            return UnavailableBackend().complete(system, messages, tools)
        import httpx
        body = {
            "model": self.model, "max_tokens": 2048, "system": system,
            "messages": messages, "tools": tools,
            # Low temperature: this is an evidence surface, not a writing aid.
            "temperature": 0.0,
        }
        r = httpx.post("https://api.anthropic.com/v1/messages", json=body,
                       headers={"x-api-key": self.api_key,
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json"},
                       timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()
        text_parts, calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(id=block["id"], name=block["name"],
                                      arguments=block.get("input") or {}))
        return Turn(text="\n".join(text_parts).strip(), tool_calls=calls,
                    stop_reason=data.get("stop_reason", "end"),
                    usage=data.get("usage", {}))


class GeminiBackend:
    """Google Gemini, for the same assistant role and under the same rules.

    Gemini is multimodal, which is useful for describing a scene or reading
    signage. It is deliberately *not* given authority over plate identity,
    watchlist matching, trajectory or evidence validity: those are decided by
    deterministic code that can be tested without a network, and an assistant
    that could overturn them would move the system's authority off the machine
    it runs on.

    Like the Anthropic backend, this translates a tool schema and a response
    shape and nothing else. Every judgement about what is safe to say stays in
    the orchestrator, where it is testable without a model.
    """

    name = "gemini"

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 timeout_s: float = 45.0) -> None:
        self._keys = collect_gemini_keys(api_key)
        # Kept so existing tests that pass api_key="" still see an empty
        # credential rather than a pool pulled from the environment.
        self.api_key = self._keys[0] if self._keys else (api_key or "")
        self.model = model or os.environ.get("SAAKSHYA_GEMINI_MODEL",
                                             DEFAULT_GEMINI_MODEL)
        self.timeout_s = timeout_s
        self.available = bool(self._keys)
        self.last_model = self.model

    def __repr__(self) -> str:
        return (f"GeminiBackend(model={self.model!r}, keys={len(self._keys)}, "
                f"available={self.available})")

    def _models(self) -> list[str]:
        ordered = [self.model, *GEMINI_MODEL_FALLBACKS]
        seen: set[str] = set()
        out: list[str] = []
        for name in ordered:
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    @staticmethod
    def _to_gemini(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Translate the Anthropic-shaped conversation the orchestrator builds.

        One conversation shape is maintained, not two: the orchestrator is the
        tested component and it should not learn a second dialect for every
        provider added.
        """
        names: dict[str, str] = {}
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_use" and block.get("id"):
                        names[str(block["id"])] = str(block.get("name") or "tool")

        out: list[dict[str, Any]] = []
        for m in messages:
            content = m.get("content")
            role = "user" if m.get("role") == "user" else "model"
            if isinstance(content, str):
                out.append({"role": role, "parts": [{"text": content}]})
                continue
            parts: list[dict[str, Any]] = []
            for block in content or []:
                kind = block.get("type")
                if kind == "text":
                    parts.append({"text": block["text"]})
                elif kind == "tool_use":
                    part: dict[str, Any] = {
                        "functionCall": {"name": block["name"],
                                         "args": block.get("input") or {}}}
                    if block.get("thought_signature"):
                        part["thoughtSignature"] = block["thought_signature"]
                    parts.append(part)
                elif kind == "tool_result":
                    raw = block.get("content", "")
                    try:
                        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
                    except json.JSONDecodeError:
                        parsed = {"result": raw}
                    if not isinstance(parsed, dict):
                        parsed = {"result": parsed}
                    name = (block.get("name")
                            or names.get(str(block.get("tool_use_id") or ""), "tool"))
                    parts.append({"functionResponse": {
                        "name": name, "response": parsed}})
            if parts:
                out.append({"role": role, "parts": parts})
        return out

    @staticmethod
    def _generation_config(*, thinking: bool = False,
                           max_output_tokens: int = 4096) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "temperature": 0.0,
            "maxOutputTokens": max_output_tokens,
        }
        if not thinking:
            # Newer Flash models spend the token budget on hidden thinking and
            # finish with empty content unless this is set.
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
        return cfg

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> Turn:
        if not self.available:
            return UnavailableBackend().complete(system, messages, tools)
        import httpx

        declarations = []
        for t in tools:
            parameters = t.get("input_schema") or t.get("parameters") or {
                "type": "object", "properties": {}}
            declarations.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": _gemini_schema(parameters),
            })
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": self._to_gemini(messages),
        }
        if declarations:
            payload["tools"] = [{"functionDeclarations": declarations}]
            payload["toolConfig"] = {
                "functionCallingConfig": {"mode": "AUTO"}}
        last_error: Exception | None = None
        for model in self._models():
            next_model = False
            for key in self._keys:
                for thinking in (False, True):
                    body = {**payload,
                            "generationConfig": self._generation_config(
                                thinking=thinking)}
                    url = gemini_endpoint(model, key)
                    try:
                        r = httpx.post(
                            url, json=body,
                            headers={"x-goog-api-key": key,
                                     "content-type": "application/json"},
                            timeout=self.timeout_s)
                    except (httpx.TimeoutException, TimeoutError) as exc:
                        last_error = exc
                        log.warning("gemini timeout on model %s", model)
                        break
                    if r.status_code in (429, 503):
                        last_error = httpx.HTTPStatusError(
                            f"Gemini {r.status_code} on {model}",
                            request=r.request, response=r)
                        log.warning("gemini %s on model %s; rotating key",
                                    r.status_code, model)
                        break
                    if r.status_code == 404:
                        last_error = httpx.HTTPStatusError(
                            f"Gemini model not available: {model}",
                            request=r.request, response=r)
                        log.warning("gemini 404 on model %s; trying a fallback",
                                    model)
                        next_model = True
                        break
                    if r.status_code == 400:
                        last_error = httpx.HTTPStatusError(
                            f"Gemini 400 on {model}: {(r.text or '')[:240]}",
                            request=r.request, response=r)
                        log.warning("gemini 400 on model %s: %s",
                                    model, (r.text or "")[:240])
                        if not thinking:
                            continue
                        # A schema or thought-signature error will 400 on every
                        # key and model. Spraying retries burns the demo quota.
                        raise last_error
                    try:
                        r.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        log.warning("gemini HTTP %s on model %s",
                                    r.status_code, model)
                        break
                    turn = self._parse(r.json(), model)
                    if turn.wants_tools or turn.text or turn.stop_reason != "MAX_TOKENS":
                        self.last_model = model
                        return turn
                    last_error = RuntimeError(
                        f"Gemini {model} finished {turn.stop_reason} with no content")
                    break
                if next_model:
                    break
        if last_error:
            raise last_error
        return Turn(text="", stop_reason="empty")

    @staticmethod
    def _parse(data: dict[str, Any], model: str) -> Turn:
        candidates = data.get("candidates") or []
        if not candidates:
            return Turn(text="", stop_reason="empty",
                        usage={"model": model, **(data.get("usageMetadata") or {})})
        text_parts, calls = [], []
        parts = (candidates[0].get("content") or {}).get("parts") or []
        for i, part in enumerate(parts):
            if part.get("thought"):
                continue
            if "functionCall" in part:
                fc = part["functionCall"]
                calls.append(ToolCall(
                    id=str(fc.get("id") or f"gemini{i}"),
                    name=fc.get("name", ""),
                    arguments=fc.get("args") or {},
                    thought_signature=part.get("thoughtSignature") or fc.get(
                        "thoughtSignature"),
                ))
            elif "text" in part:
                text_parts.append(part["text"])
        usage = dict(data.get("usageMetadata") or {})
        usage["model"] = model
        return Turn(text="\n".join(text_parts).strip(), tool_calls=calls,
                    stop_reason=candidates[0].get("finishReason", "end"),
                    usage=usage)

    def describe_still(self, jpeg: bytes, *, camera_id: str) -> dict[str, Any]:
        """Scene caption only. Not identity, not a plate read, not evidence.

        The still has already left the deployment when this is called. The
        caller is responsible for saying so on the surface that requested it.
        """
        if not self.available:
            return {"error": "gemini is not configured", "refused": True}
        import base64
        import httpx

        prompt = (
            "Describe this government CCTV still for an investigator. "
            "You may state lighting (day, night, infrared), weather, scene type "
            "(junction, gate, interior, road), whether a number plate is "
            "geometrically visible (yes / no / uncertain), and crowd density. "
            f"The registry id of this camera is {camera_id}. "
            "You must not name or identify any person, invent or read a "
            "registration mark, claim the still is evidence, or suggest the "
            "image was enhanced. If you cannot tell, say you cannot tell."
        )
        body = {
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": "image/jpeg",
                                 "data": base64.b64encode(jpeg).decode("ascii")}},
                {"text": prompt},
            ]}],
            "generationConfig": self._generation_config(max_output_tokens=512),
        }
        last_error = "unavailable"
        for model in (os.environ.get("SAAKSHYA_GEMINI_VISION_MODEL")
                      or GEMINI_VISION_MODEL, *self._models()):
            for key in self._keys:
                url = gemini_endpoint(model, key)
                try:
                    r = httpx.post(
                        url, json=body,
                        headers={"x-goog-api-key": key,
                                 "content-type": "application/json"},
                        timeout=self.timeout_s)
                except (httpx.TimeoutException, TimeoutError) as exc:
                    last_error = type(exc).__name__
                    continue
                if r.status_code in (429, 503, 404):
                    last_error = f"HTTP {r.status_code}"
                    continue
                if r.status_code >= 400:
                    last_error = f"HTTP {r.status_code}"
                    continue
                turn = self._parse(r.json(), model)
                if not turn.text:
                    last_error = "empty"
                    continue
                return {
                    "camera_id": camera_id,
                    "description": turn.text,
                    "model": model,
                    "left_the_deployment": True,
                    "evidence": False,
                    "note": ("This caption is not an observation, not a plate "
                             "read, and not a sealed exhibit. The still left "
                             "this host to reach Gemini."),
                }
        return {"error": last_error, "refused": True, "camera_id": camera_id,
                "left_the_deployment": True, "evidence": False}


#: `AI_PROVIDER` is the single switch for where assistant reasoning happens.
#: Named providers, so a deployment states its choice rather than having one
#: inferred from which key happens to be set:
#:
#:     disabled   no assistant at all
#:     local      deterministic rules over the same tools; nothing leaves the host
#:     anthropic  Claude, for free-form investigation questions
#:     gemini     Gemini, for free-form and multimodal questions
#:
#: `auto` (the default) picks the best available and falls back to `local`.
#: Whatever is chosen, **no core feature depends on it**: search, trajectory,
#: watchlist, alerting and evidence are decided by deterministic code, and the
#: application is expected to run with AI_PROVIDER=disabled.
PROVIDERS = ("auto", "disabled", "local", "anthropic", "gemini")


def _provider_setting() -> str:
    # SAAKSHYA_COPILOT=off predates this and stays honoured: a deployment that
    # switched the copilot off should not have it come back because the setting
    # was renamed underneath them.
    if os.environ.get("SAAKSHYA_COPILOT", "").lower() in ("off", "0", "false"):
        return "disabled"
    choice = os.environ.get("AI_PROVIDER", "").strip().lower() or "auto"
    if choice not in PROVIDERS:
        log.warning("AI_PROVIDER=%r is not one of %s; treating it as 'auto'. "
                    "A misspelling must not silently enable a provider.",
                    choice, ", ".join(PROVIDERS))
        return "auto"
    return choice


def default_backend() -> LLMBackend:
    """The backend this deployment has asked for, or the best one available.

    Falls back to rules rather than to nothing: an assistant that answers half
    the questions with no external dependency is worth more than one that
    declines all of them, and for government CCTV the configuration where no
    data leaves the system should be what you get without asking.
    """
    choice = _provider_setting()
    if choice == "disabled":
        return UnavailableBackend()
    if choice == "local":
        return RuleBackend()
    if choice == "anthropic":
        backend: LLMBackend = AnthropicBackend()
        if not backend.available:
            log.warning("AI_PROVIDER=anthropic but SAAKSHYA_LLM_KEY is unset; "
                        "falling back to local rules rather than failing every "
                        "question.")
            return RuleBackend()
        return backend
    if choice == "gemini":
        backend = GeminiBackend()  # type: ignore[assignment]
        if not backend.available:
            log.warning("AI_PROVIDER=gemini but no Gemini key is set "
                        "(SAAKSHYA_GEMINI_KEY / GEMINI_API_KEY / "
                        "SAAKSHYA_GEMINI_KEYS); falling back to local rules.")
            return RuleBackend()
        return backend

    # auto
    if os.environ.get("SAAKSHYA_LLM_KEY"):
        return AnthropicBackend()
    if gemini_configured():
        return GeminiBackend()
    return RuleBackend()


def turn_from_json(payload: str) -> Turn:
    """Helper for scripted fixtures held as JSON."""
    d = json.loads(payload)
    return Turn(text=d.get("text", ""),
                tool_calls=[ToolCall(c.get("id", f"t{i}"), c["name"],
                                     c.get("arguments", {}))
                            for i, c in enumerate(d.get("tool_calls", []))])


# --------------------------------------------------------------------------- #
# Rule backend
# --------------------------------------------------------------------------- #
#: Indian registration marks as they appear after OCR normalisation: state code,
#: RTO district, an optional series, then the number. Spaces and hyphens are
#: stripped before matching, so "GJ 38 BH 5815" and "GJ38BH5815" both hit.
_PLATE = re.compile(r"\b([A-Z]{2}\s?-?\d{1,2}\s?-?[A-Z]{0,3}\s?-?\d{1,4})\b")
_CAMERA = re.compile(r"\b(cam\d{1,3}|C-\d{2,4})\b", re.IGNORECASE)
_EVIDENCE = re.compile(r"\b(EZ[0-9A-Z]{20,})\b")


class RuleBackend:
    """Answers a useful subset of questions with no language model at all.

    The copilot's promise is "I can search, trace and explain — using the same
    engine as the workspace". With no API key configured that promise was empty:
    the assistant declined every question, including ones the deterministic
    tools could answer completely. This backend keeps the promise for the
    question shapes that map cleanly onto a tool call, and declines the rest as
    plainly as before.

    It is not a language model and does not pretend to be. It plans tool calls
    from keywords and renders their results; it cannot infer, summarise loosely,
    or answer anything it has no tool for. That is a real limitation and it is
    stated in every answer.

    It is also the only configuration in which **no government data leaves the
    deployment** — which for this system is a property worth having by default
    rather than a fallback to apologise for.
    """

    name = "rules"
    available = True

    #: Kept identical in shape to the LLM path: this backend emits tool calls on
    #: the first turn and prose on the second, so the orchestrator's grounding
    #: check, tool-call budget and prompt-injection scan all apply unchanged.
    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> Turn:
        results = self._results(messages)
        if results:
            return Turn(text=self._render(results), stop_reason="end")
        calls = self._plan(self._question(messages), {t["name"] for t in tools})
        if not calls:
            return Turn(text=self._cannot_answer(), stop_reason="end")
        return Turn(tool_calls=calls, stop_reason="tool_use")

    # -- reading the conversation ------------------------------------------- #
    @staticmethod
    def _question(messages: list[dict[str, Any]]) -> str:
        for m in messages:
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                return m["content"]
        return ""

    @staticmethod
    def _results(messages: list[dict[str, Any]]) -> list[tuple[str, Any]]:
        """Tool results so far, paired with the tool that produced them."""
        names: dict[str, str] = {}
        out: list[tuple[str, Any]] = []
        for m in messages:
            content = m.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "tool_use":
                    names[block["id"]] = block["name"]
                elif block.get("type") == "tool_result":
                    raw = block.get("content") or ""
                    try:
                        out.append((names.get(block["tool_use_id"], "?"),
                                    json.loads(raw)))
                    except json.JSONDecodeError:
                        # A truncated result is not partially trusted. It is
                        # reported as truncated and nothing is read from it.
                        out.append((names.get(block["tool_use_id"], "?"),
                                    {"error": "result was truncated"}))
        return out

    # -- planning ------------------------------------------------------------ #
    def _plan(self, q: str, available: set[str]) -> list[ToolCall]:
        text = q.upper().replace("-", " ")
        plate_m = _PLATE.search(re.sub(r"[^\w\s]", " ", text))
        plate = re.sub(r"[\s-]", "", plate_m.group(1)) if plate_m else None
        cam_m = _CAMERA.search(q)
        camera = cam_m.group(1) if cam_m else None
        ev_m = _EVIDENCE.search(q)
        low = q.lower()

        def want(*words: str) -> bool:
            return any(w in low for w in words)

        calls: list[ToolCall] = []

        def add(name: str, **args: Any) -> None:
            if name in available:
                calls.append(ToolCall(id=f"rule{len(calls) + 1}", name=name,
                                      arguments=args))

        if ev_m and want("verify", "integrity", "tamper"):
            add("verify_evidence", evidence_id=ev_m.group(1))
        if plate:
            if want("watchlist", "wanted", "stolen", "flagged"):
                add("query_watchlist", plate=plate)
            add("search_plate", plate=plate)
            if want("where", "route", "trace", "track", "movement", "travel",
                    "go", "went", "seen", "trajector"):
                add("build_trajectory", plate=plate)
            if want("why", "explain", "confident", "sure", "match"):
                add("explain_match", plate=plate)
            if want("report", "summary", "write up", "brief"):
                add("draft_report", plate=plate)
        if want("infrared", "monochrome", "estate", "which camera",
                "show me camera", "show camera", "cameras that",
                "cannot read", "unsuitable", "unlocated", "district"):
            args: dict[str, Any] = {}
            if want("infrared", "monochrome"):
                args["infrared"] = True
            if want("cannot read", "unsuitable", "anpr"):
                args["anpr_grade"] = "UNSUITABLE"
            if want("unlocated", "without coordinate", "not on the map"):
                args["located"] = False
            add("list_estate", **args)
        if want("timebase", "same clock", "share a time", "correlate",
                "timeline", "same window"):
            cams = _CAMERA.findall(q)
            if len(cams) >= 2:
                add("check_timebase", camera_a=cams[0], camera_b=cams[1])
            else:
                add("list_timebase")
        if want("enhance", "sharpen", "upscale", "generate an image",
                "imagine a plate", "invent a plate"):
            add("refuse_imagery", request=q[:200])
        if camera:
            if want("capab", "plate", "anpr", "read", "quality", "grade"):
                add("get_camera_capability", camera_id=camera)
            if want("next", "neighbour", "neighbor", "nearby", "adjacent",
                    "connected"):
                add("get_camera_neighbors", camera_id=camera)
            if not calls or want("about", "context", "what is", "tell me"):
                add("get_camera_context", camera_id=camera)
        return calls

    # -- rendering ----------------------------------------------------------- #
    def _render(self, results: list[tuple[str, Any]]) -> str:
        lines: list[str] = []
        for name, r in results:
            if not isinstance(r, dict):
                continue
            if r.get("refused"):
                # An access refusal carries `human`, not `reason`; reading
                # only `reason` printed "not permitted" and never said why.
                why = r.get("human") or r.get("reason") or "not permitted"
                lines.append(f"{name}: refused — {why}")
                continue
            if r.get("error"):
                lines.append(f"{name}: {r['error']}")
                continue
            lines.append(self._one(name, r))
        body = "\n".join(x for x in lines if x)
        return (body or "The tools returned nothing for this question.") + (
            "\n\nAnswered from the tool results below by deterministic rules; "
            "no language model was involved, and no data left this deployment.")

    @staticmethod
    def _one(name: str, r: dict[str, Any]) -> str:
        if name == "search_plate":
            n = r.get("result_count", len(r.get("candidates") or []))
            if not n:
                return ("search_plate: no stored observation carries this "
                        "registration mark. That is an absence of evidence, "
                        "not evidence the vehicle was absent.")
            first = (r.get("candidates") or [{}])[0]
            cams = sorted({c.get("camera_id") for c in (r.get("candidates") or [])
                           if c.get("camera_id")})
            return (f"search_plate: {n} observation(s), on "
                    f"{', '.join(cams) or 'no named camera'}. The strongest is "
                    f"{first.get('status', 'unrated')} at "
                    f"{first.get('t_norm_ist') or first.get('t_norm') or 'an unrecorded time'} "
                    f"(quality {first.get('observation_quality', 'unknown')}).")
        if name == "build_trajectory":
            hyp = r.get("hypotheses") or []
            if not hyp:
                return ("build_trajectory: no route hypothesis could be built "
                        "from these sightings.")
            h = hyp[0]
            return (f"build_trajectory: {len(hyp)} hypothesis(es); the best is "
                    f"{h.get('status', 'unrated')} with score "
                    f"{h.get('score', 'unknown')} across "
                    f"{len(h.get('legs') or [])} leg(s). A score orders "
                    "candidates and is not a probability.")
        if name == "get_camera_capability":
            return (f"get_camera_capability: {r.get('camera_id', 'camera')} is "
                    f"graded {r.get('anpr', 'UNKNOWN')} for ANPR, "
                    f"{r.get('vehicle', 'UNKNOWN')} for appearance and "
                    f"{r.get('presence', 'UNKNOWN')} for presence, from "
                    f"{r.get('samples', 0)} sample(s).")
        if name == "get_camera_context":
            cam = r.get("camera") or r
            return (f"get_camera_context: {cam.get('camera_id', 'camera')} "
                    f"({cam.get('name', 'unnamed')}), district "
                    f"{cam.get('district', 'unrecorded')}.")
        if name == "get_camera_neighbors":
            ns = r.get("neighbours") or r.get("neighbors") or []
            return (f"get_camera_neighbors: {len(ns)} connected camera(s): "
                    f"{', '.join(str(n.get('camera_id')) for n in ns[:8]) or 'none'}.")
        if name == "query_watchlist":
            e = r.get("entries") or []
            return (f"query_watchlist: {len(e)} matching entry(ies)." if e
                    else "query_watchlist: this mark is not on the watchlist.")
        if name == "verify_evidence":
            return (f"verify_evidence: "
                    f"{'PASSED' if r.get('verified') else 'FAILED'}; "
                    f"{len(r.get('checks') or [])} check(s) ran.")
        if name == "list_estate":
            cams = r.get("cameras") or []
            ids = ", ".join(str(c.get("camera_id")) for c in cams[:12]) or "none"
            return (f"list_estate: {r.get('matched', len(cams))} camera(s) "
                    f"matched. {ids}. {r.get('note', '')}")
        if name == "list_timebase":
            clusters = r.get("clusters") or []
            return (f"list_timebase: {len(clusters)} cluster(s). "
                    f"{r.get('note', '')}")
        if name == "check_timebase":
            return (f"check_timebase: {r.get('camera_a')} and "
                    f"{r.get('camera_b')} → {r.get('verdict')}. "
                    f"{r.get('reason', '')}")
        if name == "refuse_imagery":
            return f"refuse_imagery: {r.get('reason', 'refused')}"
        return f"{name}: see the tool result below."

    @staticmethod
    def _cannot_answer() -> str:
        return (
            "I could not turn that into a tool call. Without a language model "
            "configured I answer from fixed rules, so I need a registration "
            "mark (GJ38BH5815), a camera id (cam21) or an evidence id in the "
            "question.\n\n"
            "Ask me to find a mark, trace its route, explain a match, check the "
            "watchlist, list cameras (including infrared or ANPR grade), check "
            "whether two cameras share a timebase, describe a camera or its "
            "neighbours, or verify an evidence record. Set SAAKSHYA_GEMINI_KEY "
            "or SAAKSHYA_LLM_KEY to enable free-form questions."
        )
