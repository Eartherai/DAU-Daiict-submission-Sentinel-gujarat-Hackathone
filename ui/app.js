/* SAAKSHYA investigation workspace.
 *
 * The screen is organised around the task, not the data model: target →
 * observations → trajectory → watchlist → evidence → audit, left to right.
 * There is no camera video wall, because the first question an investigator
 * asks is never "show me every camera".
 *
 * Two rules run through the rendering:
 *
 *  - No opaque confidence. Wherever a score appears, its decomposition appears
 *    with it — which signal contributed what, and the sentence that produced it.
 *  - Uncertainty is stated in words, not implied by colour. CONFIRMED BY PLATE
 *    and REQUIRES VERIFICATION are printed; the colour only reinforces them.
 */
import { MapView } from "/ui/map.js?v=cr087";

/* ─── API client ─────────────────────────────────────────────────────────── */
const state = {
  token: sessionStorage.getItem("saakshya.token") || "",
  principal: null,
  results: [],
  selected: null,
  trajectory: null,
  hypothesis: 0,
  target: null,
  cameras: [],
  caseId: sessionStorage.getItem("saakshya.case") || "",
  purpose: sessionStorage.getItem("saakshya.purpose") || "",
  openCase: null,
  copilotConfig: { available: false, gemini: false },
  liveConfig: { whep: false },
  telemetry: {
    snapshot: { started: 0, completed: 0, error: "" },
    whep: { started: 0, completed: 0, error: "" },
    playbackError: "",
    reconnect: "idle",
    browser: {
      framesDecoded: null, framesDropped: null, packetsLost: null,
      packetsReceived: null, fps: null, jitterMs: null, jitterBufferMs: null,
      rttMs: null, codec: "", decoder: "", width: null, height: null,
      freezes: 0, lastFrameAt: 0, state: "IDLE",
    },
  },
};

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/* The headers every request carries. Extracted so a fetch that is not JSON —
 * an image, an export — can authenticate the same way rather than smuggling a
 * token through a query string, where it would land in server logs, browser
 * history, and any screenshot of a demonstration. */
function authHeaders() {
  const h = {};
  if (state.token) h.Authorization = `Bearer ${state.token}`;
  if (state.caseId) h["X-Case-Id"] = state.caseId;
  if (state.purpose) h["X-Purpose"] = state.purpose;
  const gemini = sessionStorage.getItem("saakshya.gemini");
  if (gemini === "off") h["X-AI-Provider"] = "local";
  else if (gemini === "on") h["X-AI-Provider"] = "gemini";
  return h;
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json",
                    ...authHeaders(), ...(opts.headers || {}) };
  const res = await fetch(path, { ...opts, headers });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = { raw: text }; }
  if (!res.ok) {
    const d = (body && body.detail) || {};
    throw new ApiError(res.status, d.code || String(res.status),
                       d.message || res.statusText);
  }
  return body;
}

/* ─── small helpers ──────────────────────────────────────────────────────── */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

function loadingNote(text) {
  return el("div", { class: "loading-note",
    text: text || "Loading from the live store…" });
}

function toast(message, bad = false) {
  const t = el("div", { class: `toast${bad ? " bad" : ""}`, text: message });
  document.body.append(t);
  setTimeout(() => t.remove(), bad ? 7000 : 3500);
}

function fmtTime(iso) {
  if (!iso) return "—";
  return String(iso).replace("T", " ").replace(/(\+00:00|Z)$/, "").slice(0, 19);
}

function fmtClock(iso) {
  if (!iso) return "—";
  return String(iso).slice(11, 19);
}

function fmtAlertClock(a) {
  if (!a) return "—";
  if (a.when) return fmtClock(a.when);
  if (a.t_norm && typeof a.t_norm === "string") return fmtClock(a.t_norm);
  const us = a.t_norm_us || a.t;
  if (us && Number(us) > 1e12) {
    try { return new Date(Number(us) / 1000).toISOString().slice(11, 19); }
    catch { return "—"; }
  }
  return "—";
}

/* A rate of 0.00 and a rate of exactly zero mean different things to an
 * investigator: the first camera has read a plate and the second never has.
 * At these sample sizes rounding erases that distinction, so the count is
 * shown whenever there is one to show. */
function plateYield(f) {
  if (f.plate_yield == null) return "—";
  const reads = f.plate_reads;
  if (!reads) return num(f.plate_yield);
  return `${num(f.plate_yield)} (${reads})`;
}

function publishedMarksLabel(f) {
  const d = Number(f.published_marks || 0);
  if (!d) return "—";
  const conf = Number(f.published_confirmed || 0);
  const leads = Number(f.published_leads || 0);
  return `${d} distinct · ${conf} confirmed / ${leads} leads`;
}

function situationCopy(o) {
  /* One screen of facts a shift actually starts with. Built only from the
   * overview payload — no extra call, no inferred cross-camera identity. */
  const open = (o.alerts && o.alerts.open) || 0;
  const hits = (o.alerts.recent || []).filter((a) => a.status === "OPEN");
  let attention;
  if (!open) {
    attention = "No open alert.";
  } else if (hits.length) {
    const a = hits[0];
    const cat = String(a.category || "alert").replace(/_/g, " ");
    const pri = a.priority ? `, ${a.priority}` : "";
    attention = `${open} open alert${open === 1 ? "" : "s"} — `
      + `${a.plate || "unplated"} on ${a.camera_id || "unknown camera"} `
      + `(${cat}${pri}).`;
    if (open > 1) attention = attention.replace(/\.$/, ` and ${open - 1} more.`);
  } else {
    attention = `${open} open alert${open === 1 ? "" : "s"}.`;
  }

  const cams = o.cameras.total;
  const marks = Number(o.observations.cameras_with_plate || 0);
  const distinct = Number(o.observations.distinct_plates || 0);
  const anprGood = (o.capability_anpr && o.capability_anpr.GOOD) || 0;
  const learned = (o.graph && o.graph.edges_observed) || 0;
  const by = o.cameras.by_state || {};
  const camState = ["STREAMING", "OBSERVED", "UNKNOWN", "DEGRADED", "FAILED",
                    "DOWN", "STOPPED"]
    .filter((k) => by[k])
    .map((k) => `${by[k]} ${k.toLowerCase()}`)
    .join(" · ");

  const yieldLine =
    `${marks} of ${cams} cameras published ${distinct.toLocaleString()} `
    + `distinct mark${distinct === 1 ? "" : "s"}; `
    + `${anprGood} graded GOOD for ANPR — yield at this geometry, not emptiness.`;
  const dwellS = Number(o.observations.person_dwell_s || 12);
  const longStay = Number(o.observations.person_long_stay || 0);
  const dwellLine = longStay
    ? `${longStay.toLocaleString()} person observation${longStay === 1 ? "" : "s"} `
      + `stayed longer than ${dwellS} s on one camera `
      + `(${Number(o.observations.person_long_stay_cameras || 0)} cameras) — `
      + `position and time, not identity.`
    : "";
  const rest =
    `${Number(learned).toLocaleString()} transition${learned === 1 ? "" : "s"} `
    + `learned from sightings.`
    + (camState ? ` ${camState}.` : "")
    + (dwellLine ? ` ${dwellLine}` : "");
  return { attention, yieldLine, rest };
}

function observationSub(obs) {
  if (!obs) return "—";
  const parts = [`${Number(obs.with_plate || 0).toLocaleString()} with a mark`];
  if (obs.plate_confirmed != null || obs.plate_leads != null) {
    parts.push(`${Number(obs.plate_confirmed || 0).toLocaleString()} confirmed`);
    parts.push(`${Number(obs.plate_leads || 0).toLocaleString()} leads`);
  }
  if (obs.persons) parts.push(`${Number(obs.persons).toLocaleString()} persons`);
  if (obs.person_long_stay) {
    parts.push(`${Number(obs.person_long_stay).toLocaleString()} long stay`);
  }
  if (obs.raw_ocr_attempts != null) {
    parts.push(`${Number(obs.raw_ocr_attempts || 0).toLocaleString()} OCR attempts stored`);
  }
  return parts.join(" · ");
}

function objectMixLine(obs) {
  const types = (obs && obs.by_object_type) || {};
  return Object.entries(types)
    .filter(([, v]) => v)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${Number(v).toLocaleString()} ${k}`)
    .join(" · ");
}

function resultHeadline(c) {
  if (c.plate) return c.plate;
  if (c.object_type === "person") return "person";
  return "no plate read";
}

function dwellLabel(c) {
  const d = c.model_versions && c.model_versions.dwell_s;
  if (d == null || c.object_type !== "person") return "";
  const exceeded = c.model_versions.dwell_exceeded;
  return exceeded ? `dwell ${d}s — long stay` : `dwell ${d}s`;
}

function plateVotesLabel(c) {
  const n = Number(c.plate_votes || 0);
  if (!c.plate) return "—";
  if (n >= 2) return `${n} agreeing frames — confirmed`;
  if (n === 1) return "1 frame — uncorroborated lead";
  return String(n);
}

function num(v, places = 2) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(places);
}

function statusChip(status) {
  const map = {
    CONFIRMED_BY_PLATE: ["confirmed", "confirmed by plate"],
    REQUIRES_VERIFICATION: ["verify", "requires verification"],
    ATTRIBUTE_FILTER: ["unknown", "attribute filter"],
    CONTRIBUTING: ["confirmed", "contributing"],
    CONFIRMED: ["confirmed", "confirmed"],
    LIKELY: ["confirmed", "likely"],
    REJECTED: ["conflict", "rejected"],
    STORED: ["plain", "stored"],
  };
  const [cls, label] = map[status] || ["plain", String(status || "").toLowerCase()];
  return el("span", { class: `chip ${cls}`, text: label });
}

function gradeChip(grade, label) {
  const cls = { GOOD: "confirmed", DEGRADED: "verify",
                UNSUITABLE: "conflict", UNKNOWN: "unknown" }[grade] || "plain";
  return el("span", { class: `chip ${cls}`, text: `${label} ${grade}` });
}

/* ─── views ──────────────────────────────────────────────────────────────── */
const loaders = {};

function show(view) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $$(".nav button").forEach((b) =>
    b.setAttribute("aria-current", String(b.dataset.view === view)));
  location.hash = view;
  if (loaders[view]) loaders[view]();
  if (view !== "live") {
    stopLiveRefresh(); closeLive();
    liveObserver?.disconnect(); liveObserver = null; liveQueue.length = 0;
  }
  if (view === "map" && map2) {
    map2.resize();
    refreshMapLayers(map2, map2.bbox());
  }
  if (view === "investigate" && map1) { map1.resize(); }
}

$$(".nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

/* A bare number in a nav badge reads as "3" and nothing else. Naming it costs
 * one attribute and turns it into "Alerts, 3 open". */
function labelCount(id, noun) {
  const el = $(id);
  if (!el) return;
  const n = el.textContent.trim();
  el.setAttribute("aria-label", n ? `${n} ${noun}` : "");
  el.setAttribute("role", "status");
}

/* ─── session ────────────────────────────────────────────────────────────── */
const purposeBar = $("#purpose-bar");

function syncPurpose() {
  state.caseId = $("#case-id").value.trim();
  state.purpose = $("#purpose").value.trim();
  sessionStorage.setItem("saakshya.case", state.caseId);
  sessionStorage.setItem("saakshya.purpose", state.purpose);
  const ok = state.caseId && state.purpose.length >= 12;
  purposeBar.classList.toggle("unset", !ok);
  purposeBar.title = ok
    ? "This case and purpose are written into the audit record of every search."
    : "A case identifier and a purpose of at least 12 characters are required "
      + "before any vehicle search can run.";
}

$("#case-id").value = state.caseId;
$("#purpose").value = state.purpose;
$("#case-id").addEventListener("input", syncPurpose);
$("#purpose").addEventListener("input", syncPurpose);
syncPurpose();

$("#btn-token").addEventListener("click", () => {
  $("#token-input").value = "";
  $("#token-dialog").showModal();
});
$("#gate-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const tok = $("#gate-token").value.trim();
  if (!tok) return;
  state.token = tok;
  sessionStorage.setItem("saakshya.token", tok);
  const c = $("#gate-case")?.value.trim();
  const p = $("#gate-purpose")?.value.trim();
  if (c) { state.caseId = c; $("#case-id").value = c; }
  if (p) { state.purpose = p; $("#purpose").value = p; }
  await identify();
  if (state.principal) {
    syncPurpose();
    show((location.hash || "#overview").slice(1) || "overview");
  } else {
    toast("Token was refused. Check it and try again.", true);
  }
});
$("#token-dialog").addEventListener("close", async (e) => {
  const dlg = e.target;
  if (dlg.returnValue !== "save") return;
  state.token = $("#token-input").value.trim();
  sessionStorage.setItem("saakshya.token", state.token);
  await identify();
});

/* Density, not zoom.
 *
 * Browser zoom scales the layout and reflows a thirty-tile wall into a column.
 * This scales the *type* against a root variable, so an operator reading from
 * across a control room gets larger text in the same grid, and the choice is
 * remembered because nobody wants to set it at the start of every shift. */
const SCALES = ["comfortable", "large", "wall"];
function applyScale(name) {
  document.documentElement.dataset.scale = name;
  const b = $("#btn-scale");
  if (b) b.title = `Text size: ${name} — click for the next size`;
  try { localStorage.setItem("saakshya.scale", name); } catch { /* private mode */ }
}
$("#btn-scale")?.addEventListener("click", () => {
  const now = document.documentElement.dataset.scale || SCALES[0];
  applyScale(SCALES[(SCALES.indexOf(now) + 1) % SCALES.length]);
});
try {
  applyScale(localStorage.getItem("saakshya.scale") || SCALES[0]);
} catch { applyScale(SCALES[0]); }

$("#btn-theme").addEventListener("click", () => {
  const root = document.documentElement;
  const next = root.dataset.theme === "dark" ? "light"
    : root.dataset.theme === "light" ? "dark"
      : (matchMedia("(prefers-color-scheme: dark)").matches ? "light" : "dark");
  root.dataset.theme = next;
  localStorage.setItem("saakshya.theme", next);
  if (map1) map1.draw();
  if (map2) map2.draw();
});
try {
  const saved = localStorage.getItem("saakshya.theme");
  if (saved) document.documentElement.dataset.theme = saved;
} catch { /* storage may be unavailable; the default theme is correct */ }

function geminiWanted() {
  return sessionStorage.getItem("saakshya.gemini") !== "off";
}

function syncGeminiButton() {
  const b = $("#btn-gemini");
  if (!b) return;
  const configured = !!state.copilotConfig?.gemini;
  const on = configured && geminiWanted();
  b.textContent = on ? "Gemini on" : "Gemini off";
  b.classList.toggle("on", on);
  b.setAttribute("aria-pressed", on ? "true" : "false");
  b.disabled = !configured;
  b.title = configured
    ? (on
      ? "Gemini is coordinating the copilot. Click to keep answers on this host."
      : "Gemini is off. Click to let Gemini coordinate the copilot.")
    : "No Gemini key in this process. Copilot still answers from local rules.";
}

$("#btn-gemini")?.addEventListener("click", () => {
  if ($("#btn-gemini").disabled) return;
  sessionStorage.setItem("saakshya.gemini", geminiWanted() ? "off" : "on");
  syncGeminiButton();
  toast(geminiWanted()
    ? "Gemini on — copilot questions may leave this host."
    : "Gemini off — copilot answers from local rules on this host.");
  if ($("#view-copilot")?.classList.contains("active")) loaders.copilot();
});

async function applyDeploymentConfig(cfg) {
  const mapOpts = {};
  if (cfg.map?.google?.enabled && cfg.map.google.key) {
    mapOpts.googleKey = cfg.map.google.key;
  } else if (cfg.map?.tiles && cfg.map.template) {
    mapOpts.tileTemplate = cfg.map.template;
    mapOpts.attribution = cfg.map.attribution;
  }
  state.mapConfig = cfg.map;
  state.mapOpts = { ...(state.mapOpts || {}), ...mapOpts };
  state.liveConfig = cfg.live || { whep: false };
  state.dataHolds = cfg.data?.holds || "";
  state.copilotConfig = cfg.copilot || { available: false, gemini: false };
  if (state.copilotConfig.gemini && sessionStorage.getItem("saakshya.gemini") == null) {
    sessionStorage.setItem("saakshya.gemini", "on");
  }
  syncGeminiButton();
  const src = $("#handling-src");
  if (src && cfg.data) {
    src.textContent = `${cfg.data.store} · ${cfg.data.holds}`;
    src.classList.toggle("demo", cfg.data.holds === "DEMONSTRATION");
  }
  const value = (...keys) => {
    for (const key of keys) {
      const v = cfg.live?.[key];
      if (v !== undefined && v !== null && String(v).trim()) return String(v);
    }
    return "not reported";
  };
  const setIndicator = (id, label, text) => {
    const node = $(`#${id}`);
    if (node) node.textContent = `${label}: ${text}`;
  };
  setIndicator("feed-government", "GOVERNMENT FEED",
               value("government_feed", "government", "source"));
  setIndicator("feed-own", "OWN FEED / FULL ANALYTICS",
               value("own_feed", "analytics_mode"));
  setIndicator("feed-central", "CENTRAL ANALYTICS MODE",
               value("central_analytics_mode", "central_analytics"));
  if (mapOpts.tileTemplate) {
    map1?.setRasterBasemap?.(mapOpts.tileTemplate, mapOpts.attribution);
    map2?.setRasterBasemap?.(mapOpts.tileTemplate, mapOpts.attribution);
    map3?.setRasterBasemap?.(mapOpts.tileTemplate, mapOpts.attribution);
  }
}

async function identify() {
  try {
    const me = await api("/me");
    state.principal = me.principal;
    const p = me.principal;
    const officer = $("#officer-name");
    if (officer) officer.textContent = p.display_name || p.user_id;
    $("#who").textContent =
      `${p.user_id} · ${p.statewide ? "STATE" : (p.districts || []).join(", ") || p.role}`;
    $("#btn-token").textContent = "Change token";
    const gate = $("#gate");
    if (gate) gate.hidden = true;
    try {
      const cfg = await api("/config");
      await applyDeploymentConfig(cfg);
    } catch { /* config is optional furniture */ }
  } catch (err) {
    state.principal = null;
    $("#who").textContent = "not signed in";
    const gate = $("#gate");
    if (gate) gate.hidden = false;
    if (err.status !== 401) toast(err.message, true);
  }
}

/* ─── search ─────────────────────────────────────────────────────────────── */
function localToIso(value) {
  if (!value) return null;
  // A datetime-local field has no timezone. Treating it as UTC silently shifts
  // every result by 5½ hours in Gujarat, so the offset is made explicit.
  return new Date(value).toISOString();
}

$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  syncPurpose();
  const params = new URLSearchParams();
  const plate = $("#q-plate").value.trim().replace(/\s+/g, "").toUpperCase();
  if (plate) params.set("plate", plate);
  if ($("#q-fuzzy").checked) params.set("fuzzy", "true");
  if ($("#q-watchlist").checked) params.set("watchlist_only", "true");
  for (const [id, key] of [["q-colour", "colour"], ["q-type", "object_type"],
                           ["q-district", "district"], ["q-camera", "camera"]]) {
    const v = $(`#${id}`)?.value.trim();
    if (v) params.set(key, v);
  }
  const from = localToIso($("#q-from").value);
  const to = localToIso($("#q-to").value);
  if (from) params.set("t_from", from);
  if (to) params.set("t_to", to);

  const btn = $("#search-form button.primary");
  btn.disabled = true;
  btn.textContent = "Searching…";
  try {
    const eventType = $("#q-event")?.value.trim();
    const severity = $("#q-severity")?.value.trim();
    if (eventType || severity) {
      const ep = new URLSearchParams(params);
      if (eventType) ep.set("event_type", eventType);
      if (severity) ep.set("severity", severity);
      if (plate) ep.set("plate", plate);
      const ev = await api(`/command/events?${ep}`);
      state.results = (ev.events || []).map((e) => ({
        observation_id: e.observation_id || e.event_id,
        camera_id: e.camera_id, plate: e.entity, t_norm: e.timestamp,
        object_type: e.object_type, score: e.confidence,
        event: e.event,
      }));
      state.target = plate || null;
      renderResults({ candidates: state.results, note: ev.provenance });
      if (plate && state.results.length) await loadTrajectory(plate);
    } else {
      const res = await api(`/search?${params}`);
      state.results = res.candidates || [];
      state.target = plate || null;
      renderResults(res);
      if (plate && state.results.length) await loadTrajectory(plate);
    }
  } catch (err) {
    renderSearchError(err);
  } finally {
    btn.disabled = false;
    btn.textContent = "Search";
  }
});

function renderSearchError(err) {
  const box = $("#results");
  clear(box);
  const guidance = {
    PURPOSE_REQUIRED: "Fill in the case identifier and purpose at the top of the "
      + "screen. Both are written into the audit record; a vehicle search "
      + "cannot run without them.",
    NOT_AUTHENTICATED: "Sign in with the bearer token issued to you.",
    OUT_OF_JURISDICTION: "That district is outside your jurisdiction. A "
      + "supervisor with statewide scope can run this search.",
    PERMISSION_DENIED: "Your role does not hold this permission.",
    QUERY_TOO_BROAD: "Add at least one filter. An unfiltered scan of the whole "
      + "estate is refused deliberately.",
    BUSY: "The system refused this request rather than queueing it. Try again "
      + "shortly.",
  }[err.code];
  box.append(el("div", { class: "notice bad" },
    el("strong", { text: err.code || "Search failed" }),
    guidance || err.message));
  $("#result-count").textContent = "";
  $("#strategy").textContent = "";
}

function renderResults(res) {
  const box = $("#results");
  clear(box);
  const rows = res.candidates || [];
  $("#result-count").textContent = `${res.result_count ?? rows.length} observations`;

  /* Withholding is announced before anything else, and it changes what the
   * empty state is allowed to say. A match found on a camera outside this
   * officer's jurisdiction is still a match: reporting it as "nothing was
   * recorded" would be a confident denial of evidence this system holds. */
  const w = res.withheld;
  if (w?.count) {
    box.append(el("div", { class: "notice warn" },
      el("strong", { text: `${w.count} match(es) withheld — outside your jurisdiction` }),
      w.message,
      el("div", { class: "dim", style: "margin-top:6px",
                  text: `District(s): ${(w.districts || []).join(", ")}. `
                        + "Request access through the force that holds them; "
                        + "this refusal is recorded in the audit log." })));
  }

  if (!rows.length) {
    box.append(el("div", { class: "notice neutral" },
      el("strong", { text: w?.count ? "Nothing shown to you" : "No observation matched" }),
      w?.count
        ? "Every match for this target is on a camera outside your "
          + "jurisdiction. The vehicle was recorded; you are not permitted to "
          + "see where."
        : "This is not evidence that the target was absent. It means no camera in "
          + "the searched set recorded a matching observation. The cameras that were "
          + "searched, and those excluded, are listed below."));
  }

  if (res.caveat) {
    box.append(el("div", { class: "notice" },
      el("strong", { text: "Attribute filter" }), res.caveat));
  }

  /* A dozen hits of one mark is not a fleet if they never left one camera.
   * The government grid loops; saying so here is what stops a looping
   * publisher being read as a multi-camera route. */
  const sight = res.sighting;
  if (sight?.message) {
    box.append(el("div", {
      class: "notice" + (sight.cross_camera ? "" : " warn"),
    },
      el("strong", {
        text: sight.cross_camera
          ? "Seen on more than one camera"
          : "One camera only",
      }),
      sight.message));
  }

  for (const c of rows) {
    const row = el("div", {
      class: "result", role: "option", "aria-selected": "false",
      onclick: () => selectResult(c, row),
    },
      el("div", { class: "top" },
        el("span", { class: "plate", text: resultHeadline(c) }),
        statusChip(c.status),
        el("span", { class: "time", text: fmtTime(c.t_norm) })),
      el("div", { class: "meta" },
        el("span", { class: "cam", text: c.camera_id }),
        c.camera_name && el("span", { text: c.camera_name }),
        c.object_type && c.object_type !== "unknown"
          && el("span", { text: c.object_type }),
        c.colour && el("span", { text: c.colour }),
        Number(c.plate_votes) === 1
          && el("span", { class: "chip verify", text: "uncorroborated lead" }),
        dwellLabel(c) && el("span", { text: dwellLabel(c) }),
        el("span", { text: `quality ${num(c.observation_quality)}` }),
        c.evidence_available && el("span", { class: "chip plain", text: "evidence" })));
    box.append(row);
  }

  const st = res.search_strategy;
  if (st) {
    const excluded = st.cameras_excluded || [];
    $("#strategy").textContent =
      `Searched ${st.cameras_searched_count} camera(s) in `
      + `${Array.isArray(st.jurisdiction) ? st.jurisdiction.join(", ") : st.jurisdiction}`
      + (excluded.length ? ` · ${excluded.length} excluded: `
        + [...new Set(excluded.map((x) => x.reason))].join(", ") : "");
    $("#strategy").title = excluded
      .map((x) => `${x.camera_id}: ${x.detail}`).join("\n");
  }
  if (rows.length) selectResult(rows[0], box.firstElementChild);
}

/* ─── detail: why this match, evidence, audit ────────────────────────────── */
function selectResult(c, row) {
  state.selected = c;
  $$(".result").forEach((r) => r.setAttribute("aria-selected", "false"));
  if (row) row.setAttribute("aria-selected", "true");
  $("#sel-id").textContent = c.observation_id || "";
  if (map1 && c.camera_id) { map1.selected = c.camera_id; map1.draw(); }
  renderDetail(c);
}

function renderDetail(c) {
  const box = $("#detail");
  clear(box);

  /* WHY THIS MATCH — never a single number. */
  const why = c.why;
  const panel = el("div", { class: "panel" },
    el("h3", {}, "Why this match", statusChip(c.status)));
  const body = el("div", { class: "body" });

  if (why && why.terms) {
    body.append(el("div", { class: "terms" }, why.terms.map((t) => {
      const pct = Math.max(0, Math.min(1, Number(t.value) || 0));
      const cls = pct >= 0.6 ? "" : pct > 0 ? "weak" : "none";
      return el("div", { class: "term" },
        el("div", { class: "line" },
          el("span", { class: "name", text: t.name.replace(/_/g, " ") }),
          el("span", { class: "val", text: `${num(t.value)} × ${num(t.weight)}` })),
        el("div", { class: "track" },
          el("div", { class: `fill ${cls}`, style: `width:${pct * 100}%` })),
        el("div", { class: "why", text: t.explanation || "" }));
    })));
    if (why.primary_weakness) {
      body.append(el("div", { class: "notice" },
        el("strong", { text: "Weakest signal" }), why.primary_weakness));
    }
    body.append(el("div", { class: "section-note", style: "padding:8px 0 0" },
      "Score is an ordering score over candidates, not a calibrated probability."));
  } else if (c.object_type === "person") {
    body.append(el("div", { class: "notice ok" },
      el("strong", { text: "Person — position and time" }),
      "Tracked from the same detector pass as vehicles. Never fused with a "
      + "plate, never given a registration mark. Dwell is reported; "
      + "intrusion is a judgement about permission this system cannot make."));
  } else if (c.plate && Number(c.plate_votes) === 1) {
    body.append(el("div", { class: "notice" },
      el("strong", { text: "Uncorroborated lead" }),
      "The registration mark was read on a single frame. It is an exact match "
      + "and it is not a confirmation — verify before acting."));
  } else if (c.plate) {
    body.append(el("div", { class: "notice ok" },
      el("strong", { text: "Identified by registration mark" }),
      "The plate was read directly at this camera. Appearance signals were not "
      + "needed and did not contribute."));
  } else {
    body.append(el("div", { class: "notice" },
      el("strong", { text: "No registration mark" }),
      "This observation is presence and appearance only. That is still "
      + "evidence — it is not a claim about who the vehicle is."));
  }
    for (const w of c.warnings || []) {
    body.append(el("div", { class: "notice", text: w }));
  }
  if (c.plate_repairs && c.plate_repairs.length) {
    body.append(el("div", { class: "notice" },
      el("strong", { text: "OCR lookalikes — not applied" }),
      "These marks are one known confusion (O/0, B/8, I/1) from the raw OCR. "
      + "The stored read was not changed.",
      el("div", { class: "meta", style: "margin-top:6px" },
        c.plate_repairs.map((r) =>
          el("span", { class: "chip verify",
                       text: r.display || r.canonical,
                       title: r.reason || "" })))));
  }
  panel.append(body);
  box.append(panel);

  /* SOURCE — where the conclusion came from. */
  box.append(el("div", { class: "panel" },
    el("h3", {}, "Source"),
    el("div", { class: "body" },
      el("dl", { class: "kv" },
        dt("Camera"), dd(`${c.camera_id}${c.camera_name ? " · " + c.camera_name : ""}`),
        dt("District"), dd(c.district || "—"),
        dt("Department"), dd(c.department || "—"),
        dt("Location"), dd(c.lat != null ? `${num(c.lat, 5)}, ${num(c.lon, 5)}` : "not located"),
        dt("PTS"), dd(`${num(c.pts_s, 3)} s`),
        dt("Normalised"), dd(fmtTime(c.t_norm)),
        dt("Track"), dd(c.track_id || "—"),
        dt("Type"), dd(c.object_type || "—"),
        dt("Plate votes"), dd(plateVotesLabel(c)),
        dwellLabel(c) ? dt("Dwell") : null,
        dwellLabel(c) ? dd(dwellLabel(c)) : null,
        dt("Quality"), dd(`${num(c.observation_quality)} (grade ${c.source_grade || "UNKNOWN"})`),
        dt("Sharpness"), dd(num(c.sharpness, 1)),
        dt("Luminance"), dd(num(c.luminance, 1)),
        dt("Plate width"), dd(c.plate_pixel_width ? `${num(c.plate_pixel_width, 0)} px` : "—"),
        dt("OCR raw"), dd(c.plate_raw || "—"),
        dt("Models"), dd(Object.entries(c.model_versions || {})
          .map(([k, v]) => `${k}=${v}`).join(" ") || "—")))));

  /* EVIDENCE — with a button that runs the real verification. */
  const ev = el("div", { class: "panel" }, el("h3", {}, "Evidence"));
  const evBody = el("div", { class: "body" });
  if (c.evidence_id) {
    evBody.append(el("dl", { class: "kv" },
      dt("Evidence"), dd(c.evidence_id)));
    evBody.append(el("button", {
      class: "primary", style: "margin-top:8px",
      onclick: (e) => verifyEvidence(c.evidence_id, e.target, evBody),
    }, "Verify evidence"));
  } else {
    evBody.append(el("div", { class: "notice neutral" },
      el("strong", { text: "Not yet sealed" }),
      "No evidence record has been created for this observation. Sealing "
      + "computes digests of the frame and clip and appends a hash-chained "
      + "manifest."));
    evBody.append(el("button", {
      class: "primary", style: "margin-top:8px",
      onclick: (e) => sealEvidence(c, e.target),
    }, "Seal evidence"));
  }
  ev.append(evBody);
  box.append(ev);

  /* ACTIONS */
  box.append(el("div", { class: "panel" },
    el("h3", {}, "Attach"),
    el("div", { class: "body", style: "display:flex;gap:6px;flex-wrap:wrap" },
      el("button", {
        class: "ghost",
        onclick: () => attach("observation", c.observation_id, c),
      }, "Attach observation to case"),
      c.plate && el("button", {
        class: "ghost",
        onclick: () => attach("target", c.plate, { plate: c.plate }),
      }, "Attach target to case"),
      c.plate && el("button", {
        class: "primary",
        onclick: () => followVehicle(c.plate),
      }, "Follow vehicle"),
      el("button", {
        class: "ghost",
        onclick: () => nextCameras(c),
      }, "Where to look next"))));
}

const dt = (t) => el("dt", { text: t });
const dd = (t) => el("dd", { text: t === null || t === undefined ? "—" : String(t) });

/* The verification endpoints answer {verified, checks:[{check, passed, detail}]}.
 * Both readers in this file had been written against {ok, checks:[{ok, name}]},
 * so every field was undefined, every check rendered ✗, and the UI reported
 * "EVIDENCE CHAIN BROKEN" over a chain that verified. It failed in the alarming
 * direction and it failed on the success path, which is why nothing caught it.
 *
 * Normalised in one place so a third reader cannot drift the same way, and
 * tolerant of both spellings so it does not break if the API is ever aligned. */
function normaliseVerification(v) {
  const passed = v.verified !== undefined ? v.verified : v.ok;
  return {
    ok: passed === true,
    checks: (v.checks || []).map((c) => ({
      ok: (c.passed !== undefined ? c.passed : c.ok) === true,
      name: c.check || c.name || "",
      detail: c.detail || "",
      /* A caution is not a failure. The record is exactly what was sealed; a
       * statement inside it is defective. Rendering the two the same way puts
       * "VERIFICATION FAILED" over an intact chain, and an operator shown that
       * over an intact chain learns to disregard it. */
      caution: c.level === "caution",
    })),
    cautions: (v.cautions || []).map((c) => ({
      name: c.check || "", detail: c.detail || "",
    })),
  };
}

async function verifyEvidence(evidenceId, button, container) {
  button.disabled = true;
  button.textContent = "Verifying…";
  try {
    const v = normaliseVerification(await api(
      `/evidence/${encodeURIComponent(evidenceId)}/verify`, { method: "POST" }));
    const cautioned = (v.cautions || []).length > 0;
    const box = el("div", {
      class: `notice ${v.ok ? (cautioned ? "warn" : "ok") : "bad"}` },
      el("strong", { text: !v.ok
        ? "VERIFICATION FAILED"
        : cautioned
          ? "Integrity intact — read the cautions"
          : "Verified" }));
    if (v.ok && cautioned) {
      box.append(el("div", { style: "margin-bottom:6px",
        text: "Every hash matches and the chain is unbroken. What follows is a "
              + "defect in what a record says, not in whether it was altered." }));
      for (const c of v.cautions) {
        box.append(el("div", { class: "mono", style: "font-size:10.5px",
                               text: `! ${c.name} — ${c.detail}` }));
      }
    }
    for (const chk of (v.checks || []).filter((c) => !c.caution)) {
      box.append(el("div", { class: "mono", style: "font-size:10.5px",
                             text: `${chk.ok ? "✓" : "✗"} ${chk.name}${chk.detail ? " — " + chk.detail : ""}` }));
    }
    container.append(box);
    button.textContent = "Verify again";
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
    button.textContent = "Verify evidence";
  } finally {
    button.disabled = false;
  }
}

async function sealEvidence(c, button) {
  button.disabled = true;
  try {
    const m = await api(
      `/evidence/from-observation/${encodeURIComponent(c.observation_id)}`,
      { method: "POST" });
    c.evidence_id = m.evidence_id;
    c.evidence_available = true;
    toast(`Sealed ${m.evidence_id}`);
    renderDetail(c);
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
    button.disabled = false;
  }
}

async function nextCameras(c) {
  try {
    const res = await api(`/cameras/${encodeURIComponent(c.camera_id)}/next`
      + `?seen_at=${encodeURIComponent(c.t_norm)}`);
    const box = $("#detail");
    const panel = el("div", { class: "panel" },
      el("h3", {}, `Where to look next from ${c.camera_id}`));
    const body = el("div", { class: "body" });
    if (!res.suggestions.length) {
      body.append(el("div", { class: "notice neutral" }, res.note));
    } else {
      const table = el("table", { class: "data" },
        el("thead", {}, el("tr", {},
          el("th", { text: "Camera" }), el("th", { text: "Priority" }),
          el("th", { text: "Transition" }), el("th", { text: "Fit" }),
          el("th", { text: "ANPR" }), el("th", { text: "Availability" }))));
      const tb = el("tbody");
      for (const s of res.suggestions) {
        tb.append(el("tr", { title: s.explanation },
          el("td", { class: "mono", text: s.camera_id }),
          el("td", { class: "num", text: num(s.priority_score) }),
          el("td", { class: "num", text: num(s.transition_probability) }),
          el("td", { class: "num", text: num(s.travel_time_fit) }),
          el("td", {}, gradeChip(s.capability.anpr, "")),
          el("td", { text: s.availability })));
      }
      table.append(tb);
      body.append(table);
      body.append(el("div", { class: "section-note", style: "padding:8px 0 0",
                              text: res.note }));
    }
    panel.append(body);
    box.append(panel);
    panel.scrollIntoView({ block: "nearest" });
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
  }
}

/* ─── trajectory ─────────────────────────────────────────────────────────── */
async function loadTrajectory(plate) {
  try {
    const res = await api(`/trajectory/${encodeURIComponent(plate)}`);
    state.trajectory = res;
    state.hypothesis = 0;
    renderTrajectory();
    await drawTrajectoryOnMap(plate, 0);
  } catch (err) {
    $("#traj-body").replaceChildren(
      el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
}

async function followVehicle(plate) {
    try {
      const res = await api(`/follow/${encodeURIComponent(plate)}`);
      const body = $("#traj-body");
      clear(body);
      body.append(el("div", { class: "notice" },
        el("strong", { text: `Follow vehicle · ${plate}` }),
        `${res.route_confidence?.confirmed_sightings || 0} confirmed sighting(s), `
        + `${res.candidates?.length || 0} ranked follow-up lead(s).`));
      for (const c of res.candidates || []) {
        body.append(el("div", { class: "result" },
          el("div", { class: "top" },
            el("span", { class: "plate", text: c.camera_id }),
            el("span", { class: "chip verify", text: c.status }),
            el("span", { class: "time", text: fmtClock(c.t_norm) })),
          el("div", { class: "meta" },
            el("span", { text: `score ${num(c.score)}` }),
            el("span", { text: c.reason || "ranked lead" }),
            c.distance_m != null && el("span", {
              text: `${Math.round(c.distance_m)} m · ${Math.round(c.elapsed_s)} s`,
            }))));
      }
      for (const x of res.contradictions || []) {
        body.append(el("div", { class: "notice bad" },
          el("strong", { text: "ROUTE_CONTRADICTION" }),
          `${x.from_camera} → ${x.to_camera}: ${x.reason}. `
          + `Distance ${Math.round(x.distance_m)} m, elapsed ${Math.round(x.elapsed_s)} s, `
          + `implied ${Math.round(x.implied_speed_kmh)} km/h.`));
      }
      if (!(res.candidates || []).length && !(res.contradictions || []).length) {
        body.append(el("div", { class: "notice neutral",
          text: "No feasible subsequent camera lead was found in this window." }));
      }
      $("#traj-target").textContent = plate;
    } catch (err) {
      toast(`${err.code}: ${err.message}`, true);
    }
}

function renderTrajectory() {
  const res = state.trajectory;
  const body = $("#traj-body");
  clear(body);
  $("#traj-target").textContent = res.target || "";

  const hyps = res.hypotheses || [];
  const tabs = $("#hyp-tabs");
  clear(tabs);
  if (!hyps.length) {
    $("#traj-status").textContent = "";
    body.append(el("div", { class: "notice neutral" },
      el("strong", { text: "No route could be built" }), res.reason || ""));
    return;
  }
  hyps.forEach((h, i) => {
    tabs.append(el("button", {
      class: `ghost${i === state.hypothesis ? " on" : ""}`,
      onclick: async () => {
        state.hypothesis = i;
        renderTrajectory();
        await drawTrajectoryOnMap(res.target, i);
      },
    }, `${String.fromCharCode(65 + i)} · ${num(h.score)}`));
  });

  const h = hyps[state.hypothesis];
  $("#traj-status").textContent =
    `${h.status} · score ${num(h.score)} · ${new Set(h.camera_sequence).size} camera${new Set(h.camera_sequence).size === 1 ? "" : "s"}`;

  const strip = el("div", { class: "legs" });
  h.camera_sequence.forEach((cam, i) => {
    if (i > 0) {
      const leg = h.legs[i - 1] || {};
      strip.append(el("div", { class: `leg-link ${leg.kind || "UNOBSERVED"}`,
                               title: leg.explanation || "" },
        el("div", { class: "bar" }),
        el("div", { class: "kind", text: (leg.kind || "").replace("_", " ") }),
        el("div", { class: "dt", text: leg.dt_s != null ? `${Math.round(leg.dt_s)} s` : "" })));
    }
    const obs = (res.observations || []).find((o) => o.camera_id === cam);
    strip.append(el("div", {
      class: "leg-node",
      onclick: () => { if (obs) selectResult(obs, null); },
    },
      el("div", { class: "cam", text: cam }),
      el("div", { class: "t", text: fmtClock(h.timestamps[i]) }),
      el("div", { class: "q", text: obs ? `quality ${num(obs.observation_quality)}` : "" })));
  });
  body.append(strip);

  const detail = el("div", { style: "padding:0 12px 12px" });

  /* The timebase verdict decides whether the intervals on this route mean
   * anything at all. It was computed, returned by the API, and never shown —
   * so a route across cameras that replay different windows looked exactly
   * like a route across cameras that share a clock. It goes first, because a
   * reader who takes the timings on trust has already been misled by the time
   * they reach the score. */
  const tb = (state.trajectory || {}).timebase;
  if (tb) {
    const tone = { ALLOWED: "ok", RESTRICTED: "", REFUSED: "bad" }[tb.verdict] ?? "";
    detail.append(el("div", { class: `notice ${tone}` },
      el("strong", { text: `Timebase · ${tb.verdict}` }),
      tb.message || "",
      ...(tb.detail || []).slice(0, 4).map(
        (d) => el("div", { class: "mono", style: "font-size:10.5px", text: d }))));
  }

  detail.append(el("dl", { class: "kv" },
    dt("Status"), dd(h.status),
    dt("Score"), dd(`${num(h.score)} — ordering score, not a probability`),
    dt("Duration"), dd(`${Math.round(h.duration_s)} s`),
    dt("Plate-confirmed"), dd(`${h.evidence.plate_confirmed} of ${h.camera_sequence.length}`),
    dt("Mean quality"), dd(num(h.evidence.mean_observation_quality))));

  for (const g of h.coverage_gaps || []) {
    detail.append(el("div", { class: "notice" },
      el("strong", { text: `Coverage gap · ${g.from_camera} → ${g.to_camera}` }),
      g.explanation));
  }
  for (const c of h.contradictions || []) {
    detail.append(el("div", { class: "notice bad" },
      el("strong", { text: `Contradiction · ${c.from_camera} → ${c.to_camera}` }),
      c.explanation,
      c.alternatives && c.alternatives.length
        ? el("ul", { style: "margin:6px 0 0 16px;padding:0" },
            c.alternatives.map((a) => el("li", { text: a })))
        : null));
  }
  for (const n of h.notes || []) {
    detail.append(el("div", { class: "notice neutral", text: n }));
  }
  const gaps = res.gap_candidates || [];
  if (gaps.length) {
    detail.append(el("div", { class: "notice" },
      el("strong", { text: `${gaps.length} candidate(s) for unobserved legs` }),
      "These cameras could not read the plate. Each is a candidate requiring "
      + "verification, never an identification."));
    for (const g of gaps.slice(0, 6)) {
      detail.append(el("div", {
        class: "result", onclick: () => selectResult(g, null),
      },
        el("div", { class: "top" },
          el("span", { class: "plate", text: g.camera_id }),
          statusChip(g.status),
          el("span", { class: "time", text: fmtClock(g.t_norm) })),
        el("div", { class: "meta" },
          el("span", { text: `score ${num(g.score)}` }),
          g.colour && el("span", { text: g.colour }))));
    }
  }
  body.append(detail);
}

async function drawTrajectoryOnMap(plate, index) {
  try {
    const geo = await api(
      `/gis/trajectory/${encodeURIComponent(plate)}?hypothesis=${index}`);
    if (map1) {
      map1.set("trajectory", geo.geometry);
      if (geo.geometry && geo.geometry.bbox) map1.fit(geo.geometry.bbox, 0.6);
    }
  } catch { /* the trajectory panel already reported the failure */ }
}

$("#btn-attach-traj").addEventListener("click", () => {
  const res = state.trajectory;
  if (!res || !(res.hypotheses || []).length) return toast("No trajectory to attach", true);
  const h = res.hypotheses[state.hypothesis];
  attach("trajectory", h.trajectory_id, h);
});

/* ─── maps ───────────────────────────────────────────────────────────────── */
let map1 = null, map2 = null;

const PRECISION_LABEL = {
  LANDMARK: "±150 m · named junction",
  LOCALITY: "±1.5 km · named locality",
  CITY: "±6 km · town only",
  UNKNOWN: "not located",
};

function legendFor(mode, node) {
  clear(node);
  node.append(el("h4", { text: mode === "capability" ? "ANPR capability" : "Stream health" }));
  const items = mode === "capability"
    ? [["--confirmed", "GOOD — plate reading viable"],
       ["--verify", "DEGRADED — corroboration only"],
       ["--conflict", "UNSUITABLE — plates not recoverable"],
       ["--unknown", "UNKNOWN — not enough evidence yet"]]
    : [["--confirmed", "Streaming"],
       ["--verify", "Degraded / reconnecting"],
       ["--conflict", "Down"],
       ["--unknown", "Not yet observed"]];
  for (const [token, label] of items) {
    node.append(el("div", { class: "item" },
      el("span", { class: "dot", style: `background:var(${token})` }),
      el("span", { text: label })));
  }
  node.append(el("h4", { style: "margin-top:8px" , text: "Route legs" }));
  for (const [cls, token, label] of [
    ["solid", "--confirmed", "OBSERVED"],
    ["dotted", "--unknown", "COVERAGE GAP — nothing could see"],
    ["dashed", "--verify", "UNOBSERVED — a capable camera saw nothing"],
    ["dashed", "--conflict", "CONTRADICTION"]]) {
    node.append(el("div", { class: "item" },
      el("span", { class: "swatch",
                   style: `border-top-style:${cls};border-top-color:var(${token})` }),
      el("span", { text: label })));
  }
  node.append(el("div", { class: "note" },
    "A gap shows where the system cannot observe. It is never evidence about "
    + "where a vehicle was."));
  if (state.derivedLocations) {
    node.append(el("h4", { style: "margin-top:8px", text: "Position accuracy" }));
    for (const [k, label] of Object.entries(PRECISION_LABEL)) {
      if (k === "UNKNOWN") continue;
      node.append(el("div", { class: "item" },
        el("span", { class: "dot",
                     style: `background:var(--ink-3);opacity:${
                       k === "LANDMARK" ? 1 : k === "LOCALITY" ? 0.6 : 0.3}` }),
        el("span", { text: label })));
    }
    node.append(el("div", { class: "note" },
      "These positions are derived from each camera's name, not surveyed. They "
      + "place a camera near the right junction so corridors can be reasoned "
      + "about; they are never evidence of where a vehicle was."));
  }
}

function renderRegistryRail(located, unlocated) {
  const rail = $("#registry-rail");
  if (!rail) return;
  clear(rail);
  const all = [...(located || []), ...(unlocated || [])]
    .sort((a, b) => String(a.camera_id).localeCompare(String(b.camera_id)));
  rail.append(el("div", { class: "registry-rail-head", text:
    `Registry ${all.length} cameras · `
    + `${(located || []).length} on the map · `
    + `${(unlocated || []).length} without surveyed coordinates` }));
  const row = el("div", { class: "registry-rail-row" });
  for (const c of all) {
    const unlocatedCam = c.located === false || c.lat == null || c.lon == null;
    const card = el("button", {
      class: "registry-chip" + (unlocatedCam ? " unlocated" : ""),
      type: "button",
      title: c.location_basis || "",
    });
    const img = el("img", { alt: c.camera_id });
    card.append(
      el("div", { class: "registry-thumb" }, img),
      el("div", { class: "name", text: c.camera_id }),
      el("div", { class: "sub",
                  text: unlocatedCam
                    ? "not on the map"
                    : (c.district || "") }));
    card.addEventListener("click", () => {
      if (!unlocatedCam && map2 && c.lat != null && c.lon != null) {
        map2.centre = [c.lat, c.lon];
        map2.zoom = Math.max(map2.zoom, 14);
        map2.draw();
      }
      onMapSelect({ kind: "camera", id: c.camera_id, data: c }, map2);
    });
    fillRegistryStill(img, c.camera_id);
    row.append(card);
  }
  rail.append(row);
}

async function fillRegistryStill(img, id) {
  try {
    const res = await fetch(`/cameras/${encodeURIComponent(id)}/snapshot`,
                            { headers: authHeaders() });
    if (!res.ok) return;
    const blob = await res.blob();
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    const url = URL.createObjectURL(blob);
    img.dataset.url = url;
    img.src = url;
  } catch { /* the chip still names the camera */ }
}

async function refreshMapLayers(map, bbox) {
  const q = new URLSearchParams();
  if (bbox) {
    q.set("bbox", `${bbox.west.toFixed(4)},${bbox.south.toFixed(4)},`
      + `${bbox.east.toFixed(4)},${bbox.north.toFixed(4)}`);
  }
  q.set("zoom", String(Math.round(map.zoom)));
  try {
    const cams = await api(`/gis/cameras?${q}`);
    map.set("cameras", cams.features);
    state.cameras = cams.features;
    state.derivedLocations = cams.features.some(
      (f) => f.location_basis === "DERIVED_FROM_NAME");
    const note = $("#viewport-note");
    if (note && map === map1) {
      note.textContent = cams.clustered
        ? `${cams.returned} clusters · ${cams.matched} cameras in view`
        : `${cams.matched} cameras in view`;
    }
    if (map === map2) {
      $("#map2-count").textContent = `${cams.matched} on the map`
        + (cams.cameras_without_location
          ? ` · ${cams.cameras_without_location} in the registry without coordinates`
          : "")
        + (cams.registry_total
          ? ` · ${cams.registry_total} registered` : "");
      /* The rail is the registry, not the viewport. A zoomed map that hid
       * eleven unlocated cameras plus everything off-screen would look like an
       * estate of whatever happened to be in view. */
      try {
        const full = bbox ? await api("/gis/cameras?zoom=16") : cams;
        renderRegistryRail(
          (full.features || []).filter((f) => !f.cluster),
          full.unlocated || []);
      } catch {
        renderRegistryRail(
          (cams.features || []).filter((f) => !f.cluster),
          cams.unlocated || []);
      }
    }
    if (map.show.alerts) {
      const al = await api(`/gis/alerts?${q}`);
      map.set("alerts", al.features);
    } else { map.set("alerts", []); }
    if (map.show.coverage) {
      const cov = await api(`/gis/coverage?${q}`);
      map.set("coverage", cov.gaps);
    } else { map.set("coverage", []); }
  } catch (err) {
    if (err.status !== 401) toast(`Map: ${err.message}`, true);
  }
}

function wireMapControls(root, map, legendNode, modeAttr, toggleAttr) {
  $$(`[${modeAttr}]`, root).forEach((b) => b.addEventListener("click", () => {
    $$(`[${modeAttr}]`, root).forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    map.mode = b.getAttribute(modeAttr);
    legendFor(map.mode, legendNode);
    map.draw();
  }));
  $$(`[${toggleAttr}]`, root).forEach((b) => b.addEventListener("click", async () => {
    const key = b.getAttribute(toggleAttr);
    map.show[key] = !map.show[key];
    b.classList.toggle("on", map.show[key]);
    if (key === "labels") map.draw();
    else await refreshMapLayers(map, map.bbox());
  }));
}

/* An empty map with no explanation reads as "there are no cameras". That is a
 * different statement from "there are cameras and nobody told us where they
 * are", and on the live government grid the second one is true for all thirty.
 * Saying so is the difference between an honest blank and a broken one. */
function noCoordinatesNotice(count) {
  for (const id of ["map-empty-1", "map-empty-2"]) {
    const existing = document.getElementById(id);
    if (existing) existing.remove();
  }
  if (!count) return;
  for (const [wrapSel, id] of [["#view-investigate .map-wrap", "map-empty-1"],
                               ["#view-map .map-wrap", "map-empty-2"]]) {
    const wrap = $(wrapSel);
    if (!wrap) continue;
    const node = el("div", { class: "notice", id },
      el("strong", { text: `${count} cameras registered · none with coordinates` }),
      "These cameras are reachable and being analysed — their measured "
      + "capability and observations are in the Cameras view. What is missing "
      + "is where they are. Location comes from the grid catalogue, which "
      + "requires a signed-in session on the CDN host. Nothing is placed on "
      + "this map that we were not told.");
    node.style.cssText = "position:absolute;left:50%;top:50%;"
      + "transform:translate(-50%,-50%);max-width:36ch;z-index:5;"
      + "box-shadow:var(--shadow)";
    wrap.append(node);
  }
}

/* One debounce timer per map. A shared timer meant the second map's fit
   cancelled the first map's pending refresh, and the first map silently never
   loaded its layers. */
const viewportTimers = new WeakMap();

function debounceViewport(map) {
  return (bbox) => {
    clearTimeout(viewportTimers.get(map));
    viewportTimers.set(map, setTimeout(() => refreshMapLayers(map, bbox), 200));
  };
}

async function initMaps() {
  // Ask the server what this deployment has: a basemap is optional, and a map
  // that silently tries to load tiles it will never get is worse than one that
  // draws a graticule and says so.
  let cfg = { map: { tiles: false, google: { enabled: false } } };
  try { cfg = await api("/config"); } catch { /* not signed in yet */ }
  await applyDeploymentConfig(cfg);
  const mapOpts = state.mapOpts || {};

  map1 = new MapView($("#map"),
    { ...mapOpts, onSelect: (hit) => onMapSelect(hit, map1) });
  map1.onViewport = debounceViewport(map1);
  map2 = new MapView($("#map2"),
    { ...mapOpts, onSelect: (hit) => onMapSelect(hit, map2) });
  map2.onViewport = debounceViewport(map2);

  legendFor("health", $("#legend"));
  legendFor("health", $("#legend2"));
  wireMapControls(document, map1, $("#legend"), "data-mode", "data-toggle");
  wireMapControls(document, map2, $("#legend2"), "data-mode2", "data-toggle2");

  try {
    const ext = await api("/gis/extent");
    if (ext.extent) {
      state.extent = ext.extent;
      map1.fit(ext.extent);
      map2.fit(ext.extent);
      noCoordinatesNotice(null);
    } else {
      // An empty map with no explanation reads as "no cameras". It is not the
      // same thing as "cameras exist and we were not told where they are", and
      // the difference is the whole reason the notice exists.
      noCoordinatesNotice(ext.cameras_without_location || 0);
      await refreshMapLayers(map1, map1.bbox());
    }
  } catch (err) {
    // 401 before sign-in is expected and silent. Anything else is a fault and
    // must be visible: a bare `catch {}` here hid a ReferenceError and the
    // symptom was simply that a panel never appeared.
    if (!(err instanceof ApiError) || err.status !== 401) {
      console.error("map initialisation failed", err);
      toast(`Map initialisation failed: ${err.message}`, true);
    }
  }
}

$("#btn-fit").addEventListener("click", async () => {
  const ext = await api("/gis/extent");
  if (ext.extent) map1.fit(ext.extent);
});
$("#btn-fit2").addEventListener("click", async () => {
  const ext = await api("/gis/extent");
  if (ext.extent) map2.fit(ext.extent);
});

async function onMapSelect(hit, map) {
  if (!hit) return;
  if (hit.kind === "cluster") {
    map.centre = [hit.data.lat, hit.data.lon];
    map.zoom = Math.min(19, map.zoom + 2);
    map.draw();
    await refreshMapLayers(map, map.bbox());
    return;
  }
  if (hit.kind !== "camera" && hit.kind !== "trajectory-node") return;
  try {
    const ctx = await api(`/cameras/${encodeURIComponent(hit.id)}`);
    const target = map === map2 ? $("#map-detail") : null;
    const cap = (ctx.capability || [])[0] || {};
    const summary =
      `${ctx.camera.camera_id} · ${ctx.camera.name || ""} · `
      + `${ctx.camera.district || ""} · ${ctx.camera.department || ""} — `
      + `state ${(ctx.health || {}).state || "UNKNOWN"}, `
      + `ANPR ${cap.anpr_grade || "UNKNOWN"}, `
      + `appearance ${cap.vehicle_reid_grade || "UNKNOWN"}, `
      + `${(ctx.counts || {}).observations || 0} observations, `
      + `${ctx.neighbours.length} evidenced neighbours`;
    /* Where a position came from, beside the position. A camera placed from
     * its name is not the same claim as one whose own signage confirms it, and
     * an investigator reading a corridor off this map is entitled to see which
     * this is without leaving the screen. */
    const cam = ctx.camera;
    const basis = cam.location_basis && cam.location_basis !== "UNKNOWN"
      ? `position ${cam.location_precision || "UNKNOWN"}, `
        + `${String(cam.location_basis).toLowerCase().replace(/_/g, " ")}`
      : "no recorded position";
    if (target) {
      clear(target);
      target.append(el("div", { text: summary }));
      target.append(el("div", { class: "muted", style: "margin-top:4px", text: basis }));
      if (cam.location_note) {
        target.append(el("div", {
          class: "notice neutral", style: "margin-top:6px",
          text: cam.location_note }));
      }
      target.append(el("div", { class: "live-actions", style: "display:flex;margin-top:8px" },
        el("button", { class: "primary", onclick: () => {
          show("live");
          const tile = $(`#live .live-tile[data-camera="${CSS.escape(hit.id)}"]`);
          openLive(tile || el("div"), hit.id);
        } }, "Live video"),
        el("button", { class: "ghost", onclick: () => {
          if ($("#q-camera")) $("#q-camera").value = hit.id;
          show("investigate");
        } }, "Events")));
    } else {
      toast(summary);
    }
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
  }
}

/* ─── overview ───────────────────────────────────────────────────────────── */
/* ─── command overview ────────────────────────────────────────────────────
 * Where a shift starts. Three questions in the order they actually arrive:
 * what needs attention, what is being worked, and whether the machinery under
 * it is sound. The camera wall is not here — it is a thing you look at once
 * you know which camera you want.
 */
/* ─── overview ───────────────────────────────────────────────────────────── */
loaders.overview = async () => {
  const box = $("#overview");
  clear(box);
  box.append(el("div", { class: "ov-page" }, loadingNote("Loading the shift picture…")));
  try {
    const [o, marksPay, cmd] = await Promise.all([
      api("/overview"),
      api("/marks").catch(() => ({ marks: [] })),
      api("/command/summary").catch(() => null),
    ]);
    const copy = situationCopy(o);
    const hour = o.observations.marks_last_hour || {};
    const located = (o.cameras.by_state && true);
    const by = o.cameras.by_state || {};
    const streaming = Number(by.STREAMING || 0) + Number(by.OBSERVED || 0);
    const anpr = o.capability_anpr || {};
    const good = anpr.GOOD || 0;
    const deg = anpr.DEGRADED || 0;
    const uns = anpr.UNSUITABLE || 0;
    const unk = anpr.UNKNOWN || 0;
    const totCam = o.cameras.total || 1;
    const bar = (n, cls) => el("div", { class: `bar ${cls || ""}` },
      el("i", { style: `width:${Math.min(100, (Number(n) / totCam) * 100)}%` }));
    const cap = (title, hint, n, color) => el("div", { class: "cap-row" },
      el("div", { class: "lab" }, title, el("small", { text: hint })),
      el("div", { class: "n", text: String(n) }),
      el("div", { class: "cap-track" },
        el("i", { style: `width:${Math.min(100, (n / totCam) * 100)}%;background:${color}` })));

    const alerts = (o.alerts.recent || []).filter((a) => a.status === "OPEN").slice(0, 4);
    let marks = (o.observations.recent_marks || marksPay.marks || []);
    if (state.dataHolds === "DEMONSTRATION") {
      const keep = new Set(["C-014", "C-021"]);
      const preferred = marks.filter((m) => keep.has(m.camera_id));
      marks = preferred.length ? preferred : marks;
    }
    marks = preferUsableStills(marks).slice(0, 12);
    const published = Number(o.cameras.published_marks
      || o.observations.cameras_with_plate || 0);
    const withStill = Number(o.cameras.with_still || 0);
    const showing = Math.max(streaming, withStill);

    clear(box);
    const kpis = el("div", { class: "kpi-row" },
      el("div", { class: "kpi" },
        el("h4", { text: "Cameras onboarded" }),
        el("div", { class: "big", text: String(o.cameras.total) }),
        el("div", { class: "sub", text: copy.rest.split(".")[0] || Object.entries(by).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ") }),
        bar(o.cameras.total)),
      el("div", { class: "kpi" },
        el("h4", { text: "Showing a frame" }),
        el("div", { class: "big", text: String(showing) }),
        el("div", { class: "sub", text: streaming
          ? `${by.STREAMING || 0} streaming · ${by.OBSERVED || 0} observed`
          : `${withStill} cameras have a stored still` }),
        bar(showing, "green")),
      el("div", { class: "kpi" },
        el("h4", { text: "Marks read, last hour" }),
        el("div", { class: "big", text: String(hour.distinct || o.observations.distinct_plates || 0) }),
        el("div", { class: "sub", text: `${hour.confirmed || o.observations.plate_confirmed || 0} confirmed · ${hour.leads || o.observations.plate_leads || 0} single-frame leads` }),
        bar(hour.distinct || o.observations.distinct_plates || 0)),
      el("div", { class: "kpi" },
        el("h4", { text: "Alerts unacknowledged" }),
        el("div", { class: "big", text: String(o.alerts.open) }),
        el("div", { class: "sub", text: "each names the watchlist rule that fired" }),
        bar(o.alerts.open, "red")),
      cmd ? el("div", { class: "kpi" },
        el("h4", { text: "Persons / vehicles in store" }),
        el("div", { class: "big", text: `${cmd.persons_detected || 0} / ${cmd.vehicles_tracked || 0}` }),
        el("div", { class: "sub", text: `${cmd.anpr_reads_per_min || 0} ANPR / min · ${cmd.events_per_min || 0} events / min · ${cmd.label}` }),
        bar(cmd.persons_detected || 0)) : null);

    const prove = el("div", { class: "ov-card" },
      el("h3", { text: "What the estate can prove" }),
      el("p", { class: "lede", text: "Graded from each camera's own stream, never declared by the vendor." }),
      cap("Published a mark", "a registration was read from this camera", published, "var(--confirmed)"),
      cap("Can read a plate", "a real read exists", good, "var(--confirmed)"),
      cap("Corroboration only", "reads exist but confirm, never identify", deg, "#c4b49a"),
      cap("Cannot read a plate", "measured, not assumed", uns, "var(--conflict)"),
      cap("Not graded", "no capability sample has been run", unk, "var(--ink-faint)"),
      unk ? el("div", { class: "cap-note", text:
        `${unk} camera${unk === 1 ? " is" : "s are"} not graded. That is an absence of evidence about those cameras, not a poor grade.` }) : null);

    const open = el("div", { class: "ov-card" },
      el("span", { class: "pill", text: `${o.alerts.open} unacknowledged` }),
      el("h3", { text: "Open alerts" }),
      el("p", { class: "lede", text: "Nothing becomes an alert unless a watchlist rule fires, and the rule that fired is named on the row." }),
      alerts.length
        ? el("div", { class: "alert-list" },
            ...alerts.map((a) => el("div", { class: "alert-hit" },
              el("div", { class: "pl plate-read", text: a.plate || "—" }),
              el("div", { class: "tm", text: fmtAlertClock(a) }),
              el("div", { class: "meta", text:
                `${String(a.category || "watchlist").replace(/_/g, " ")} · ${a.camera_id || ""} · ${a.priority || ""}` }))))
        : el("div", { class: "cap-note", text: "No open alert." }));

    const gallery = el("div", { class: "ov-card", style: "grid-column:1/-1" },
      el("h3", { text: "Marks, with location" }),
      el("p", { class: "lede", text: "Distinct registration marks as last published, with the camera and district that saw them. A still is the camera, not an enhanced plate." }),
      marks.length
        ? el("div", { class: "plate-gallery" }, ...marks.map(plateCard))
        : el("div", { class: "cap-note", text: "No registration mark in this store yet." }));

    box.append(el("div", { class: "ov-page" },
      el("p", { class: "ov-kicker" },
        el("strong", { text: "Overview" }), "estate health, capability and open alerts"),
      kpis,
      el("div", { class: "ov-split" }, prove, open),
      gallery));

    fillNavFoot(o);
    loadHealthPanel(el("div")); // keep sys-dot updated
    paintCommandStatus(cmd, o);
  } catch (err) {
    clear(box);
    box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
};

function preferUsableStills(marks) {
  const rows = Array.isArray(marks) ? marks.slice() : [];
  const good = rows.filter((m) => m.still_ok !== false);
  const rest = rows.filter((m) => m.still_ok === false);
  return good.length ? good.concat(rest) : rows;
}

function plateRead(plate) {
  return el("div", { class: "plate-read", text: String(plate || "—").replace(/\s+/g, "").toUpperCase() });
}

function plateCard(m) {
  const showStill = m.still_ok !== false;
  const img = el("img", { alt: m.plate });
  const still = el("div", { class: "still" }, showStill ? img : plateRead(m.plate));
  const card = el("button", { class: "plate-card", type: "button" },
    still,
    el("div", { class: "read" }, plateRead(m.plate)),
    el("div", { class: "where", text:
      `${m.camera_id} · ${m.name || ""} · ${m.district || "location unknown"} · ${fmtClock(m.t)}` }));
  if (showStill) {
    refreshTile(img, m.camera_id).catch(() => {
      still.replaceChildren(plateRead(m.plate));
    });
  }
  card.addEventListener("click", () => {
    const q = $("#q-plate");
    if (q) q.value = m.plate;
    show("investigate");
    $("#search-form")?.requestSubmit();
  });
  return card;
}

function fillNavFoot(o) {
  const foot = $("#nav-foot");
  if (!foot || !o) return;
  const hour = o.observations.marks_last_hour || {};
  const good = (o.capability_anpr && o.capability_anpr.GOOD) || 0;
  clear(foot);
  const row = (n, t) => el("div", { class: "nf" },
    el("b", { text: String(n) }), el("span", { text: t }));
  foot.append(
    row(o.cameras.total, "cameras onboarded"),
    row(good, "graded good for plate reading"),
    row(hour.distinct || o.observations.distinct_plates || 0, "marks read in the last hour"),
    row(o.alerts.open, "alerts open, unacknowledged"));
}

/* System health, also written into the nav dot so a degraded subsystem is
 * visible from every screen without anyone going to look for it. */
async function loadHealthPanel(body) {
  clear(body);
  try {
    const h = await api("/system/health");
    const dot = $("#sys-dot");
    if (dot) { dot.dataset.state = h.overall; dot.title = `System: ${h.overall}`; }
    for (const c of h.components) {
      body.append(el("div", { class: "health-row" },
        el("span", { class: `state state-${c.state}`, text: c.state }),
        el("div", {},
          el("div", { class: "what", text: c.component.replace(/_/g, " ") }),
          el("div", { class: "why", text: (c.component === "grid_access"
            ? String(c.detail || "").replace(/Refresh SENTINEL_GRID_PASSWORD[\s\S]*?\./, "Refresh the stream credential from the sandbox portal.")
            : c.detail) }))));
    }
  } catch (err) {
    body.append(el("div", { class: "notice bad", style: "margin:10px 14px" },
      `${err.code}: ${err.message}`));
  }
}

async function loadCasePanel(body) {
  clear(body);
  try {
    const c = await api("/cases");
    if (!c.count) {
      body.append(el("div", { class: "section-note", style: "padding:10px 14px" },
        "No case is open. Every search is bound to one — open a case before "
        + "searching, and the reason is recorded with the result."));
      return;
    }
    for (const k of c.cases.slice(0, 6)) {
      body.append(el("div", { class: "stat-row" },
        el("span", { class: "lbl mono", text: k.case_id }),
        el("span", { class: "sub", text: `${k.classification || "—"} · ${k.district || "—"}` })));
    }
  } catch (err) {
    body.append(el("div", { class: "notice", style: "margin:10px 14px" },
      `${err.code}: ${err.message}`));
  }
}

async function loadActivityPanel(body) {
  clear(body);
  try {
    const a = await api("/audit?limit=8");
    if (!a.entries.length) {
      body.append(el("div", { class: "section-note", style: "padding:10px 14px" },
        "Nothing has been searched yet in this deployment."));
      return;
    }
    body.append(auditTable(a.entries.slice(0, 8)));
  } catch (err) {
    /* An investigator is not an auditor: this panel is empty for them by
     * design, and saying so beats showing a permission error on the home
     * screen every time they open it. */
    body.append(el("div", { class: "section-note", style: "padding:10px 14px" },
      err.code === "PERMISSION_DENIED"
        ? "The audit log is readable by auditors and supervisors. Your role "
          + "does not hold audit:read — which is the separation working, not a fault."
        : `${err.code}: ${err.message}`));
  }
}

function card(title, big, sub, extra) {
  return el("div", { class: "card" },
    el("h4", { text: title }),
    el("div", { class: "big", text: big }),
    sub && el("div", { class: "sub", text: sub }),
    extra);
}

function bars(counts, tokens) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return el("div", { class: "bars" }, Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => el("div", { class: "b" },
      el("span", { class: "lab", text: k }),
      el("span", { class: "track" },
        el("span", { class: "fill",
                     style: `width:${(v / total) * 100}%;background:var(${tokens[k] || "--unknown"})` })),
      el("span", { class: "num", text: Number(v).toLocaleString() }))));
}


/* ─── analytics ───────────────────────────────────────────────────────────
 * What the estate can actually do, and what it has actually produced. Kept
 * separate from Cameras because the question is different: Cameras answers
 * "tell me about cam04", Analytics answers "what is this estate good for".
 */
function fillAnalyticsCapability(body, c) {
  const tally = (key) => c.features.reduce((acc, f) => {
    const v = f[key] || "UNKNOWN";
    acc[v] = (acc[v] || 0) + 1;
    return acc;
  }, {});
  clear(body);
  for (const [label, key] of [["Plate reading (ANPR)", "anpr"],
                              ["Appearance", "vehicle"],
                              ["Presence", "presence"]]) {
    const t = tally(key);
    body.append(el("div", { class: "stat-row" },
      el("span", { class: "n", text: String(t.GOOD || 0),
                   style: (t.GOOD || 0) ? "" : "color:var(--ink-faint)" }),
      el("span", { class: "lbl", text: label }),
      el("span", { class: "sub", text: Object.entries(t)
        .filter(([k]) => k !== "GOOD")
        .map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ") || "—" })));
  }
  body.append(el("div", { class: "section-note", style: "padding:8px 14px" },
    "Grades are measured from each camera's own stream, never declared by a "
    + "catalogue. UNKNOWN means not enough evidence to grade — it is not a "
    + "poor grade."));
}

function fillAnalyticsYield(body, c, overview) {
  clear(body);
  if (overview) {
    const obs = overview.observations || {};
    body.append(
      el("div", { class: "stat-row" },
        el("span", { class: "n",
                     text: Number(obs.distinct_plates || 0).toLocaleString() }),
        el("span", { class: "lbl", text: "distinct marks in the live store" }),
        el("span", { class: "sub",
                     text: `${Number(obs.cameras_with_plate || 0)} cameras · `
                           + `${Number(obs.plate_confirmed || 0).toLocaleString()} confirmed / `
                           + `${Number(obs.plate_leads || 0).toLocaleString()} leads` })),
      el("div", { class: "stat-row" },
        el("span", { class: "n",
                     text: Number(obs.persons || 0).toLocaleString(),
                     style: obs.persons ? "" : "color:var(--ink-faint)" }),
        el("span", { class: "lbl", text: "person observations" }),
        el("span", { class: "sub",
                     text: "same detector pass as vehicles · never plated" })),
      el("div", { class: "stat-row" },
        el("span", { class: "n",
                     text: Number(obs.person_long_stay || 0).toLocaleString(),
                     style: obs.person_long_stay ? "" : "color:var(--ink-faint)" }),
        el("span", { class: "lbl", text: "person long-stay reports" }),
        el("span", { class: "sub",
                     text: obs.person_long_stay
                       ? `longer than ${Number(obs.person_dwell_s || 12)} s on one camera · `
                         + `${Number(obs.person_long_stay_cameras || 0)} cameras · `
                         + "position and time, not identity, not intrusion"
                       : "none yet — dwell is reported when a person stays on one camera" })),
      ...(() => {
        const types = obs.by_object_type || {};
        if (!Object.keys(types).length) return [];
        const tokens = {
          car: "--ink", person: "--unknown", truck: "--ink-2", bus: "--ink-3",
          motorcycle: "--ink", bicycle: "--ink-faint", van: "--ink-2",
          truck_bus: "--ink-3",
        };
        const n = Object.keys(types).filter((k) => types[k]).length;
        return [
          el("div", { class: "stat-row" },
            el("span", { class: "n", text: String(n) }),
            el("span", { class: "lbl", text: "detector classes in the live store" }),
            el("span", { class: "sub",
                         text: "COCO vehicle and person labels from the same pass · not identity" })),
          bars(types, tokens),
          el("div", { class: "section-note", style: "padding:8px 14px" },
            "A bicycle or a person on one camera is an object report. "
            + "It is not an intrusion judgement and it is not a face."),
        ];
      })(),
      el("div", { class: "stat-row" },
        el("span", { class: "n",
                     text: Number(obs.raw_ocr_attempts || 0).toLocaleString(),
                     style: obs.raw_ocr_attempts ? "" : "color:var(--ink-faint)" }),
        el("span", { class: "lbl", text: "raw OCR attempts stored" }),
        el("span", { class: "sub",
                     text: obs.raw_ocr_attempts
                       ? "every read including rejected format, kept for forensics"
                       : "empty — this ingest process predates the write; published marks are still on observations" })));
  }
  if (!c) {
    if (!overview) {
      body.append(el("div", { class: "notice", style: "margin:10px 14px" },
        "Store counts and the capability sample are both unavailable. "
        + "Capability grades, if they loaded, still stand."));
    }
    return;
  }
  const withSamples = c.features.filter((f) => f.samples);
  const totalSamples = withSamples.reduce((a, f) => a + f.samples, 0);
  /* `plate_reads` is null on rows graded before the count was added — the
   * rate was kept, the count was not. Summing `|| 0` over those nulls
   * rendered "0 registration marks read · 0.00% of observations" for an
   * estate that had read plenty. A missing measurement is not a measured
   * nought, and this panel exists precisely to tell one from the other. */
  const counted = withSamples.filter((f) => f.plate_reads !== null
                                         && f.plate_reads !== undefined);
  const missing = withSamples.length - counted.length;
  const reads = counted.reduce((a, f) => a + f.plate_reads, 0);
  const countedSamples = counted.reduce((a, f) => a + f.samples, 0);
  body.append(
    el("div", { class: "stat-row" },
      el("span", { class: "n", text: String(withSamples.length) }),
      el("span", { class: "lbl", text: "cameras with a capability sample" }),
      el("span", { class: "sub", text: `${c.total - withSamples.length} not yet run` })),
    el("div", { class: "stat-row" },
      el("span", { class: "n", text: totalSamples.toLocaleString() }),
      el("span", { class: "lbl", text: "observations in that sample" })),
    el("div", { class: "stat-row" },
      el("span", { class: "n",
                   text: counted.length ? String(reads) : "—",
                   style: reads ? "" : "color:var(--ink-faint)" }),
      el("span", { class: "lbl", text: "plated observations in that sample" }),
      el("span", { class: "sub", text: !counted.length
        ? "not recorded — re-grade from stored observations to count them"
        : `${(reads / countedSamples * 100).toFixed(2)}% of the sample`
          + (missing ? `, across ${counted.length} of ${withSamples.length} `
                     + "cameras; the rest were graded before the count was kept"
                     : "")
          + " · this is yield, not the live-store mark count" })));
  body.append(el("div", { class: "section-note", style: "padding:8px 14px" },
    "ANPR grade GOOD is a claim about geometry and light (yield ≥ 35% at ≥ 90 px). "
    + "A camera graded UNSUITABLE can still have published a mark. "
    + "Re-grade from stored observations on Cameras to refresh the sample."));
}

function fillAnalyticsTimebase(body, t) {
  clear(body);
  if (!t.clusters.length) {
    body.append(el("div", { class: "notice", style: "margin:10px 14px" },
      el("strong", { text: "No cluster established" }),
      "Cross-camera correlation is refused for every pair until two cameras "
      + "are shown to share a timebase. Nothing has shown that yet."));
  }
  for (const cl of t.clusters) {
    body.append(el("div", { class: "stat-row" },
      el("span", { class: "n", text: String(cl.member_count) }),
      el("span", { class: "lbl mono", text: cl.cluster_id }),
      el("span", { class: "sub", text: `${cl.basis} · ${cl.confidence || "confidence not stated"}` })));
    if (cl.note) {
      body.append(el("div", { class: "section-note", style: "padding:2px 14px 10px" },
        cl.note));
    }
  }
  const usable = t.cameras.filter((x) => x.usable_for_correlation).length;
  const clustered = t.cameras.filter((x) => x.time_cluster).length;
  body.append(el("div", { class: "section-note", style: "padding:8px 14px" },
    `${clustered} of ${t.cameras.length} cameras sit in a cluster; ${usable} `
    + "have timing sound enough to correlate at all. A camera whose PTS jumps "
    + "backwards cannot be placed on any timeline, cluster or no."));
}

function panelFetchError(body, err) {
  clear(body);
  body.append(el("div", { class: "notice bad", style: "margin:10px 14px" },
    `${err.code}: ${err.message}`));
}

loaders.analytics = async () => {
  const box = $("#analytics");
  clear(box);
  const grid = el("div", { class: "command-grid" });
  box.append(grid);

  const mk = (title, meta) => {
    const body = el("div", {});
    const p = el("div", { class: "panel" },
      el("div", { class: "panel-head" }, el("h3", { text: title }),
        meta ? el("span", { class: "meta", text: meta }) : null),
      body);
    p.body = body;
    grid.append(p);
    return p;
  };

  const cap = mk("Capability across the estate");
  const yieldPanel = mk("What analytics produced");
  const timebase = mk("Timebase clusters");
  timebase.classList.add("wide");
  cap.body.append(loadingNote());
  yieldPanel.body.append(loadingNote());
  timebase.body.append(loadingNote());

  /* Capability, store yield, and timebase are independent reads. Awaiting
   * them in series left the last two panels blank for the duration of
   * /overview on a large live store — the walkthrough and a judge who
   * clicks Analytics both saw empty columns next to a filled grade list.
   * Paint each panel as its call returns; yield waits only on the two
   * reads it actually uses. */
  const capP = api("/gis/capability").then((c) => {
    fillAnalyticsCapability(cap.body, c);
    return c;
  }, (err) => { panelFetchError(cap.body, err); return null; });
  const ovP = api("/overview").then((o) => o, () => null);
  const tbP = api("/gis/timebase").then((t) => {
    fillAnalyticsTimebase(timebase.body, t);
    return t;
  }, (err) => { panelFetchError(timebase.body, err); return null; });
  const [c, o] = await Promise.all([capP, ovP]);
  fillAnalyticsYield(yieldPanel.body, c, o);
  await tbP;
};

/* ─── system ──────────────────────────────────────────────────────────────
 * Whether the machinery is sound, with the evidence each verdict rests on.
 * UNKNOWN is shown as UNKNOWN and never as green: a dashboard that reports
 * healthy because it never looked converts ignorance into assurance.
 */
loaders.system = async () => {
  const box = $("#system");
  clear(box);
  try {
    const h = await api("/system/health");
    const dot = $("#sys-dot");
    if (dot) { dot.dataset.state = h.overall; dot.title = `System: ${h.overall}`; }

    box.append(el("div", { class: `notice ${
      h.overall === "HEALTHY" ? "ok" : h.overall === "FAILED" ? "bad" : "" }` },
      el("strong", { text: `System ${h.overall}` }), h.note));

    box.append(hybridArchitecture());
    box.append(worldSystemsResearch());
    try {
      const sys = await api("/command/systems");
      const table = el("table", { class: "data" },
        el("thead", {}, el("tr", {},
          el("th", { text: "System" }), el("th", { text: "Department" }),
          el("th", { text: "Vendor" }), el("th", { text: "Protocol" }),
          el("th", { text: "Cameras" }), el("th", { text: "Health" }),
          el("th", { text: "Last sync" }))));
      const tb = el("tbody");
      for (const s of sys.systems || []) {
        tb.append(el("tr", {},
          el("td", { class: "mono", text: s.system }),
          el("td", { text: s.department }),
          el("td", { text: s.vendor }),
          el("td", { class: "mono", text: s.protocol }),
          el("td", { class: "num", text: String(s.cameras) }),
          el("td", { text: s.health }),
          el("td", { class: "mono", text: s.last_sync || "—" })));
      }
      table.append(tb);
      box.append(el("div", { class: "panel", style: "margin-top:14px" },
        el("div", { class: "panel-head" }, el("h3", { text: "Connected systems" })),
        el("div", { class: "section-note", text: sys.provenance }),
        table));
    } catch { /* command systems optional */ }

    const grid = el("div", { class: "command-grid", style: "margin-top:14px" });
    for (const c of h.components) {
      const body = el("div", {});
      body.append(el("div", { class: "health-row" },
        el("span", { class: `state state-${c.state}`, text: c.state }),
        el("div", {}, el("div", { class: "why", text: c.detail }))));
      /* Every number the verdict was derived from, so a reader can disagree
       * with the verdict rather than having to take it. */
      const facts = Object.entries(c).filter(([k, v]) =>
        !["component", "state", "detail", "providers", "jobs"].includes(k)
        && (typeof v === "number" || typeof v === "string" || typeof v === "boolean"));
      if (facts.length) {
        body.append(el("dl", { class: "kv", style: "padding:8px 14px" },
          facts.flatMap(([k, v]) => [dt(k.replace(/_/g, " ")), dd(String(v))])));
      }
      if (c.component === "ai_providers") {
        for (const pr of c.providers || []) {
          body.append(el("div", { class: "stat-row" },
            el("span", { class: "lbl mono", text: pr.provider }),
            el("span", { class: `chip ${pr.configured ? "confirmed" : "unknown"}`,
                         text: pr.configured ? "configured" : "not configured" }),
            el("span", { class: "sub", text: `${pr.location} · ${pr.role}` })));
        }
      }
      if (c.component === "jobs") {
        for (const j of c.jobs || []) {
          body.append(el("div", { class: "stat-row" },
            el("span", { class: "lbl mono", text: `${j.job_class} ${j.name}` }),
            el("span", { class: "sub", text: `pid ${j.pid} · ~${j.working_set_mb} MB` })));
        }
      }
      grid.append(el("div", { class: "panel" },
        el("div", { class: "panel-head" },
          el("h3", { text: c.component.replace(/_/g, " ") })), body));
    }
    box.append(grid);
    box.append(el("div", { class: "section-note", style: "margin-top:14px" },
      `Checked ${fmtTime(h.generated_at)}`));
  } catch (err) {
    box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
};

function hybridArchitecture() {
  /* The submission is a hybrid. Model 1 is mandatory and kept. Model 2 is
   * viewing as stills, because thirty live video sessions would be thirty
   * extra copies of the government stream. Model 3 is the federation and
   * metadata bus. Model 4 (central recording of every camera) is rejected on
   * modelled bandwidth, not left as an unfinished page. */
  const wrap = el("div", { class: "panel", style: "margin-top:14px" });
  wrap.append(el("div", { class: "panel-head" },
    el("h3", { text: "Submitted architecture — hybrid Models 1+2+3+4+5" })));
  const body = el("div", { style: "padding:10px 14px" });
  const rows = [
    ["Model 1 — Registry & GIS (foundation)",
     "Central CCTV inventory, health and GIS. Positions that cannot be surveyed stay unlocated rather than invented. Map click opens camera detail → live video → events."],
    ["Model 2 — Unified viewing + metadata analytics",
     "Native video (WHEP / stills) with a decoupled overlay. Operator modes: VIDEO / VEHICLES / PEOPLE / ANPR / FULL without restarting streams."],
    ["Model 3 — Federation & event bus (kept)",
     "VMSAdapter contract (RTSP / ONVIF / Generic). DEMO/TEST connected-systems rows are not government VMS integrations. In-process bus with a Kafka-shaped publish/subscribe seam."],
    ["Model 4 — Selective central analytics (not statewide recording)",
     "Regional ingest + selective central ANPR / watchlist / route / alerts. PRIMARY/SECONDARY/PREVIEW/INACTIVE scheduler. Raw 80k video is not centralised — that remains MODELLED bandwidth arithmetic, not a deployment."],
    ["Model 5 — Adaptive regional media / AI",
     "Direct WHEP where the browser can decode; VideoToolbox H.264 bridge where required; RTSP/TCP stays the AI plane."],
  ];
  for (const [title, detail] of rows) {
    body.append(el("div", { class: "stat-row", style: "align-items:flex-start" },
      el("span", { class: "lbl", text: title }),
      el("span", { class: "sub", text: detail })));
  }
  wrap.append(body);
  return wrap;
}

function worldSystemsResearch() {
  /* Honest comparison. Singapore / Dubai / China are larger and more
   * centralised. They were built on cameras chosen for policing, often with
   * face recognition. Copying them here is Model 4 plus biometrics: 160 Gbps
   * of video we cannot ingest, and a face pipeline this build refuses.
   * The claim we will defend: for an accidental, uncalibrated, multi-department
   * estate with no central video, this is the strongest stack we can justify. */
  const wrap = el("div", { class: "panel", style: "margin-top:14px" });
  wrap.append(el("div", { class: "panel-head" },
    el("h3", { text: "Why this stack — and why we will not claim to beat PolCam" })));
  const body = el("div", { style: "padding:10px 14px" });
  body.append(el("p", { class: "section-note", style: "padding:0 0 10px" },
    "Those programmes win at scale on purpose-sited cameras. Gujarat's challenge is the opposite estate. Numbers below are published figures, labelled, not our measurements."));

  const systems = [
    ["Singapore PolCam",
     "90,000+ cameras since 2012; 200,000 planned. Centralised to POCC. Purpose-installed by police. Humans still monitor (Assistant Watch Officers).",
     "Does not transfer: homogeneous, police-sited estate. Copying it here is central video we cannot carry."],
    ["Dubai Oyoon",
     "Ruler: more than 300,000 cameras. Central command. Face recognition is in the published design. AI flags; humans still verify fines.",
     "Dropped on purpose: this build has no face pipeline (India / BSA). Centralising that video is Model 4."],
    ["China Skynet / Sharp Eyes",
     "Official 2018 figure: government departments >30 million cameras. Industry estimates for Skynet are much higher and are not treated as official. Centralised public-security video and face ID.",
     "Different legal regime, different cameras. We will not import face recognition to look like SOTA."],
    ["UK National ANPR Service",
     "~90 million plate reads/day. Video is not centralised — only reads move. 12-month searchable retention.",
     "KEPT as the pattern: metadata-first. Their readers are purpose-built ANPR; ours are hospital gates and bus stands."],
    ["Gujarat TRINETRA / VISWAS / ITMS",
     "Incumbent. 7,000+ CCTV, district command centres, ANPR/RLVD in four cities, VAHAN e-challan.",
     "We complement this. Demonstrating basic ANPR as if it were new would be demonstrating what Gujarat already runs."],
  ];
  for (const [title, what, verdict] of systems) {
    body.append(el("div", { class: "stat-row", style: "align-items:flex-start" },
      el("span", { class: "lbl", text: title }),
      el("span", { class: "sub", text: what + " — " + verdict })));
  }

  body.append(el("h4", { style: "margin:16px 0 8px;font-size:12px",
                         text: "Computer-vision choices — best we can run, not newest on a slide" }));
  const cv = [
    ["Detection",
     "Research frontier: RT-DETRv4 / RF-DETR (2026). We run RT-DETRv2-R18 (Apache-2.0, COCO classes). Newer is registered as a GPU candidate. Ultralytics YOLO rejected: AGPL covers weights."],
    ["ANPR",
     "Selected yolo-v9-t-640 + cct-s-v2-global after measuring the larger -s-608 worse (0.30–0.44 vs 0.83–0.86). Fast-ALPR default rejected: 9-slot OCR truncates Indian 10-character marks. Awiros India OCR is the upgrade path, not yet swapped."],
    ["Vehicle Re-ID",
     "Literature SOTA on VeRi-776 does not transfer (arXiv 2606.01981: 20–40% drop on a new network). We measured DINOv2: decoy 0.941 vs target-to-self 0.412. Dropped as identity. Kept only as a ranking term after physics prunes."],
    ["Multi-camera tracking",
     "Strongest method reviewed (Spatial-Temporal Multi-Cuts) needs bird's-eye calibration. 80,000 uncalibrated departmental cameras will not be surveyed. Camera-link + timebase instead. That is a data/geometry limit, not a missing library."],
    ["Model 4 central VMS",
     "MODELLED: 80,000 × 2 Mbps ≈ 160 Gbps; 30-day ≈ 52 PB. No network Gujarat has carries that. UK NAS already proved metadata-first at national scale. Not unfinished — rejected on arithmetic."],
    ["Face recognition",
     "Mature worldwide. Out of scope here by decision. Dubai and Skynet use it; we will not, and we will not pretend a plate system is a face system."],
  ];
  for (const [title, detail] of cv) {
    body.append(el("div", { class: "stat-row", style: "align-items:flex-start" },
      el("span", { class: "lbl", text: title }),
      el("span", { class: "sub", text: detail })));
  }
  wrap.append(body);
  return wrap;
}


/* ─── live grid ───────────────────────────────────────────────────────────
 * The wall an operator expects. Two ways to see a camera, and the tile says
 * which one it is showing:
 *
 *   * a **cached still**, refreshed on a timer. One capture is shared by every
 *     viewer, because thirty browser tiles must not open thirty RTSP sessions
 *     against the government grid.
 *   * **live video** over WebRTC, negotiated by the browser directly with the
 *     media server. This platform never proxies or transcodes video: doing so
 *     would put a second analytics-sized workload in the path for no
 *     investigative gain.
 *
 * Live video is opened only for the camera an operator has actually clicked.
 * A wall of thirty peer connections is a bandwidth decision nobody made.
 */
const LIVE_REFRESH_MS = 1500;
/* File stills. Thirty parallel reads are still cheaper than one extra RTSP. */
const LIVE_MAX_INFLIGHT = 30;
let liveInflight = 0;
const liveQueue = [];
let liveTimer = null;
let livePlayer = null;

/* Only tiles the operator can actually see are captured. A thirty-camera wall
 * on a laptop shows about eight at a time; capturing the other twenty-two is
 * stream capacity spent on pixels nobody is looking at. */
let liveObserver = null;
let liveCaptureEnabled = true;
let liveLayout = "focus";
let liveDistrict = "all";
let liveCamsAll = [];
let liveWallMode = 12;
let livePriority = "all";
const intelState = {
  analytics: true,
  mode: "full",
  people: true,
  vehicles: true,
  anpr: true,
  tracking: true,
  compare: false,
};
const snapshotInflight = new Map();
const snapshotCache = new Map();
let telemetryTimer = null;

function telemetryValue(started, completed) {
  if (!started) return "not started";
  if (!completed) return "in progress";
  return `${Math.round(completed - started)} ms`;
}

function updateTelemetry() {
  const t = state.telemetry;
  const videos = $$("video").filter((v) => !v.paused && v.readyState >= 2);
  const tiles = $$("#live .live-tile").filter((tile) => {
    const r = tile.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
      && r.top < innerHeight && r.left < innerWidth;
  });
  const set = (id, text) => { const n = $(`#${id}`); if (n) n.textContent = text; };
  set("telemetry-video", `${videos.length} active / ${$$("video").length} total`);
  set("telemetry-visible", `${tiles.length} of ${$$("#live .live-tile").length}`);
  set("telemetry-snapshot", telemetryValue(t.snapshot.started, t.snapshot.completed)
    + (t.snapshot.error ? ` · error: ${t.snapshot.error}` : ""));
  set("telemetry-whep", telemetryValue(t.whep.started, t.whep.completed)
    + (t.whep.error ? ` · error: ${t.whep.error}` : ""));
  set("telemetry-playback", `${t.reconnect}${t.playbackError ? ` · error: ${t.playbackError}` : ""}`);
  const b = t.browser;
  const browserText = b.state === "LIVE"
    ? `LIVE · ${b.fps == null ? "FPS unavailable" : `${b.fps.toFixed(1)} FPS`}`
    : b.state;
  set("telemetry-browser", browserText);
  set("telemetry-frames", b.framesDecoded == null
    ? "UNAVAILABLE" : `${b.framesDecoded} decoded · ${b.framesDropped ?? 0} dropped`);
  set("telemetry-network", b.packetsReceived == null
    ? "UNAVAILABLE"
    : `${b.packetsReceived} received · ${b.packetsLost ?? 0} lost · `
      + `${b.jitterMs == null ? "jitter unavailable" : `${b.jitterMs.toFixed(1)} ms jitter`}`);
  set("telemetry-codec", b.codec || "not reported");
}

function startTelemetry() {
  if (telemetryTimer) return;
  telemetryTimer = setInterval(updateTelemetry, 500);
  updateTelemetry();
}

function streamPriority(cam) {
  if (livePlayer?.id && livePlayer.id === cam?.camera_id) return "PRIMARY";
  const declared = String(cam?.stream_priority || cam?.priority || "").toUpperCase();
  if (["PRIMARY", "SECONDARY", "PREVIEW", "INACTIVE"].includes(declared)) return declared;
  const status = String(cam?.state || "").toUpperCase();
  if (status === "STREAMING") return "SECONDARY";
  if (status === "OBSERVED") return "PREVIEW";
  if (status === "UNKNOWN" || status === "STOPPED" || status === "DOWN"
      || status === "FAILED") return "INACTIVE";
  return "PREVIEW";
}

function wallCams(cams) {
  const filtered = livePriority === "all"
    ? cams
    : cams.filter((cam) => streamPriority(cam).toLowerCase() === livePriority);
  return filtered.slice(0, liveWallMode);
}

/* All visual representations of a camera share this request and blob URL.
 * The grid, filmstrip and table are intentionally separate accessible views,
 * but they must never become separate upstream consumers. */
async function sharedSnapshot(id) {
  const overlay = intelState.analytics ? intelState.mode : "off";
  const key = `${id}:${overlay}:${intelState.people}:${intelState.vehicles}:${intelState.anpr}`;
  const cached = snapshotCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < 1000) return cached;
  const existing = snapshotInflight.get(key);
  if (existing) return existing;
  state.telemetry.snapshot.started = performance.now();
  state.telemetry.snapshot.error = "";
  const qs = new URLSearchParams({
    overlay,
    people: String(intelState.people),
    vehicles: String(intelState.vehicles),
    anpr: String(intelState.anpr),
  });
  const request = fetch(`/cameras/${encodeURIComponent(id)}/snapshot?${qs}`,
                         { headers: authHeaders() })
    .then(async (res) => {
      if (!res.ok) {
        let why = "";
        try { why = (await res.json())?.detail?.message || ""; } catch { /* not json */ }
        const e = new Error(String(res.status));
        e.why = why;
        throw e;
      }
      const blob = await res.blob();
      const old = snapshotCache.get(key);
      if (old?.url) URL.revokeObjectURL(old.url);
      const value = {
        url: URL.createObjectURL(blob),
        age: Number(res.headers.get("X-Frame-Age-Seconds")),
        kind: (res.headers.get("X-Frame-Kind") || "").toLowerCase(),
        source: res.headers.get("X-Frame-Source") || "",
        fetchedAt: Date.now(),
      };
      snapshotCache.set(key, value);
      state.telemetry.snapshot.completed = performance.now();
      return value;
    })
    .catch((err) => {
      state.telemetry.snapshot.error = err.message || "request failed";
      throw err;
    })
    .finally(() => snapshotInflight.delete(key));
  snapshotInflight.set(key, request);
  return request;
}

/* `front` is for a tile the operator has just scrolled to. Without it a newly
 * visible tile joined the back of a queue behind twenty cameras that had
 * scrolled off, so the wall filled everywhere except where anyone was looking. */
function queueStill(img, id, front = false) {
  if (!img || !id) return;
  if (liveQueue.some(([im]) => im === img)) return;
  if (front) liveQueue.unshift([img, id]);
  else liveQueue.push([img, id]);
  setTileState(id, "queued");
  pumpStills();
}

function pumpStills() {
  while (liveInflight < LIVE_MAX_INFLIGHT && liveQueue.length) {
    const [img, id] = liveQueue.shift();
    liveInflight += 1;
    refreshTile(img, id).finally(() => {
      liveInflight -= 1;
      liveProgress();
      pumpStills();
    });
  }
  liveProgress();
}

/* What the wall is actually doing, at the top of the wall.
 *
 * Thirty cameras at one to ten seconds each cannot all be on screen at once,
 * and without this the operator sees a page of dark tiles and concludes the
 * system is broken. It is not broken; it is working through a queue, and it
 * should say so. */
function liveProgress() {
  const box = $("#live-progress");
  if (!box) return;
  const tiles = $$("#live-grid .live-tile");
  const n = (st) => tiles.filter((t) =>
    t.querySelector(".frame")?.dataset.state === st).length;
  const live = n("live");
  const parts = [`${live} of ${tiles.length || $$("#live .live-tile").length} showing a frame`];
  if (liveInflight) parts.push(`${liveInflight} capturing`);
  if (liveQueue.length) parts.push(`${liveQueue.length} queued`);
  const waiting = n("waiting");
  if (waiting) parts.push(`${waiting} waiting for ingest`);
  const failed = n("failed");
  if (failed) parts.push(`${failed} unavailable`);
  box.textContent = parts.join(" · ");
}

/* A tile's frame area always states where it actually is. It must never read
 * "connecting…" for a camera nothing has tried to connect to. */
function setTileState(id, state, text) {
  for (const tile of $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`)) {
    const frame = tile.querySelector(".frame");
    if (!frame || frame.dataset.state === "live") continue;
    frame.dataset.state = state;
    const known = frame.dataset.known || "";
    clear(frame);
    frame.append(el("div", { class: "placeholder" },
      el("div", { text: text || {
        idle: known || "still not requested",
        queued: "waiting for a capture slot",
        waiting: "waiting for ingest to publish a still",
        capturing: "capturing…",
      }[state] || state }),
      known && state !== "idle"
        ? el("div", { class: "known", text: known }) : null));
  }
}

loaders.live = async () => {
  startTelemetry();
  const box = $("#live");
  clear(box);
  liveLayout = liveLayout || "focus";
  box.dataset.layout = liveLayout;
  box.dataset.wall = String(liveWallMode);

  let cams = [];
  try {
    const gis = await api("/gis/cameras?zoom=16");
    cams = [
      ...(gis.features || []).filter((f) => !f.cluster),
      ...(gis.unlocated || []),
    ];
  } catch {
    try {
      cams = (await api(`/gis/capability`)).features || [];
    } catch (err) {
      box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
      return;
    }
  }
  cams.sort((a, b) => String(a.camera_id).localeCompare(String(b.camera_id)));
  cams = cams.filter((c) => c.enabled !== false);
  const demoWall = state.dataHolds === "DEMONSTRATION";
  if (demoWall) {
    const keep = ["OWN-PEOPLE", "OWN-TRAFFIC", "C-014", "C-021"];
    const rank = new Map(keep.map((id, i) => [id, i]));
    cams = cams.filter((c) => rank.has(c.camera_id));
    cams.sort((a, b) => rank.get(a.camera_id) - rank.get(b.camera_id));
  }
  liveCamsAll = cams;
  $("#live-count").textContent = `${cams.length} cameras · wall ${liveWallMode}`;
  $("#n-live").textContent = String(cams.length);
  labelCount("#n-live", "cameras on the wall");

  paintLiveFilters(cams);
  paintLiveWorkspace(cams);
  liveCaptureEnabled = true;
  liveProgress();
  startLiveRefresh();

  if (livePlayer?.id) return;
  const heroId = demoWall ? "OWN-PEOPLE" : (cams[0] && cams[0].camera_id);
  if (heroId) {
    const hero = $(`#live-strip .live-tile[data-camera="${CSS.escape(heroId)}"]`)
      || $(`#live-grid .live-tile[data-camera="${CSS.escape(heroId)}"]`);
    if (hero) setTimeout(() => openLive(hero, heroId), 400);
  }
};

function visibleLiveCams(cams) {
  if (liveDistrict === "all") return cams;
  if (liveDistrict === "Unlocated") return cams.filter((c) => c.located === false);
  return cams.filter((c) => (c.district || "") === liveDistrict);
}

function paintLiveFilters(cams) {
  const bar = $("#live-filters");
  if (!bar) return;
  clear(bar);
  const districts = [...new Set(cams.map((c) => c.district).filter(Boolean))];
  const opts = ["all", ...districts, "Unlocated"];
  for (const d of opts) {
    const b = el("button", { type: "button", text: d === "all" ? "All" : d });
    if ((liveDistrict || "all") === d) b.classList.add("on");
    b.addEventListener("click", () => {
      liveDistrict = d;
      $$("#live-filters button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      paintLiveWorkspace(liveCamsAll);
    });
    bar.append(b);
  }
}

function paintLiveWorkspace(all) {
  const box = $("#live");
  if (!box) return;
  const keep = livePlayer?.id;
  const cams = wallCams(visibleLiveCams(all || liveCamsAll));
  clear(box);
  box.dataset.layout = liveLayout;
  box.dataset.wall = String(liveWallMode);

  const focus = el("div", { class: "live-focus" });
  const stage = el("div", { class: "live-stage", id: "live-stage" });
  const side = el("div", { class: "live-sidecar", id: "live-sidecar" },
    el("h3", { text: "Select a camera" }),
    el("div", { class: "sid", text: "Measured capability is computed from this camera's stream." }));
  const actions = el("div", { class: "live-actions", id: "live-actions" });
  const here = el("div", { class: "here-plates", id: "here-plates" },
    el("div", { class: "here-kicker", text: "Plates read on this camera" }),
    el("div", { class: "here-row", id: "here-plate-row" },
      el("div", { class: "cap-note", text: "Open a camera to see marks read here." })));
  focus.append(stage, side, actions, here);

  const grid = el("div", { class: "live-grid", id: "live-grid" });
  const strip = el("div", { class: "filmstrip", id: "live-strip" });
  const tab = el("table", { class: "data live-tab", id: "live-tab" },
    el("thead", {}, el("tr", {},
      el("th", { text: "Frame" }), el("th", { text: "Camera" }),
      el("th", { text: "Stream" }), el("th", { text: "Marks" }))));
  const tb = el("tbody");
  tab.append(tb);

  liveObserver?.disconnect();
  liveObserver = new IntersectionObserver((entries) => {
    if (!liveCaptureEnabled) return;
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const tile = e.target;
      if (tile.dataset.requested) continue;
      tile.dataset.requested = "1";
      queueStill(tile._img, tile.dataset.camera, true);
    }
  }, { rootMargin: "200px" });

  for (const [index, c] of cams.entries()) {
    const tile = liveTile(c, { state: c.state, frames: c.frames, last_error: c.last_error });
    tile.dataset.wallIndex = String(index);
    grid.append(tile);
    const mini = liveTile(c, { state: c.state, frames: c.frames, last_error: c.last_error });
    mini.dataset.wallIndex = String(index);
    strip.append(mini);
    liveObserver.observe(tile);
    liveObserver.observe(mini);
    tile.dataset.requested = "1";
    mini.dataset.requested = "1";
    if (index < liveWallMode) queueStill(mini._img, c.camera_id);

    const thumb = el("img", { alt: c.camera_id, "data-camera": c.camera_id });
    if (index < liveWallMode) queueStill(thumb, c.camera_id);
    const row = el("tr", {},
      el("td", {}, thumb),
      el("td", {}, el("div", { text: c.name || c.camera_id }),
        el("div", { class: "dim", text: `${c.camera_id} · ${c.district || "—"}` })),
      el("td", { class: "mono", text: `${c.codec || "—"} · ${c.width || "?"}×${c.height || "?"}` }),
      el("td", { text: c.published_marks ? `${c.published_marks} marks` : "no mark" }));
    row.addEventListener("click", () => openLive(tile, c.camera_id));
    tb.append(row);
  }

  const plates = el("div", { class: "ov-card", id: "live-plates", style: "margin:8px 16px 16px" },
    el("h3", { text: "Marks, location-wise" }),
    el("p", { class: "lede", text: "Latest distinct plates in this store, with the camera that published them." }),
    el("div", { class: "plate-gallery", id: "live-plate-gallery" }, loadingNote("Loading marks…")));

  box.append(focus, grid, strip, tab, plates);
  fillLivePlates();
  if (keep) {
    const tile = $(`#live-strip .live-tile[data-camera="${CSS.escape(keep)}"]`)
      || $(`#live-grid .live-tile[data-camera="${CSS.escape(keep)}"]`);
    if (tile) setTimeout(() => openLive(tile, keep), 80);
  }
}

async function fillLivePlates() {
  const g = $("#live-plate-gallery");
  if (!g) return;
  try {
    const res = await api("/marks");
    clear(g);
    const rows = preferUsableStills((res.marks || []).filter((m) => {
      if (state.dataHolds !== "DEMONSTRATION") return true;
      return ["C-014", "C-021"].includes(m.camera_id);
    })).slice(0, 16);
    if (!rows.length) { g.append(el("div", { class: "cap-note", text: "No plate in this store." })); return; }
    for (const m of rows) g.append(plateCard(m));
  } catch (err) {
    clear(g);
    g.append(el("div", { class: "notice", text: err.message || "marks unavailable" }));
  }
}

function gradeWidth(grade) {
  const g = String(grade || "").toUpperCase();
  if (g === "GOOD") return 88;
  if (g === "DEGRADED") return 52;
  if (g === "UNSUITABLE") return 22;
  return 8;
}

function capMeter(label, grade, extra, hint) {
  const g = String(grade || "UNKNOWN");
  const track = el("div", { class: "cap-track" },
    el("i", { style: `width:${gradeWidth(g)}%;background:var(--confirmed)` }));
  return el("div", { class: "cap-block" },
    el("div", { class: "cap-row" },
      el("span", { class: "lab", text: label }),
      el("span", { class: "n", text: extra || g.toLowerCase() })),
    track,
    el("div", { class: "sid", text: hint }));
}

function fillLiveActions(cam) {
  const bar = $("#live-actions");
  if (!bar || !cam) return;
  clear(bar);
  const caseId = ($("#case-id")?.value || state.caseId || "").trim();
  const seal = el("button", { class: "primary", type: "button",
    text: caseId ? `Snapshot & seal to ${caseId}` : "Snapshot & seal" });
  seal.addEventListener("click", () => snapshotSeal(cam));
  const search = el("button", { type: "button", text: "Search marks read here" });
  search.addEventListener("click", () => {
    if ($("#q-camera")) $("#q-camera").value = cam.camera_id;
    if ($("#q-plate")) $("#q-plate").value = "";
    show("investigate");
    $("#search-form")?.requestSubmit();
  });
  const next = el("button", { type: "button", text: "Where to look next" });
  next.addEventListener("click", () => {
    $("#live-sidecar .nbr-list")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  const mapBtn = el("button", { type: "button", text: "Show on estate map" });
  mapBtn.addEventListener("click", () => show("map"));
  bar.append(seal, search, next, mapBtn);
}

async function snapshotSeal(cam) {
  const caseId = ($("#case-id")?.value || state.caseId || "").trim();
  if (!caseId) {
    toast("Set a case in the masthead first", true);
    return;
  }
  try {
    await api(`/cases/${encodeURIComponent(caseId)}/items`, {
      method: "POST",
      body: JSON.stringify({
        item_type: "camera",
        item_ref: cam.camera_id,
        note: `Live snapshot from Focus on ${cam.camera_id}`,
      }),
    });
    toast(`Sealed ${cam.camera_id} to ${caseId}`);
  } catch (err) {
    toast(err.message || "Could not seal", true);
  }
}

function herePlateCard(m) {
  const img = el("img", { alt: m.plate });
  const card = el("button", { class: "here-plate", type: "button" },
    img,
    plateRead(m.plate),
    el("div", { class: "meta", text: `${fmtClock(m.t)}${m.votes ? ` · ${m.votes} votes` : ""}` }));
  fetch(`/cameras/${encodeURIComponent(m.camera_id)}/plate.jpg?plate=${encodeURIComponent(m.plate)}`,
        { headers: authHeaders() })
    .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.blob(); })
    .then((blob) => {
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      const url = URL.createObjectURL(blob);
      img.dataset.url = url;
      img.src = url;
    })
    .catch(() => refreshTile(img, m.camera_id).catch(() => {}));
  card.addEventListener("click", () => {
    card.classList.add("picked");
    $$("#here-plate-row .here-plate").forEach((x) => {
      if (x !== card) x.classList.remove("picked");
    });
    if ($("#q-plate")) $("#q-plate").value = m.plate;
    show("investigate");
    $("#search-form")?.requestSubmit();
  });
  return card;
}

async function fillHerePlates(cameraId) {
  const row = $("#here-plate-row");
  const kicker = $("#here-plates .here-kicker");
  if (!row || !cameraId) return;
  if (kicker) kicker.textContent = `Plates read on ${cameraId}`;
  try {
    const res = await api(`/marks?camera_id=${encodeURIComponent(cameraId)}`);
    clear(row);
    const marks = res.marks || [];
    if (!marks.length) {
      row.append(el("div", { class: "cap-note",
        text: "No registration mark from this camera in the store yet." }));
      return;
    }
    for (const m of marks) row.append(herePlateCard(m));
  } catch (err) {
    clear(row);
    row.append(el("div", { class: "cap-note", text: err.message || "marks unavailable" }));
  }
}

function fillLiveSidecar(cam) {
  const side = $("#live-sidecar");
  if (!side || !cam) return;
  const id = cam.camera_id;
  renderSidecar(cam, null);
  api(`/cameras/${encodeURIComponent(id)}`).then((ctx) => {
    if (livePlayer?.id !== id) return;
    renderSidecar(cam, ctx);
  }).catch(() => {});
}

function renderSidecar(cam, ctx) {
  const side = $("#live-sidecar");
  if (!side || !cam) return;
  const caps = Array.isArray(ctx?.capability) ? ctx.capability : [];
  const cap = caps.reduce((best, r) => (
    !best || (r.samples || 0) > (best.samples || 0) ? r : best), null) || {};
  const anpr = cap.anpr_grade || cam.anpr || cam.anpr_grade || "UNKNOWN";
  const veh = cap.vehicle_reid_grade || cam.vehicle || cam.vehicle_reid_grade || "UNKNOWN";
  const pres = cap.presence_grade || cam.presence || cam.presence_grade || "UNKNOWN";
  const yieldN = cap.plate_yield ?? cam.plate_yield;
  const yieldTxt = (yieldN != null && Number.isFinite(Number(yieldN)))
    ? `${String(anpr).toLowerCase()} · ${Number(yieldN).toFixed(2)} yield`
    : String(anpr).toLowerCase();
  const registry = ctx?.camera || cam;
  const neighbours = ctx?.neighbours || [];
  const nameOf = (cid) => {
    const hit = (liveCamsAll || []).find((c) => c.camera_id === cid);
    return hit?.name || cid;
  };
  clear(side);
  side.append(
    el("h3", { text: registry.name || cam.name || cam.camera_id }),
    el("div", { class: "sid", text:
      `${cam.camera_id} · ${registry.district || cam.district || "—"} · ${registry.codec || cam.codec || ""} · ${registry.width || cam.width || "?"}×${registry.height || cam.height || "?"}` }),
    el("div", { class: "side-label", text: "Measured capability" }),
    capMeter("Plate reading", anpr, yieldTxt,
      "Computed from this camera's own stream. Not graded means too little evidence — never a poor grade."),
    capMeter("Appearance", veh, String(veh).toLowerCase(),
      "Distinguishes one vehicle from another well enough to corroborate — never to identify."),
    capMeter("Presence", pres, String(pres).toLowerCase(),
      "Something passed is recoverable. Person boxes are presence, not identity."),
    el("div", { class: "cap-note", text:
      "Measured, not declared. Every grade is computed from this camera's own stream." }));

  const rows = [
    ["Camera", cam.camera_id],
    ["Site", registry.site || registry.name || "—"],
    ["District", registry.district || "—"],
    ["Department", registry.department || "—"],
    ["Stream", `${registry.codec || cam.codec || "—"} · ${registry.width || cam.width || "?"}×${registry.height || cam.height || "?"}`],
    ["Basis", (registry.location_basis || cam.location_basis || "UNKNOWN").toLowerCase().replace(/_/g, " ")],
  ];
  const table = el("table", { class: "reg-table" });
  for (const [k, v] of rows) {
    table.append(el("tr", {}, el("th", { text: k }), el("td", { text: String(v || "—") })));
  }
  side.append(el("div", { class: "side-label", text: "Registry" }), table);
  const basis = String(registry.location_basis || cam.location_basis || "").toUpperCase();
  if (basis && basis !== "SURVEYED") {
    side.append(el("div", { class: "cap-note warn", text:
      "Position derived from the camera's name. Not a surveyed position — good enough to reason about a corridor, never evidence of where a vehicle was." }));
  }

  const nbrBox = el("div", { class: "nbr-list" });
  side.append(el("div", { class: "side-label", text: "Evidenced neighbours" }), nbrBox);
  if (!neighbours.length) {
    nbrBox.append(el("div", { class: "sid", text: "No transition with a sighting behind it is listed." }));
  } else {
    for (const n of neighbours.slice(0, 8)) {
      const to = n.to_camera || n.camera_id;
      nbrBox.append(el("div", { class: "nbr" },
        el("span", { text: `${to} ${nameOf(to)}` }),
        el("span", { class: "mono", text:
          `${Number(n.confidence || 0).toFixed(2)} · ${n.support || 0} sightings` })));
    }
    nbrBox.append(el("div", { class: "sid", text:
      "Transitions learned from sightings, not geography. A link with no sighting behind it is not listed." }));
  }
}

function istClock() {
  return new Date().toLocaleString("en-IN", {
    hour12: false, timeZone: "Asia/Kolkata",
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).replace(",", "") + " IST";
}

let liveClock = null;
function stopLiveClock() {
  if (liveClock) { clearInterval(liveClock); liveClock = null; }
}

/* Detection overlay is independent of WHEP playback: metadata is polled into a
 * bounded queue and painted on rAF. A stalled detector must not pause video. */
let overlayState = null;
const OVERLAY_STALE_MS = 2500;
const OVERLAY_QUEUE_MAX = 32;

function stopDetectionOverlay() {
  if (!overlayState) return;
  if (overlayState.raf) cancelAnimationFrame(overlayState.raf);
  if (overlayState.poll) clearInterval(overlayState.poll);
  overlayState = null;
}

function startDetectionOverlay(cameraId, canvas) {
  stopDetectionOverlay();
  if (!canvas) return;
  const tracks = new Map(); // track_id -> {bbox, plate, ts, colour}
  overlayState = {
    cameraId, canvas, tracks, raf: 0, poll: 0,
    lastMetaAt: 0, overlayLatencyMs: null,
  };
  const poll = async () => {
    if (!overlayState || overlayState.cameraId !== cameraId) return;
    try {
      if (!intelState.analytics) {
        overlayState.tracks.clear();
      }
      const qs = new URLSearchParams({
        overlay: intelState.analytics ? intelState.mode : "off",
        people: String(intelState.people),
        vehicles: String(intelState.vehicles),
        anpr: String(intelState.anpr),
      });
      const res = await api(`/command/cameras/${encodeURIComponent(cameraId)}/boxes?${qs}`);
      const marks = intelState.analytics ? (res.boxes || []) : [];
      const now = performance.now();
      overlayState.lastMetaAt = now;
      overlayState.tracks.clear();
      let n = 0;
      for (const m of marks) {
        if (n >= OVERLAY_QUEUE_MAX) break;
        const bbox = m.bbox || m.box;
        if (!bbox || bbox.length < 4) continue;
        const tid = String(m.track_id || m.plate || `m${n}`);
        const person = (m.object_type || "").toLowerCase() === "person";
        overlayState.tracks.set(tid, {
          bbox, plate: m.plate || "", ts: now,
          otype: m.object_type,
          conf: m.confidence,
          showTrack: intelState.tracking,
          colour: person ? "#3ec8dc" : (m.plate ? "#28c85a" : "#f1c40f"),
        });
        n += 1;
      }
      const counts = res.counts || res;
      const node = $("#live-counts");
      if (node) {
        node.textContent =
          `People: ${Number(counts.people || 0)} · Vehicles: ${Number(counts.vehicles || 0)} · Tracked: ${Number(counts.tracked || 0)}`;
      }
      if (state.telemetry) {
        state.telemetry.overlayLatencyMs = overlayState.overlayLatencyMs;
      }
    } catch {
      /* overlay must never take down live video */
    }
  };
  const paint = () => {
    if (!overlayState || overlayState.cameraId !== cameraId) return;
    const stage = canvas.parentElement;
    const media = stage?.querySelector("video.live-whep, img");
    const w = media?.clientWidth || stage?.clientWidth || 0;
    const h = media?.clientHeight || stage?.clientHeight || 0;
    if (w && h && (canvas.width !== w || canvas.height !== h)) {
      canvas.width = w; canvas.height = h;
    }
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const now = performance.now();
    for (const [tid, t] of [...tracks.entries()]) {
      if (now - t.ts > OVERLAY_STALE_MS) { tracks.delete(tid); continue; }
      const [x1, y1, x2, y2] = t.bbox;
      // bboxes are normalized 0..1 or pixel coords; support both.
      const norm = Math.max(x1, y1, x2, y2) <= 1.5;
      const rx1 = (norm ? x1 * canvas.width : x1);
      const ry1 = (norm ? y1 * canvas.height : y1);
      const rx2 = (norm ? x2 * canvas.width : x2);
      const ry2 = (norm ? y2 * canvas.height : y2);
      ctx.strokeStyle = t.colour;
      ctx.lineWidth = 2;
      ctx.strokeRect(rx1, ry1, Math.max(1, rx2 - rx1), Math.max(1, ry2 - ry1));
      const label = [t.plate, t.showTrack ? tid : "", t.otype,
                     t.conf != null ? Number(t.conf).toFixed(2) : ""]
        .filter(Boolean).join(" · ");
      if (label) {
        ctx.fillStyle = "rgba(0,0,0,0.55)";
        ctx.fillRect(rx1, Math.max(0, ry1 - 18), Math.min(canvas.width - rx1, 8 * label.length + 10), 16);
        ctx.fillStyle = "#fff";
        ctx.font = "12px ui-monospace, monospace";
        ctx.fillText(label, rx1 + 4, Math.max(12, ry1 - 5));
      }
      overlayState.overlayLatencyMs = Math.round(now - t.ts);
    }
    overlayState.raf = requestAnimationFrame(paint);
  };
  overlayState.poll = setInterval(poll, 1000);
  poll();
  overlayState.raf = requestAnimationFrame(paint);
}

function startLiveClock() {
  stopLiveClock();
  const tick = () => {
    const node = $("#live-stage .hud-clock");
    if (!node) { stopLiveClock(); return; }
    node.textContent = istClock();
  };
  liveClock = setInterval(tick, 1000);
  tick();
}

function fillLiveStage(id) {
  const stage = $("#live-stage");
  if (!stage) return;
  const cam = (liveCamsAll || []).find((c) => c.camera_id === id) || { camera_id: id };
  clear(stage);
  const img = el("img", { alt: `Live ${id}` });
  const fps = cam.measured_fps ? `${Number(cam.measured_fps).toFixed(0)} fps` : "";
  const hud = el("div", { class: "hud" },
    el("span", { class: "hud-chip live", text: "Opening" }),
    (state.liveConfig?.whep && state.dataHolds !== "DEMONSTRATION")
      ? el("span", { class: "hud-chip", text: "WHEP" }) : null,
    el("span", { class: "hud-chip", text: cam.codec || "h264" }),
    el("span", { class: "hud-chip", text: cam.width && cam.height ? `${cam.width}×${cam.height}` : id }),
    fps ? el("span", { class: "hud-chip", text: fps }) : null,
    el("span", { class: "hud-chip hud-clock", text: istClock() }));
  const caption = el("div", { class: "stage-cap",
    text: `${cam.name || id} · ${cam.camera_id || id}` });
  const note = el("div", { class: "stage-note",
    text: "Timestamp is the camera's own burned-in clock." });
  stage.append(img, hud, caption, note);
  const overlay = el("canvas", { class: "live-overlay", id: "live-overlay" });
  stage.append(overlay);
  startLiveClock();
  startDetectionOverlay(id, overlay);
  mountCompare(stage, img);
  fillLiveSidecar(cam);
  fillLiveActions(cam);
  fillHerePlates(id);
}


function liveTile(cam, health) {
  const id = cam.camera_id;
  /* Stated from the registry, not guessed from a failure. UNKNOWN means this
   * camera has never been ingested. OBSERVED means the store already holds
   * its observations but health has not been persisted this ingest. */
  const st = health?.state || cam.state;
  const known = !st || st === "UNKNOWN"
    ? "never ingested"
    : st === "OBSERVED"
      ? "observed · health not yet persisted"
      : st === "STREAMING"
      ? `streaming · ${Number(health?.frames || cam.frames || 0).toLocaleString()} frames seen`
      : `${String(st).toLowerCase()}${health?.last_error ? " · " + health.last_error : ""}`;
  const frame = el("div", { class: "frame", "data-state": "idle" },
    el("div", { class: "placeholder" },
      el("div", { text: "still not requested" }),
      el("div", { class: "known", text: known })));
  frame.dataset.known = known;
  const priority = streamPriority(cam);
  const uxLabel = (cam.ux_state || cam.ux || priority || "PREVIEW").toString().toUpperCase();
  const codecLabel = (cam.codec || "h264").toString();
  const latencyLabel = (cam.latency_ms != null)
    ? `${Math.round(Number(cam.latency_ms))} ms`
    : (cam.rtt_ms != null ? `${Math.round(Number(cam.rtt_ms))} ms rtt` : null);
  const aiLabel = (cam.ai_state || cam.ai || "AI idle").toString();
  const tile = el("div", { class: "live-tile", "data-camera": id,
    "data-priority": priority.toLowerCase() }, frame,
    el("div", { class: "meta" },
      el("div", { class: "name", text: `${id} · ${cam.name || "unnamed"}` }),
      el("div", { class: "sub",
                  text: [
                    cam.located === false ? "not on the map" : (cam.district || cam.location || "district unknown"),
                    codecLabel,
                    latencyLabel]
                    .filter(Boolean).join(" · ") }),
      el("div", { class: "grades" },
        gradeChip(cam.anpr || cam.anpr_grade || "UNKNOWN", "ANPR"),
        gradeChip(cam.vehicle || cam.vehicle_reid_grade || "UNKNOWN",
                  "appearance"),
        el("div", { class: "stream-meta" },
          el("span", {
            class: `chip plain ${uxLabel === "LIVE" ? "ux-live" : "ux-preview"}`,
            text: uxLabel === "LIVE" ? "LIVE" : (uxLabel === "PRIMARY" ? "LIVE" : "PREVIEW"),
          }),
          el("span", { class: "chip plain", text: codecLabel }),
          latencyLabel
            ? el("span", { class: "chip plain", text: latencyLabel })
            : null,
          el("span", { class: "chip plain", text: aiLabel })),
        Number(cam.published_marks || 0)
          ? el("span", { class: "chip confirmed",
                         title: publishedMarksLabel(cam),
                         text: `${cam.published_marks} plate${Number(cam.published_marks) === 1 ? "" : "s"} in store` })
          : null)));

  const img = el("img", { alt: `Still from ${id}` });
  tile._img = img;
  tile.addEventListener("click", () => openLive(tile, id));
  return tile;
}

/* Fetched, not src-assigned.
 *
 * An `<img src>` cannot carry the bearer token, so every tile came back 401 and
 * the whole wall read "no frame". Putting the token in the query string would
 * have worked and is exactly what should not be done — it would land in server
 * logs, browser history and any screenshot of the demonstration. So the image
 * is fetched with the header like every other request and handed to the tile as
 * a blob. */
async function refreshTile(img, id, attempt = 1) {
  /* The tile is found by camera id, not from the image. The image is detached
   * until a frame arrives, so `img.closest()` returns null and every error
   * message was written to nothing — the wall sat on "connecting…" while the
   * console filled with 503s. */
  const host = img?.closest?.(".live-tile, #live-stage");
  const own = $$("#live .live-tile").find((t) => t._img === img);
  const tile = (host && host.classList.contains("live-tile"))
    ? host
    : (own || $(`#live .live-tile[data-camera="${CSS.escape(id)}"]`));
  const frame = tile?.querySelector(".frame");
  const inStage = !!(host && host.id === "live-stage");
    const pumping = tile?.classList.contains("selected");
    if (!inStage && frame && frame.dataset.state !== "live" && !pumping) setTileState(id, "capturing");
  try {
    const snapshot = await sharedSnapshot(id);
    const url = snapshot.url;
    const ageS = snapshot.age;
    const kind = snapshot.kind;
    const src = snapshot.source;
    img.dataset.url = url;
    img.src = url;
    const moving = kind === "live-view" || kind === "file-view"
      || /selected camera|own-feed recording|PTS-paced/i.test(src);
    const fresh = moving || (Number.isFinite(ageS) && ageS < 2.5);
    if (inStage) {
      const chip = host.querySelector(".hud-chip.live");
      if (chip) {
        chip.textContent = moving ? "Live" : "Still";
        chip.classList.toggle("live", moving);
      }
      return;
    }
    if (frame && img === (tile._img || img)) {
      frame.dataset.state = "live";
      clear(frame);
      frame.append(
        img,
        el("span", {
          class: "badge" + (fresh ? " live" : ""),
          text: fresh ? "LIVE" : "STILL",
        }),
        el("span", { class: "age",
                     text: Number.isFinite(ageS)
                       ? (fresh ? `${ageS.toFixed(1)}s` : `${Math.round(ageS)}s old`)
                       : new Date().toLocaleTimeString() }));
    }
  } catch (err) {
    /* A 503 here is the grid declining another consumer right now, not a dead
     * camera. Captures on this estate take one to ten seconds each, so under a
     * full wall that answer is common and temporary — retried with backoff
     * rather than written off. */
    /* 502 is the grid refusing us. Retrying that is pointless and pretending
     * it is temporary is worse than pointless. */
    /* "has not published a still" is ingest still catching up on this camera.
     * Retrying it four times opens nothing and fills the wall with "retrying".
     * The 20 s refresh will ask again once a JPEG exists. */
    const unpublished = (err.why || "").includes("has not published a still");
    const retryable = err.message === "503" && attempt < 4 && !unpublished;
    setTileState(id, unpublished ? "waiting" : (retryable ? "capturing" : "failed"),
      unpublished
        ? "waiting for ingest to publish a still"
        : retryable
          ? `grid busy — retrying (${attempt} of 3)`
          : err.why
            ? err.why
            : err.message === "403"
              ? "outside your jurisdiction"
              : `no frame (${err.message})`);
    if (retryable) {
      await new Promise((r) => setTimeout(r, 2500 * attempt));
      return refreshTile(img, id, attempt + 1);
    }
  }
}

function startLiveRefresh() {
  stopLiveRefresh();
  liveTimer = setInterval(() => {
    const box = $("#live-refresh");
    if (box && !box.checked) return;
    if (!$("#view-live").classList.contains("active")) return;
    if (!liveCaptureEnabled) return;
    /* File stills are cheap. Refresh the whole wall so a camera below the
     * fold is not stale when the operator scrolls to it. Do not pile up if
     * a previous tick is still in flight. */
    if (liveQueue.length > 4 || liveInflight > 8) return;
    for (const tile of $$("#live .live-tile")) {
      if (tile._img) queueStill(tile._img, tile.dataset.camera);
    }
  }, LIVE_REFRESH_MS);
}

function stopLiveRefresh() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
}

let livePump = null;

function stopStillPump() {
  if (livePump) { clearInterval(livePump); livePump = null; }
}

function startStillPump(id) {
  stopStillPump();
  const tick = () => {
    const tiles = $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`);
    if (!tiles.some((t) => t.classList.contains("selected"))) {
      stopStillPump(); return;
    }
    const imgs = [];
    for (const t of tiles) {
      const im = t.querySelector(".frame img") || t._img;
      if (im) imgs.push(im);
    }
    const stageImg = $("#live-stage img");
    if (stageImg) imgs.push(stageImg);
    for (const img of imgs) {
      if (img && liveInflight < LIVE_MAX_INFLIGHT + 4) {
        refreshTile(img, id).catch(() => {});
      }
    }
  };
  livePump = setInterval(tick, 250);
  tick();
}

function resetBrowserTelemetry() {
  state.telemetry.browser = {
    framesDecoded: null, framesDropped: null, packetsLost: null,
    packetsReceived: null, fps: null, jitterMs: null, jitterBufferMs: null,
    rttMs: null, codec: "", decoder: "", width: null, height: null,
    freezes: 0, lastFrameAt: 0, state: "NEGOTIATING",
  };
}

function startBrowserWatchdog(video, pc, id) {
  let previous = null;
  const sample = async () => {
    if (!livePlayer || livePlayer.id !== id) return;
    const b = state.telemetry.browser;
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      if (!b.lastFrameAt) b.lastFrameAt = performance.now();
      if (performance.now() - b.lastFrameAt > 3000) {
        b.freezes += 1;
        b.state = "DEGRADED";
        state.telemetry.reconnect = "degraded: no decoded frame";
      } else if (b.state !== "NEGOTIATING") {
        b.state = "LIVE";
      }
    } else if (b.lastFrameAt && performance.now() - b.lastFrameAt > 3000) {
      b.freezes += 1;
      b.state = "NO_FRAME";
    }
    if (!pc?.getStats) return;
    try {
      const reports = await pc.getStats();
      reports.forEach((r) => {
        if (r.type === "inbound-rtp" && r.kind === "video") {
          const delta = previous && r.framesDecoded != null
            ? r.framesDecoded - previous.framesDecoded : null;
          b.framesDecoded = r.framesDecoded ?? null;
          b.framesDropped = r.framesDropped ?? null;
          b.packetsLost = r.packetsLost ?? null;
          b.packetsReceived = r.packetsReceived ?? null;
          b.fps = r.framesPerSecond ?? (delta != null ? delta / 1.0 : null);
          b.jitterMs = r.jitter == null ? null : r.jitter * 1000;
          b.jitterBufferMs = r.jitterBufferDelay == null || !r.jitterBufferEmittedCount
            ? null : 1000 * r.jitterBufferDelay / r.jitterBufferEmittedCount;
          b.width = r.frameWidth ?? null;
          b.height = r.frameHeight ?? null;
          previous = r;
        } else if (r.type === "codec" && r.mimeType?.startsWith("video/")) {
          b.codec = r.mimeType;
          b.decoder = r.decoderImplementation || "";
        } else if (r.type === "candidate-pair" && r.state === "succeeded"
                   && r.currentRoundTripTime != null) {
          b.rttMs = r.currentRoundTripTime * 1000;
        }
      });
    } catch (err) {
      state.telemetry.playbackError = `stats unavailable: ${err.message || "error"}`;
    }
    updateTelemetry();
  };
  sample();
  return setInterval(sample, 1000);
}

/* WHEP: the browser offers, the media server answers, and the video arrives on
 * the peer connection. Falls back to the selected-camera still pump if anything
 * in that exchange fails, rather than leaving a black rectangle. */
async function openLive(tile, id) {
  closeLive();
  $$(`.live-tile[data-camera="${CSS.escape(id)}"]`).forEach((t) => t.classList.add("selected"));
  livePlayer = { pc: null, tile, id, statsTimer: null };
  fillLiveStage(id);

  let fileView = false;
  try {
    const vr = await fetch(`/cameras/${encodeURIComponent(id)}/view`, {
      method: "POST", headers: authHeaders(),
    });
    if (vr.ok) {
      const body = await vr.json().catch(() => ({}));
      fileView = body.source === "file";
    }
  } catch { /* stills still refresh */ }
  startStillPump(id);

  const live = state.liveConfig || {};
  if (!live.whep || fileView) return;

  resetBrowserTelemetry();
  state.telemetry.whep.started = performance.now();
  state.telemetry.whep.completed = 0;
  state.telemetry.whep.error = "";
  state.telemetry.reconnect = "negotiating";
  const video = el("video", { autoplay: true, muted: true, playsInline: true, class: "live-whep" });
  video.setAttribute("playsinline", "");
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
  livePlayer.pc = pc;
  pc.onconnectionstatechange = () => {
    state.telemetry.reconnect = pc.connectionState;
    updateTelemetry();
  };
  video.addEventListener("error", () => {
    state.telemetry.playbackError = video.error?.message || "media error";
    state.telemetry.reconnect = "playback error";
    updateTelemetry();
  });
  video.addEventListener("loadeddata", () => {
    state.telemetry.browser.lastFrameAt = performance.now();
    state.telemetry.browser.state = "LIVE";
    updateTelemetry();
  });
  video.addEventListener("timeupdate", () => {
    state.telemetry.browser.lastFrameAt = performance.now();
    if (state.telemetry.browser.state !== "NEGOTIATING") {
      state.telemetry.browser.state = "LIVE";
    }
  });
  video.addEventListener("stalled", () => {
    state.telemetry.browser.state = "DEGRADED";
    state.telemetry.reconnect = "stalled";
    updateTelemetry();
  });

  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });
  pc.ontrack = (e) => {
    if (!livePlayer || livePlayer.id !== id) return;
    // Attach the remote track directly. Relying only on e.streams[0] left the
    // video element without a live track in some MediaMTX/WHEP answers.
    const stream = video.srcObject instanceof MediaStream
      ? video.srcObject
      : new MediaStream();
    if (!stream.getTracks().includes(e.track)) stream.addTrack(e.track);
    video.srcObject = stream;
    video.play().catch(() => {
      state.telemetry.playbackError = "autoplay blocked";
      updateTelemetry();
    });
    const stage = $("#live-stage");
    if (!stage) return;
    stopStillPump();
    const img = stage.querySelector("img");
    if (img) img.style.display = "none";
    if (!stage.querySelector("video.live-whep")) {
      stage.insertBefore(video, stage.firstChild);
    }
    if (intelState.compare) {
      stage.querySelector(".live-compare")?.remove();
      mountCompare(stage, video);
    }
    const chip = stage.querySelector(".hud-chip.live");
    if (chip) {
      chip.textContent = "Live";
      chip.classList.add("live");
    }
    state.telemetry.whep.completed = performance.now();
    state.telemetry.reconnect = "connected";
    livePlayer.statsTimer = startBrowserWatchdog(video, pc, id);
    updateTelemetry();
  };

  const url = live.proxy
    ? `/cameras/${encodeURIComponent(id)}/whep`
    : `${live.base}/${encodeURIComponent(id)}/whep`;
  const headers = { "Content-Type": "application/sdp", "Accept": "application/sdp" };
  if (live.proxy) Object.assign(headers, authHeaders());

  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await new Promise((resolve) => {
      if (pc.iceGatheringState === "complete") { resolve(); return; }
      const done = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", done);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", done);
      setTimeout(resolve, 3500);
    });
    const sdp = pc.localDescription?.sdp || offer.sdp;
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: sdp,
    });
    if (!res.ok) throw new Error(`WHEP ${res.status}`);
    const answer = await res.text();
    await pc.setRemoteDescription({ type: "answer", sdp: answer });
  } catch (err) {
    state.telemetry.whep.error = err.message || "negotiation failed";
    state.telemetry.reconnect = "fallback to snapshot";
    updateTelemetry();
    try { pc.close(); } catch { /* already closed */ }
    if (livePlayer) livePlayer.pc = null;
  }
}

function closeLive() {
  stopStillPump();
  stopLiveClock();
  stopDetectionOverlay();
  if (!livePlayer) return;
  if (livePlayer.statsTimer) clearInterval(livePlayer.statsTimer);
  try { livePlayer.pc && livePlayer.pc.close(); } catch { /* already closed */ }
  state.telemetry.browser.state = "IDLE";
  const id = livePlayer.id || livePlayer.tile?.dataset.camera;
  $$(`.live-tile[data-camera="${CSS.escape(id || "")}"]`).forEach((t) => t.classList.remove("selected"));
  const frame = livePlayer.tile?.querySelector(".frame");
  if (frame && id) {
    clear(frame);
    const img = el("img", { alt: `Still from ${id}` });
    livePlayer.tile._img = img;
    frame.append(img, el("span", { class: "badge live", text: "LIVE" }));
    refreshTile(img, id);
  }
  livePlayer = null;
}

$("#live-reload")?.addEventListener("click", () => {
  liveQueue.length = 0;
  for (const tile of $$("#live .live-tile")) {
    delete tile.dataset.requested;
    if (tile._img) queueStill(tile._img, tile.dataset.camera);
  }
});

$$("[data-live-layout]").forEach((b) => b.addEventListener("click", () => {
  liveLayout = b.dataset.liveLayout || "focus";
  $$("[data-live-layout]").forEach((x) => x.classList.toggle("on", x === b));
  const box = $("#live");
  if (box) box.dataset.layout = liveLayout;
  const root = (liveLayout === "tab")
    ? $$("#live-tab img[data-camera]")
    : (liveLayout === "focus")
      ? $$("#live-strip .live-tile")
      : $$("#live-grid .live-tile");
  for (const node of root) {
    const id = node.dataset.camera;
    const img = node._img || node;
    if (id) queueStill(img, id, true);
  }
}));

$("#btn-telemetry")?.addEventListener("click", () => {
  const panel = $("#live-telemetry");
  const button = $("#btn-telemetry");
  if (!panel || !button) return;
  const open = panel.hidden;
  panel.hidden = !open;
  button.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    startTelemetry();
    updateTelemetry();
  }
});

$$("[data-live-wall]").forEach((b) => b.addEventListener("click", () => {
  liveWallMode = Number(b.dataset.liveWall) || 9;
  if ($("#live-count")) $("#live-count").textContent = `${liveCamsAll.length} cameras · wall ${liveWallMode}`;
  $$("[data-live-wall]").forEach((x) => {
    const active = x === b;
    x.classList.toggle("on", active);
    x.setAttribute("aria-pressed", active ? "true" : "false");
  });
  if ($("#view-live")?.classList.contains("active")) paintLiveWorkspace(liveCamsAll);
}));

$$("[data-live-priority]").forEach((b) => b.addEventListener("click", () => {
  livePriority = b.dataset.livePriority || "all";
  $$("[data-live-priority]").forEach((x) => {
    const active = x === b;
    x.classList.toggle("on", active);
    x.setAttribute("aria-pressed", active ? "true" : "false");
  });
  if ($("#view-live")?.classList.contains("active")) paintLiveWorkspace(liveCamsAll);
}));

$("#masthead-search")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = ($("#masthead-q").value || "").trim();
  if (!q) { show("investigate"); return; }
  const plate = q.replace(/\s+/g, "").toUpperCase();
  if ($("#q-plate")) $("#q-plate").value = plate;
  show("investigate");
  $("#search-form")?.requestSubmit();
});

/* ─── alerts ─────────────────────────────────────────────────────────────── */
let alertStatus = "OPEN";
$$("[data-alert-status]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-alert-status]").forEach((x) => x.classList.remove("on"));
  b.classList.add("on");
  alertStatus = b.dataset.alertStatus;
  loaders.alerts();
}));

loaders.alerts = async () => {
  const box = $("#alerts");
  try {
    const res = await api(`/alerts?status=${alertStatus}&limit=200`);
    clear(box);
    $("#n-alerts").textContent = res.stats ? String(res.stats.open ?? "") : "";
  labelCount("#n-alerts", "alerts open");
    if (!res.alerts.length) {
      box.append(el("div", { class: "empty" }, "No alerts in this state."));
      return;
    }
    const cards = el("div", { class: "alert-cards" },
      ...res.alerts.slice(0, 12).map((a) => el("div", { class: "alert-card" },
        plateRead(a.plate),
        el("div", { class: "body" },
          el("div", { class: "pl", text: a.plate || "—" }),
          el("div", { class: "meta", text:
            `WATCHLIST MATCH · ${String(a.category || "").replace(/_/g, " ")} · ${a.camera_id || "—"} · ${a.priority || ""}` }),
          el("div", { class: "tm", text:
            `${fmtAlertClock(a)} · confidence ${a.confidence != null ? (Number(a.confidence) * 100).toFixed(1) + "%" : "—"}` }),
          el("div", { class: "actions" },
            el("button", { class: "ghost", onclick: () => jumpAlert(a) }, "VIEW VIDEO"),
            el("button", { class: "ghost", onclick: () => trackEntity(a.plate, a) }, "TRACK"),
            el("button", { class: "ghost", onclick: () => routeAlert(a) }, "ROUTE"),
            el("button", { class: "ghost", onclick: () => { show("map"); toast("GIS: camera " + (a.camera_id || "")); } }, "OPEN GIS"),
            a.status === "OPEN" ? el("button", { class: "ghost", onclick: async (e) => {
              e.target.disabled = true;
              try {
                await api(`/alerts/${encodeURIComponent(a.alert_id)}/acknowledge`, { method: "POST" });
                toast("Acknowledged"); loaders.alerts();
              } catch (err) { toast(`${err.code}: ${err.message}`, true); }
            } }, "ACKNOWLEDGE") : el("span", { class: "chip", text: a.status })))))));
    box.append(cards, alertTable(res.alerts, true));
  } catch (err) {
    clear(box);
    box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
};

/* One audit table, so the overview's activity panel and the audit view cannot
 * drift apart in what they show or how they show it. */
function auditTable(entries) {
  const table = el("table", { class: "data" },
    el("thead", {}, el("tr", {},
      el("th", { text: "Time" }), el("th", { text: "Actor" }),
      el("th", { text: "Role" }), el("th", { text: "Action" }),
      el("th", { text: "Case" }), el("th", { text: "Purpose" }),
      el("th", { text: "Target" }), el("th", { text: "Results" }))));
  const tb = el("tbody");
  for (const e of entries) {
    tb.append(el("tr", {},
      el("td", { class: "mono", text: fmtTime(e.t) }),
      el("td", { class: "mono", text: e.actor }),
      el("td", { text: e.role || "—" }),
      el("td", { text: e.action }),
      el("td", { class: "mono", text: e.case_id || "—" }),
      el("td", { text: e.purpose || "—" }),
      el("td", { class: "mono", text: (e.target || "—").slice(0, 40) }),
      el("td", { class: "num", text: e.result_count ?? "—" })));
  }
  table.append(tb);
  return table;
}

/* The estate on the home screen, read-only. A third MapView rather than moving
 * one of the existing two: the investigation map holds a selection and a
 * trajectory, and borrowing it would make the home screen mutate the state an
 * investigator is working in. */
let map3 = null;
async function loadOverviewMap(body) {
  if (state.mapsReady) await state.mapsReady;
  clear(body);
  const holder = el("div", { class: "overview-map" });
  holder.append(el("div", { class: "gmap-host", "aria-hidden": "true" }));
  const canvas = el("canvas", { class: "map" });
  holder.append(canvas);
  body.append(holder);
  try {
    const { MapView } = await import("/ui/map.js?v=cr087");
    map3 = new MapView(canvas,
      { ...(state.mapOpts || {}), onSelect: () => {} });
    const ext = await api("/gis/extent");
    if (ext.extent) map3.fit(ext.extent, 0.12);
    const b = map3.bbox();
    const cams = await api(`/gis/cameras?south=${b.south}&west=${b.west}`
      + `&north=${b.north}&east=${b.east}&zoom=${Math.round(map3.zoom)}`);
    map3.set("cameras", cams.features || []);
    if (ext.cameras_without_location) {
      body.append(el("div", { class: "section-note", style: "padding:8px 14px" },
        `${ext.cameras_without_location} camera(s) have no coordinates and are `
        + "not on this map. They are listed under Cameras — capability is a "
        + "property of the camera, not of its position."));
    }
  } catch (err) {
    clear(body);
    body.append(el("div", { class: "notice", style: "margin:10px 14px" },
      `Map unavailable: ${err.code || ""} ${err.message || err}`.trim()));
  }
}

function alertTable(rows, actions = false) {
  const table = el("table", { class: "data" },
    el("thead", {}, el("tr", {},
      el("th", { text: "Time" }), el("th", { text: "Plate" }),
      el("th", { text: "Camera" }), el("th", { text: "Category" }),
      el("th", { text: "Priority" }), el("th", { text: "Confidence" }),
      el("th", { text: "Status" }), actions ? el("th", { text: "" }) : null)));
  const tb = el("tbody");
  for (const a of rows) {
    tb.append(el("tr", {},
      el("td", { class: "mono", text: fmtTime(a.t_norm) }),
      el("td", { class: "mono", text: a.plate || "—" }),
      el("td", { class: "mono", text: a.camera_id || "—" }),
      el("td", { text: a.category || "—" }),
      el("td", {}, el("span", {
        class: `chip ${a.priority === "HIGH" || a.priority === "CRITICAL"
          ? "conflict" : "verify"}`, text: a.priority || "—" })),
      el("td", { class: "num", text: num(a.confidence) }),
      el("td", { text: a.status }),
      actions ? el("td", {}, a.status === "OPEN" ? el("button", {
        class: "ghost",
        onclick: async (e) => {
          e.target.disabled = true;
          try {
            await api(`/alerts/${encodeURIComponent(a.alert_id)}/acknowledge`,
                      { method: "POST" });
            toast("Acknowledged");
            loaders.alerts();
          } catch (err) { toast(`${err.code}: ${err.message}`, true); }
        },
      }, "Acknowledge") : null) : null));
  }
  table.append(tb);
  return table;
}

/* ─── cameras / capability ───────────────────────────────────────────────── */
loaders.cameras = async () => {
  const box = $("#cameras");
  clear(box);
  box.append(loadingNote("Loading measured capability from the live store…"));
  try {
    const res = await api("/gis/capability");
    clear(box);
    $("#n-cameras").textContent = String(res.total);
  labelCount("#n-cameras", "cameras registered");
    const g = res.grade_summary;
    const published = res.features.filter((f) => Number(f.published_marks || 0) > 0).length;
    $("#cap-note").textContent =
      `ANPR: ${Object.entries(g.anpr).map(([k, v]) => `${v} ${k}`).join(" · ")}`
      + ` · ${published} camera${published === 1 ? "" : "s"} published a mark in the store`;

    if (res.note) {
      box.append(el("div", { class: "notice", style: "margin:12px" },
        el("strong", { text: "Some cameras cannot be placed on the map" }),
        res.note));
    }

    const table = el("table", { class: "data" },
      el("thead", {}, el("tr", {},
        el("th", { text: "Camera" }), el("th", { text: "Resolution" }),
        el("th", { text: "Codec" }), el("th", { text: "Location" }),
        el("th", { text: "ANPR" }), el("th", { text: "Appearance" }),
        el("th", { text: "Presence" }), el("th", { text: "Samples" }),
        el("th", { text: "Plate yield" }),
        el("th", { text: "Marks in store" }),
        el("th", { text: "Bands" }))));
    const tb = el("tbody");
    for (const f of res.features) {
      tb.append(el("tr", {},
        el("td", { class: "mono", text: f.camera_id }),
        el("td", { class: "mono", text: f.resolution || "—" }),
        el("td", { text: f.codec || "—" }),
        el("td", {}, f.located
          ? el("span", { class: "mono", text: `${num(f.lat, 4)}, ${num(f.lon, 4)}` })
          : el("span", { class: "chip unknown", text: "no coordinates" })),
        el("td", {}, gradeChip(f.anpr, "")),
        el("td", {}, gradeChip(f.vehicle, "")),
        el("td", {}, gradeChip(f.presence, "")),
        el("td", { class: "num", text: String(f.samples) }),
        el("td", { class: "num", title: "reads / vehicle observations in the capability sample",
                   text: plateYield(f) }),
        el("td", { class: "num",
                   title: "live-store identity, not the capability sample",
                   text: publishedMarksLabel(f) }),
        el("td", { class: "mono", style: "font-size:10px",
                   text: (f.bands || []).map((b) => `${b.time_band}:${b.anpr}`).join(" ") || "—" })));
    }
    table.append(tb);
    box.append(table);
  } catch (err) {
    clear(box);
    box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
};

$("#btn-regrade").addEventListener("click", async (e) => {
  e.target.disabled = true;
  e.target.textContent = "Grading…";
  try {
    const res = await api("/capability/grade", { method: "POST" });
    toast(`Graded ${res.graded} camera/band combinations from stored observations`);
    loaders.cameras();
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
  } finally {
    e.target.disabled = false;
    e.target.textContent = "Re-grade from stored observations";
  }
});

/* ─── cases ──────────────────────────────────────────────────────────────── */
loaders.cases = async () => {
  try {
    const res = await api("/cases");
    const box = $("#case-list");
    clear(box);
    $("#n-cases").textContent = String(res.count);
  labelCount("#n-cases", "cases");
    for (const c of res.cases) {
      box.append(el("div", {
        class: "result", onclick: () => openCase(c.case_id),
      },
        el("div", { class: "top" },
          el("span", { class: "plate", text: c.case_id }),
          el("span", { class: `chip ${c.status === "OPEN" ? "confirmed" : "plain"}`,
                       text: c.status }),
          el("span", { class: "time", text: fmtTime(c.updated_at).slice(0, 10) })),
        el("div", { class: "meta" },
          el("span", { text: c.title }),
          c.district && el("span", { text: c.district }))));
    }
    if (!res.cases.length) {
      box.append(el("div", { class: "empty" }, "No cases yet. Open one to bind "
        + "your searches to a stated purpose."));
    }
  } catch (err) { /* unauthenticated */ void err; }
};

$("#case-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const c = await api("/cases", { method: "POST", body: JSON.stringify({
      case_id: $("#c-id").value.trim(),
      title: $("#c-title").value.trim(),
      purpose: $("#c-purpose").value.trim(),
      fir_number: $("#c-fir").value.trim() || null,
      district: $("#c-district").value.trim() || null,
    }) });
    toast(`Opened ${c.case_id}`);
    $("#case-id").value = c.case_id;
    $("#purpose").value = c.purpose;
    syncPurpose();
    loaders.cases();
    openCase(c.case_id);
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
  }
});

async function openCase(caseId) {
  state.openCase = caseId;
  $("#case-open").textContent = caseId;
  const box = $("#case-detail");
  try {
    const res = await api(`/cases/${encodeURIComponent(caseId)}`);
    clear(box);
    box.append(el("dl", { class: "kv" },
      dt("Case"), dd(res.case.case_id),
      dt("Title"), dd(res.case.title),
      dt("Purpose"), el("dd", { class: "prose", text: res.case.purpose }),
      dt("FIR"), dd(res.case.fir_number || "—"),
      dt("District"), dd(res.case.district || "—"),
      dt("Opened by"), dd(res.case.opened_by),
      dt("Status"), dd(res.case.status)));

    box.append(el("h3", { style: "margin:16px 0 6px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)" },
      `Attached (${res.items.length})`));
    if (res.items.length) {
      const table = el("table", { class: "data" },
        el("thead", {}, el("tr", {},
          el("th", { text: "Type" }), el("th", { text: "Reference" }),
          el("th", { text: "Added by" }), el("th", { text: "When" }))));
      const tb = el("tbody");
      for (const it of res.items) {
        tb.append(el("tr", {},
          el("td", {}, el("span", { class: "chip plain", text: it.item_type })),
          el("td", { class: "mono", text: it.item_ref }),
          el("td", { text: it.added_by }),
          el("td", { class: "mono", text: fmtTime(it.created_at) })));
      }
      table.append(tb);
      box.append(table);
    } else {
      box.append(el("div", { class: "empty" }, "Nothing attached yet."));
    }

    box.append(el("h3", { style: "margin:16px 0 6px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)" },
      "Notes"));
    for (const n of res.notes) {
      box.append(el("div", { class: "notice neutral" },
        el("strong", { text: `${n.author} · ${fmtTime(n.created_at)}` }), n.body));
    }
    const noteBox = el("textarea", { rows: 2, placeholder: "add a note",
                                     style: "width:100%;margin-top:6px" });
    box.append(noteBox, el("button", {
      class: "ghost", style: "margin-top:6px",
      onclick: async () => {
        if (!noteBox.value.trim()) return;
        try {
          await api(`/cases/${encodeURIComponent(caseId)}/notes`, {
            method: "POST", body: JSON.stringify({ body: noteBox.value.trim() }) });
          noteBox.value = "";
          openCase(caseId);
        } catch (err) { toast(`${err.code}: ${err.message}`, true); }
      },
    }, "Add note"));
  } catch (err) {
    clear(box);
    box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
}

async function attach(itemType, itemRef, payload) {
  if (!state.caseId) return toast("Set a case identifier first", true);
  try {
    await api(`/cases/${encodeURIComponent(state.caseId)}/items`, {
      method: "POST",
      body: JSON.stringify({ item_type: itemType, item_ref: itemRef, payload }),
    });
    toast(`Attached ${itemType} ${itemRef} to ${state.caseId}`);
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
  }
}

$("#btn-export-case").addEventListener("click", async () => {
  if (!state.openCase) return toast("Select a case first", true);
  try {
    const pkg = await api(`/cases/${encodeURIComponent(state.openCase)}/export`);
    const blob = new Blob([JSON.stringify(pkg, null, 2)],
                          { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: `${state.openCase}-case-file.json` });
    document.body.append(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    toast(`Exported · audit chain ${pkg.audit_chain_verified ? "verified" : "BROKEN"}`,
          !pkg.audit_chain_verified);
  } catch (err) {
    toast(`${err.code}: ${err.message}`, true);
  }
});

/* ─── audit ──────────────────────────────────────────────────────────────── */
loaders.audit = async () => {
  const box = $("#audit");
  try {
    const res = await api("/audit?limit=400");
    clear(box);
    $("#audit-chain").textContent = res.chain_verified
      ? `chain verified · ${res.count} entries`
      : `CHAIN BROKEN: ${res.chain_error}`;
    box.append(auditTable(res.entries));
  } catch (err) {
    clear(box);
    box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
};

/* ─── evidence chain ─────────────────────────────────────────────────────── */
loaders.evidence = async () => {
  const box = $("#evidence-chain");
  clear(box);
  const pending = el("div", { class: "loading-note" },
    "Recomputing manifests. Overview already reports the evidence subsystem; "
    + "this page re-hashes files and can wait on a busy store.");
  box.append(pending);
  api("/system/health").then((h) => {
    const ev = (h.components || []).find((c) => c.component === "evidence");
    if (!ev || !box.contains(pending)) return;
    pending.replaceWith(el("div", {
      class: `notice ${ev.state === "HEALTHY" ? "ok" : ev.state === "FAILED" ? "bad" : ""}` },
      el("strong", { text: `Evidence subsystem ${ev.state}` }),
      ev.detail,
      " The table below appears when the full chain recompute returns."));
  }).catch(() => {});
  try {
    const v = normaliseVerification(await api("/evidence/chain/verify"));
    clear(box);
    /* Cautions must appear here too. This is the screen an officer opens before
     * relying on a record; a defect reported only in the single-record panel is
     * a defect nobody will read. */
    const cautioned = (v.cautions || []).length > 0;
    box.append(el("div", {
      class: `notice ${v.ok ? (cautioned ? "warn" : "ok") : "bad"}` },
      el("strong", { text: !v.ok
        ? "EVIDENCE CHAIN BROKEN"
        : cautioned
          ? `Chain verified — ${v.cautions.length} record(s) need reading before use`
          : "Evidence chain verified" }),
      !v.ok
        ? "At least one record does not match its recorded hash. Details below."
        : "Every manifest hashes to the value recorded in the entry that follows "
          + "it. A removed or altered record would break this."
          + (cautioned
             ? " Nothing here has been altered — what follows is a defect in "
               + "what a record says about itself."
             : "")));
    for (const c of (v.cautions || [])) {
      box.append(el("div", { class: "notice warn" },
        el("strong", { class: "mono", text: c.name }), c.detail));
    }
    const table = el("table", { class: "data" },
      el("thead", {}, el("tr", {},
        el("th", { text: "" }), el("th", { text: "Check" }), el("th", { text: "Detail" }))));
    const tb = el("tbody");
    for (const c of (v.checks || []).filter((x) => !x.caution)) {
      tb.append(el("tr", {},
        el("td", { text: c.ok ? "✓" : "✗" }),
        el("td", { class: "mono", text: c.name }),
        el("td", { text: c.detail || "" })));
    }
    table.append(tb);
    box.append(table);
  } catch (err) {
    clear(box);
    box.append(el("div", { class: "notice bad" }, `${err.code}: ${err.message}`));
  }
};

/* ─── copilot ────────────────────────────────────────────────────────────── */
const COPILOT_PROMPTS = [
  ["Infrared cameras", "Show me the infrared cameras and pin their stills."],
  ["Cannot read plates", "Which cameras are graded UNSUITABLE for ANPR?"],
  ["Unlocated", "Which cameras are in the registry but have no coordinates?"],
  ["Timebase cam01+cam21", "May cam01 and cam21 share a timeline?"],
  ["Timebase cam01+cam04", "May cam01 and cam04 share a timeline?"],
  ["Find GJ32AG0028", "Find GJ32AG0028 and say which cameras it appears on."],
  ["Enhance a still", "Enhance this still and sharpen the plate so I can read it."],
];

loaders.copilot = async () => {
  try {
    const d = await api("/copilot/describe");
    $("#copilot-state").textContent = d.available
      ? `${d.tools.length} read-only tools · ${d.backend}${d.model ? " · " + d.model : ""}`
      : "local rules — the workspace is unaffected";
    const banner = $("#copilot-banner");
    if (banner && d.vision) {
      banner.textContent = d.vision.enabled
        ? "Gemini is coordinating specialists. A still you describe leaves this host — it is not evidence and not a plate read."
        : "One coordinator over four deterministic specialists. Stills stay on this host unless vision is switched on for a supervised demo.";
    }
    const row = $("#specialist-row");
    if (row) {
      clear(row);
      for (const s of d.specialists || []) {
        row.append(el("span", { class: "specialist-chip",
                                "data-specialist": s.id,
                                title: s.role,
                                text: s.role || s.id }));
      }
    }
    const chips = $("#prompt-chips");
    if (chips && !chips.dataset.ready) {
      chips.dataset.ready = "1";
      for (const [label, q] of COPILOT_PROMPTS) {
        const b = el("button", { type: "button", text: label });
        b.addEventListener("click", () => askCopilot(q));
        chips.append(b);
      }
    }
  } catch { /* unauthenticated */ }
};

function markSpecialists(ids) {
  $$("#specialist-row .specialist-chip").forEach((c) => {
    c.classList.toggle("on", (ids || []).includes(c.dataset.specialist));
  });
}

function askCopilot(q) {
  const input = $("#chat-input");
  input.value = q;
  $("#chat-form").requestSubmit();
}

function copilotCameraWall(ids, host) {
  if (!ids || !ids.length) return;
  const wall = el("div", { class: "cam-wall" });
  for (const id of ids) {
    const img = el("img", { alt: id });
    const describe = el("button", {
      class: "describe", type: "button", text: "Describe still",
    });
    describe.addEventListener("click", (ev) => {
      ev.stopPropagation();
      describeStill(id, host);
    });
    const tile = el("button", { class: "cam-tile", type: "button" },
      img,
      el("div", { class: "meta" },
        el("div", { class: "id", text: id }),
        el("div", { class: "dim", text: "ingest still · not evidence" })),
      describe);
    tile.addEventListener("click", () => {
      show("live");
    });
    fillRegistryStill(img, id);
    wall.append(tile);
  }
  host.append(wall);
}

async function describeStill(id, host) {
  const note = el("div", { class: "scene-note",
    text: `Sending a downscaled still of ${id} off this host…` });
  host.append(note);
  try {
    const a = await api("/copilot/scene", {
      method: "POST", body: JSON.stringify({ camera_id: id }) });
    note.classList.add("warn");
    note.textContent = `${id} · ${a.model || "gemini"} · FRAME LEFT THE DEPLOYMENT · not evidence. ${a.description || ""}`;
  } catch (err) {
    note.classList.add("warn");
    note.textContent = `${err.code || "ERROR"}: ${err.message}`;
  }
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const q = input.value.trim();
  if (!q) return;
  const log = $("#chat-log");
  log.append(el("div", { class: "msg user", text: q }));
  input.value = "";
  log.scrollTop = log.scrollHeight;
  const pending = el("div", { class: "msg bot dim", text: "Specialists working…" });
  log.append(pending);
  try {
    const a = await api("/copilot/ask", {
      method: "POST", body: JSON.stringify({ question: q }) });
    pending.remove();
    markSpecialists(["coordinator", ...(a.specialists || [])]);
    const msg = el("div", { class: `msg bot${a.grounded ? "" : " withheld"}` },
      el("div", { text: a.answer }));
    if (a.specialists && a.specialists.length) {
      msg.append(el("div", { class: "tools",
        text: `Specialists: ${a.specialists.join(" · ")}` }));
    }
    copilotCameraWall(a.cameras || [], msg);
    if (a.tool_calls && a.tool_calls.length) {
      msg.append(el("div", { class: "tools" },
        "Queries run: ",
        ...a.tool_calls.map((t) => el("code", {
          text: `${t.tool}${t.refused ? " (refused)" : ""} ` })),
        a.grounding && a.grounding.tokens_checked
          ? ` · ${a.grounding.tokens_checked} facts checked against results` : ""));
    }
    for (const w of a.warnings || []) {
      msg.append(el("div", { class: "notice", text: w }));
    }
    for (const s of a.suspicious_content || []) {
      msg.append(el("div", { class: "notice bad" },
        el("strong", { text: "Suspicious content in camera imagery" }),
        `${s.field}: ${s.value} — treated as data and not acted on.`));
    }
    log.append(msg);
  } catch (err) {
    pending.remove();
    log.append(el("div", { class: "msg bot withheld", text: `${err.code}: ${err.message}` }));
  }
  log.scrollTop = log.scrollHeight;
});

function paintCommandStatus(cmd, o) {
  const health = $("#cc-health");
  const alerts = $("#cc-alerts");
  const ai = $("#cc-ai");
  if (health) {
    health.textContent = `Healthy ${cmd?.healthy ?? "—"} · down ${cmd?.down ?? "—"}`;
  }
  if (alerts) alerts.textContent = `Alerts ${o?.alerts?.open ?? cmd?.active_alerts ?? "—"}`;
  if (ai) ai.textContent = `AI store ${cmd?.observations ?? "—"} obs`;
}

function applyIntelMode(mode) {
  intelState.mode = mode;
  intelState.analytics = mode !== "video" && mode !== "off";
  if (mode === "video") intelState.analytics = false;
  if (mode === "vehicles") { intelState.vehicles = true; intelState.people = false; intelState.anpr = false; }
  if (mode === "people") { intelState.vehicles = false; intelState.people = true; intelState.anpr = false; }
  if (mode === "anpr") { intelState.vehicles = true; intelState.people = false; intelState.anpr = true; }
  if (mode === "full" || mode === "incident" || mode === "both") {
    intelState.vehicles = true; intelState.people = true; intelState.anpr = true;
  }
  snapshotCache.clear();
  if (overlayState) overlayState.poll && overlayState.poll._noop;
  const cam = livePlayer?.id;
  const canvas = $("#live-overlay");
  if (cam && canvas) startDetectionOverlay(cam, canvas);
  if ($("#view-live")?.classList.contains("active")) paintLiveWorkspace(liveCamsAll);
}

$$("[data-intel]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-intel]").forEach((x) => { x.classList.remove("on"); x.setAttribute("aria-pressed", "false"); });
  b.classList.add("on"); b.setAttribute("aria-pressed", "true");
  intelState.analytics = b.dataset.intel !== "off";
  applyIntelMode(intelState.analytics ? (intelState.mode === "video" ? "full" : intelState.mode) : "video");
}));

$$("[data-viewmode]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-viewmode]").forEach((x) => { x.classList.remove("on"); x.setAttribute("aria-pressed", "false"); });
  b.classList.add("on"); b.setAttribute("aria-pressed", "true");
  applyIntelMode(b.dataset.viewmode);
}));

$$("[data-class]").forEach((b) => b.addEventListener("click", () => {
  const key = b.dataset.class;
  intelState[key] = !intelState[key];
  b.classList.toggle("on", intelState[key]);
  b.setAttribute("aria-pressed", String(intelState[key]));
  applyIntelMode(intelState.mode);
}));

$("#btn-compare")?.addEventListener("click", () => {
  intelState.compare = !intelState.compare;
  $("#btn-compare").classList.toggle("on", intelState.compare);
  $("#btn-compare").setAttribute("aria-pressed", String(intelState.compare));
  const cam = livePlayer?.id;
  if (cam) fillLiveStage(cam);
});

$$("[data-preset]").forEach((b) => b.addEventListener("click", () => {
  const id = b.dataset.preset;
  const spec = {
    "control-room": { wall: 12, mode: "video", view: "live" },
    "overview-30": { wall: 30, mode: "video", view: "live" },
    "traffic": { wall: 12, mode: "anpr", view: "live" },
    "person-search": { wall: 9, mode: "people", view: "live" },
    "watchlist-incident": { wall: 4, mode: "full", view: "alerts" },
    "designated-vehicle": { wall: 4, mode: "anpr", view: "investigate" },
  }[id];
  if (!spec) return;
  liveWallMode = spec.wall;
  $$("[data-live-wall]").forEach((x) => {
    const on = Number(x.dataset.liveWall) === spec.wall;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  applyIntelMode(spec.mode);
  show(spec.view);
  if (spec.view === "live") loaders.live?.();
}));

async function trackEntity(plate, alert) {
  if (!plate) { toast("No plate on this alert", true); return; }
  show("investigate");
  if ($("#q-plate")) $("#q-plate").value = plate;
  try {
    const card = await api(`/command/track/${encodeURIComponent(plate)}`);
    paintTrackPanel(card, alert);
    await loadTrajectory(plate);
    await followVehicle(plate);
  } catch (err) {
    toast(`${err.code || ""} ${err.message}`, true);
  }
}

function paintTrackPanel(card, alert) {
  const panel = $("#track-panel");
  const body = $("#track-body");
  if (!panel || !body) return;
  panel.hidden = false;
  clear(body);
  body.append(el("div", { class: "sid", text:
    `${card.subject || card.target} · ${card.identifier || ""}` }));
  for (const hop of card.hops || []) {
    body.append(el("div", { class: "track-hop" },
      el("div", { class: "role", text: hop.role }),
      el("div", {},
        el("div", { class: "mono", text: hop.camera_id || "—" }),
        el("div", { class: "muted", text: `${hop.signal || ""} · ${hop.t || ""}` })),
      hop.observation_id ? el("button", { class: "ghost", onclick: () => jumpObservation(hop.observation_id, hop.camera_id) },
        "JUMP TO EVENT") : null));
  }
  for (const t of card.transitions || []) {
    body.append(el("div", { class: "notice " + (t.result === "CONTRADICTION" ? "bad" : "neutral") },
      `${t.from_camera} → ${t.to_camera} · ${t.distance_km ?? "?"} km · `
      + `${t.elapsed_s ?? "?"}s elapsed · min ${t.expected_minimum_s ?? "—"}s · ${t.result}`));
  }
  if (alert?.camera_id) {
    body.append(el("div", { class: "live-actions", style: "display:flex" },
      el("button", { class: "primary", onclick: () => jumpAlert(alert) }, "VIEW VIDEO")));
  }
}

async function jumpObservation(oid, cameraId) {
  try {
    const j = await api(`/command/jump/${encodeURIComponent(oid)}`);
    toast(`Event ${j.event_time || ""} · ${j.camera_id} · ${j.signal || ""}`);
    show("live");
    openLive($(`.live-tile[data-camera="${CSS.escape(j.camera_id)}"]`) || el("div"), j.camera_id);
  } catch (err) {
    if (cameraId) {
      show("live");
      openLive($(`.live-tile[data-camera="${CSS.escape(cameraId)}"]`) || el("div"), cameraId);
    } else toast(`${err.code}: ${err.message}`, true);
  }
}

function jumpAlert(a) {
  if (a.observation_id) return jumpObservation(a.observation_id, a.camera_id);
  if (!a.camera_id) { toast("No camera on this alert", true); return; }
  show("live");
  openLive($(`.live-tile[data-camera="${CSS.escape(a.camera_id)}"]`) || el("div"), a.camera_id);
}

async function routeAlert(a) {
  if (!a.plate) { toast("No plate to route", true); return; }
  show("map");
  await trackEntity(a.plate, a);
}

function startCommandClock() {
  const tick = () => {
    const n = $("#cc-clock");
    if (n) n.textContent = istClock();
  };
  setInterval(tick, 1000);
  tick();
}

/* Compare uses the same live element: left is native video, right is a canvas
 * copy plus metadata boxes. A second WHEP session is not opened. */
function mountCompare(stage, videoOrImg) {
  if (!intelState.compare) return;
  const wrap = el("div", { class: "live-compare" });
  const left = el("div", { class: "pane" },
    el("div", { class: "pane-label", text: "ORIGINAL" }));
  const right = el("div", { class: "pane" },
    el("div", { class: "pane-label", text: "AI ANNOTATED (store metadata)" }));
  const canvas = el("canvas");
  right.append(canvas);
  wrap.append(left, right);
  stage.append(wrap);
  const src = videoOrImg;
  const paint = () => {
    if (!intelState.compare) return;
    const w = src.clientWidth || 320, h = src.clientHeight || 180;
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    try { ctx.drawImage(src, 0, 0, w, h); } catch { /* not ready */ }
    requestAnimationFrame(paint);
  };
  requestAnimationFrame(paint);
}

/* ─── start ──────────────────────────────────────────────────────────────── */
(async function start() {
  await identify();
  /* Maps and the first view share the store. Waiting for GIS extent before
   * painting Overview left the shift picture blank for tens of seconds.
   * The overview map still waits on this promise so it gets the same
   * street tiles as Estate map — otherwise it paints a graticule while
   * /config is in flight. */
  const mapsP = initMaps();
  state.mapsReady = mapsP;
  startCommandClock();
  loaders.cases();
  loaders.alerts();
  /* A shift starts on the command picture, not in a search box. A deep link
   * still wins — someone sent that link for a reason. */
  const initial = (location.hash || "#overview").slice(1);
  show($(`#view-${initial}`) ? initial : "overview");
  await mapsP;
})();

/* Debug handle, localhost only.
 *
 * Read-only references to state the page already holds, exposed so a developer
 * can inspect layers from the console. Gated on the hostname so it does not
 * exist in a deployment. */
if (["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)) {
  Object.defineProperty(window, "__saakshya", {
    value: { get map1() { return map1; }, get map2() { return map2; }, state },
  });
}
