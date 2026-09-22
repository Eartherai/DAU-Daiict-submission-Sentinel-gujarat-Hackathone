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
import HlsEngine from "/ui/vendor/hls-1.5.17.mjs?v=1.5.17";
import { MapView } from "/ui/map.js?v=cr100";
import { officerIdMismatch } from "/ui/auth-gate.js?v=cr100";

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
  simulationConfig: { enabled: false, available: false, proxy: false,
                      catalog_count: 30, ready_count: 0, label: "" },
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
  if (!state.token) {
    state.token = sessionStorage.getItem("saakshya.token") || "";
  }
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
  const product = view === "intelligence" ? "intelligence"
    : view === "system" || view === "audit" || view === "cameras" ? "system"
    : view === "investigate" || view === "map" || view === "cases"
      || view === "evidence" || view === "copilot" || view === "alerts" ? "investigation"
    : "operations";
  productState.mode = product;
  $$("[data-product]").forEach((b) => {
    const on = b.dataset.product === product;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
  });
  if (loaders[view]) loaders[view]();
  if (view !== "live") {
    stopLiveRefresh(); stopWallHeartbeat();
    closeLive(); closeTileWhepAll(); closeTileHlsAll();
    liveObserver?.disconnect(); liveObserver = null;
    abortSnapshots();
  } else {
    /* Leaving Live tears every session down, so entering it has to build them
     * back. That was left to the post-paint callback inside the wall painter,
     * which does not run on every path into this view: navigating back to Live
     * showed a full grid of tiles with no video at all, and stayed that way
     * until the operator happened to click a layout or wall-size button, which
     * re-ran the sync as a side effect. Establish the media plane explicitly on
     * entry instead of depending on which code path painted the wall.
     *
     * Two frames, because the tiles must be laid out before they can be
     * measured: the scheduler skips any tile smaller than 8px, and on the frame
     * the grid is created every tile is still 0x0. */
    /* The loader that paints the wall is async, so two frames is not enough:
     * on entry the grid is usually still empty, every tile measures 0x0, the
     * scheduler correctly skips them all, and nothing ever retries - which is
     * the bug this block exists to fix. Re-run a few times over the first few
     * seconds instead of guessing one moment. syncTileWhep is idempotent: it
     * reattaches sessions it already holds and only negotiates what is
     * missing, so repeating it costs nothing. */
    applyCommandChrome();
    applyMediaPolicy();
    startWallHeartbeat();
    for (const delay of [0, 300, 900, 2000, 4000]) {
      setTimeout(() => {
        if (!$("#view-live")?.classList.contains("active")) return;
        bindWhepScroll();
        applyCommandChrome();
        applyMediaPolicy();
        fitWall();
        syncTileWhep();
      }, delay);
    }
  }
  if (view !== "intelligence") {
    for (const host of [$("#intel-stage-a"), $("#intel-stage-b")]) {
      if (host?._intelTimer) { clearInterval(host._intelTimer); host._intelTimer = null; }
    }
  }
  if (view === "map" && map2) {
    const refit = () => {
      map2.resize();
      refreshMapLayers(map2, map2.bbox());
    };
    refit();
    setTimeout(refit, 250);
    setTimeout(refit, 800);
  }
  if (view === "investigate" && map1) { map1.resize(); }
  if (view === "intelligence" && intelMap) intelMap.resize();
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
  const officerId = $("#gate-officer")?.value.trim();
  const tok = $("#gate-token").value.trim();
  if (!officerId || !tok) {
    toast("Enter your Officer ID and the access token issued to you.", true);
    return;
  }
  state.token = tok;
  sessionStorage.setItem("saakshya.token", tok);
  const c = $("#gate-case")?.value.trim();
  const p = $("#gate-purpose")?.value.trim();
  if (c) { state.caseId = c; $("#case-id").value = c; }
  if (p) { state.purpose = p; $("#purpose").value = p; }
  await identify();
  if (!state.principal) {
    toast("Token was refused. Check it and try again.", true);
    return;
  }
  /* The token authenticated *someone*; this confirms it authenticated the
   * officer who typed it. A mismatch is treated as a failed sign-in, not a
   * warning — the token is dropped rather than left active under the wrong
   * name. */
  if (officerIdMismatch(officerId, state.principal)) {
    state.principal = null;
    state.token = "";
    sessionStorage.removeItem("saakshya.token");
    $("#who").textContent = "not signed in";
    const gate = $("#gate");
    if (gate) gate.hidden = false;
    toast("That token is not issued to this Officer ID. Sign in with your "
      + "own Officer ID and the token issued to you.", true);
    return;
  }
  syncPurpose();
  show((location.hash || "#overview").slice(1) || "overview");
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
  if (cfg.map?.google?.enabled) {
    mapOpts.googleLoader = cfg.map.google.loader || "/maps/google-api";
  }
  if (cfg.map?.tiles && cfg.map.template) {
    mapOpts.tileTemplate = cfg.map.template;
    mapOpts.attribution = cfg.map.attribution;
  }
  state.mapConfig = cfg.map;
  state.mapOpts = { ...(state.mapOpts || {}), ...mapOpts };
  state.liveConfig = cfg.live || { whep: false };
  state.simulationConfig = cfg.simulation || { enabled: false, available: false, proxy: false,
                                               catalog_count: 30, ready_count: 0, label: "" };
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
  if (!state.token) {
    state.token = sessionStorage.getItem("saakshya.token") || "";
  }
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
      const visibleCandidates = (res.candidates || []).slice(0, 5);
      for (const c of visibleCandidates) {
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
      if ((res.candidates || []).length > visibleCandidates.length) {
        body.append(el("div", { class: "section-note", text:
          `Showing the five highest-ranked leads; ${(res.candidates || []).length - visibleCandidates.length} more remain available in the case API.` }));
      }

      // A burst of observations can produce many copies of the same
      // impossible camera-to-camera transition.  Preserve the count while
      // showing one representative (the highest implied speed) per pair, so
      // the operator sees a decision rather than a scrolling wall of noise.
      const contradictions = new Map();
      for (const x of res.contradictions || []) {
        const key = `${x.from_camera}→${x.to_camera}`;
        const current = contradictions.get(key);
        if (!current) contradictions.set(key, { ...x, count: 1 });
        else {
          current.count += 1;
          if ((x.implied_speed_kmh || 0) > (current.implied_speed_kmh || 0)) {
            Object.assign(current, x);
          }
        }
      }
      const visibleContradictions = [...contradictions.values()].slice(0, 3);
      for (const x of visibleContradictions) {
        body.append(el("div", { class: "notice bad" },
          el("strong", { text: "ROUTE_CONTRADICTION" }),
          `${x.from_camera} → ${x.to_camera}: ${x.reason}. `
          + `Distance ${Math.round(x.distance_m)} m, elapsed ${Math.round(x.elapsed_s)} s, `
          + `implied ${Math.round(x.implied_speed_kmh)} km/h.`
          + (x.count > 1 ? ` ${x.count} observations collapsed into this transition.` : "")));
      }
      if (contradictions.size > visibleContradictions.length) {
        body.append(el("div", { class: "section-note", text:
          `Showing ${visibleContradictions.length} of ${contradictions.size} distinct impossible transitions; the full set remains in the case API.` }));
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
let map1 = null, map2 = null, intelMap = null;
let lastTrackCard = null;

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
      el("div", { class: "name", text: c.name || c.camera_id }),
      el("div", { class: "sub",
                  text: unlocatedCam
                    ? `${c.camera_id} · not on the map`
                    : `${c.camera_id} · ${c.district || "district unknown"}` }));
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

/* The registry rail asks for a still per camera, in a loop. Unbounded and
 * uncancellable, thirty of those captures - one to ten seconds each - held
 * every connection the browser allows for minutes, and the request the Live
 * wall makes on entry queued behind them and never returned. The rail is a
 * row of thumbnails; it does not deserve the whole connection budget. Bound
 * it, and let leaving the view take the connections back. */
const REGISTRY_STILL_MAX = 3;
const registryStillQueue = [];
let registryStillInflight = 0;

function pumpRegistryStills() {
  while (registryStillInflight < REGISTRY_STILL_MAX && registryStillQueue.length) {
    const job = registryStillQueue.shift();
    registryStillInflight += 1;
    job().finally(() => { registryStillInflight -= 1; pumpRegistryStills(); });
  }
}

function fillRegistryStill(img, id) {
  registryStillQueue.push(async () => {
    const ctl = new AbortController();
    snapshotAborts.add(ctl);
    try {
      const res = await fetch(`/cameras/${encodeURIComponent(id)}/snapshot`,
                              { headers: authHeaders(), signal: ctl.signal });
      if (!res.ok) return;
      const blob = await res.blob();
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      const url = URL.createObjectURL(blob);
      img.dataset.url = url;
      img.src = url;
    } catch { /* aborted, or the chip still names the camera */ }
    finally { snapshotAborts.delete(ctl); }
  });
  pumpRegistryStills();
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
$("#btn-focus-target")?.addEventListener("click", () => {
  if (lastTrackCard && map1) map1.focusTarget(lastTrackCard.hops || []);
  else toast("Track a target first");
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
  if (hit.kind === "alert") {
    show("alerts");
    toast(`${hit.data?.priority || "ALERT"} · ${hit.data?.plate || hit.id}`);
    return;
  }
  if (hit.kind === "trajectory-node" && hit.data?.observation_id) {
    jumpObservation(hit.data.observation_id, hit.id);
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
/* A rank is not a permission set.  This small briefing block is deliberately
 * driven by the authenticated product role: it gives an officer a useful next
 * action without creating a UI switch that could imply access they do not
 * hold.  The API remains the authority for every operation. */
const ROLE_BRIEFS = {
  SUPERVISOR: {
    label: "State command brief",
    scope: "Statewide posture · prioritise, authorise and review exceptions.",
    next: "Review open watchlist alerts, then assess coverage and system health before directing a district response.",
    actions: [["Open alerts", "alerts"], ["Estate map", "map"], ["System health", "system"]],
  },
  INVESTIGATOR: {
    label: "Investigation brief",
    scope: "Assigned jurisdiction · case-bound search, route and evidence.",
    next: "Confirm the case and purpose, search the registration mark, then verify the evidence before acting on a lead.",
    actions: [["Investigate", "investigate"], ["Open evidence", "evidence"], ["Case file", "cases"]],
  },
  OPERATOR: {
    label: "Control-room brief",
    scope: "Assigned jurisdiction · observe, acknowledge and hand over.",
    next: "Work the alert queue, open the relevant camera, and record a clean handover to the investigating officer.",
    actions: [["Open alerts", "alerts"], ["Live cameras", "live"], ["Estate map", "map"]],
  },
  ADMIN: {
    label: "Estate administration brief",
    scope: "Statewide estate · registry, integration and operational health.",
    next: "Resolve degraded camera health, validate source metadata, and keep access policies separate from investigations.",
    actions: [["System health", "system"], ["Camera capability", "cameras"], ["Estate map", "map"]],
  },
  AUDITOR: {
    label: "Oversight brief",
    scope: "Statewide oversight · audit integrity and policy review.",
    next: "Review the audit chain and case handling history. Oversight does not become an investigation side door.",
    actions: [["Audit log", "audit"], ["System health", "system"], ["Estate map", "map"]],
  },
};

function dutyBrief() {
  const role = String(state.principal?.role || "").toUpperCase();
  const brief = ROLE_BRIEFS[role] || {
    label: "Operational brief",
    scope: "Permissions are determined by the signed-in identity.",
    next: "Open the task that matches your authorised operational responsibility.",
    actions: [["Open alerts", "alerts"], ["System health", "system"]],
  };
  return el("section", { class: "duty-brief", "aria-label": "Role-aware operational brief" },
    el("div", { class: "duty-copy" },
      el("div", { class: "duty-eyebrow", text: `${role || "SIGNED-IN"} · PERMISSION-AWARE` }),
      el("h3", { text: brief.label }),
      el("p", { class: "duty-scope", text: brief.scope }),
      el("p", { class: "duty-next" }, el("strong", { text: "Next: " }), brief.next)),
    el("div", { class: "duty-actions", "aria-label": "Role-appropriate workspace actions" },
      ...brief.actions.map(([label, view]) => el("button", {
        class: view === "alerts" ? "primary" : "ghost",
        type: "button",
        onclick: () => show(view),
      }, label))));
}

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
        el("div", { class: "big", text: `${cmd.kpis?.people?.display ?? cmd.persons_detected ?? 0} / ${cmd.kpis?.vehicles?.display ?? cmd.vehicles_tracked ?? 0}` }),
        el("div", { class: "sub", text: `${cmd.kpis?.anpr_reads_per_min?.display ?? cmd.anpr_reads_per_min ?? 0} ANPR / min · ${cmd.kpis?.events_per_min?.display ?? cmd.events_per_min ?? 0} events / min · ${cmd.label}` }),
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
      /* A recording is not a report. The same marks, with their timestamps and
       * cameras, as a file that can be attached to a submission or handed to a
       * court — generated from this store at the moment it is asked for. */
      el("div", { style: "margin:-4px 0 10px" },
        /* Not a plain href: this deployment authenticates with a bearer token
         * held in session storage, and a link the browser follows itself sends
         * no Authorization header - the download would have 401'd. Fetch it
         * with the same credentials every other request uses, then hand the
         * operator the bytes. */
        anprReportButton(),
        el("span", { class: "sid", style: "margin-left:8px",
                     text: "plate · timestamp · camera · district · department" })),
      marks.length
        ? el("div", { class: "plate-gallery" }, ...marks.map(plateCard))
        : el("div", { class: "cap-note", text: "No registration mark in this store yet." }));

    box.append(el("div", { class: "ov-page" },
      el("p", { class: "ov-kicker" },
        el("strong", { text: "Overview" }), "estate health, capability and open alerts"),
      kpis,
      dutyBrief(),
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

function anprReportButton() {
  const btn = el("button", { class: "btn small", type: "button",
                             text: "Download ANPR report (CSV)" });
  btn.addEventListener("click", async () => {
    const was = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Preparing\u2026";
    try {
      const res = await fetch("/reports/anpr.csv?limit=1000",
                              { headers: authHeaders() });
      if (!res.ok) throw new Error(`report ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = el("a", { href: url,
                          download: `saakshya-anpr-${Date.now()}.csv` });
      document.body.append(a);
      a.click();
      a.remove();
      /* Revoke on the next turn of the loop: revoking synchronously can beat
       * the download the click just started. */
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      toast("ANPR report downloaded");
    } catch (err) {
      toast(`Report unavailable: ${err.message || err}`, true);
    } finally {
      btn.disabled = false;
      btn.textContent = was;
    }
  });
  return btn;
}

function plateRead(plate) {
  return el("div", { class: "plate-read", text: String(plate || "—").replace(/\s+/g, "").toUpperCase() });
}

function plateCard(m) {
  const showStill = m.still_ok !== false && !directGovernmentOnDemand();
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
  box.append(loadingNote("Checking subsystem health…"));
  try {
    /* These two are independent, and awaiting them one after the other made
     * the operator wait for the sum rather than the slower of the pair. */
    const summaryPromise = api("/command/summary").catch(() => null);
    const h = await api("/system/health");
    clear(box);
    const dot = $("#sys-dot");
    if (dot) { dot.dataset.state = h.overall; dot.title = `System: ${h.overall}`; }

    try {
      const cmd = await summaryPromise;
      if (cmd?.rank_equivalence?.length) {
        const table = el("table", { class: "data", id: "system-ranks" },
          el("thead", {}, el("tr", {},
            el("th", { text: "Gujarat rank" }),
            el("th", { text: "Product role" }),
            el("th", { text: "Scope" }),
            el("th", { text: "May" }),
            el("th", { text: "Must not" }))));
        const tb = el("tbody");
        for (const row of cmd.rank_equivalence) {
          tb.append(el("tr", {},
            el("td", { text: row.ranks }),
            el("td", { class: "mono", text: row.role }),
            el("td", { text: row.scope }),
            el("td", { text: row.may }),
            el("td", { text: row.must_not })));
        }
        table.append(tb);
        box.append(el("div", { class: "panel ranks-first" },
          el("div", { class: "panel-head" }, el("h3", { text: "Rank → role (existing RBAC)" })),
          el("div", { class: "section-note",
            text: cmd.rank_note || "Six product roles. Fourteen ranks are not fourteen permission sets." }),
          table));
      }
    } catch { /* optional */ }

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
        el("div", { class: "panel-head" }, el("h3", { text: "Connected systems · DEMO / TEST" })),
        el("div", { class: "section-note", text: `${sys.label || "DEMO / TEST"} · ${sys.provenance}` }),
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
     "Native video with a decoupled overlay. Visible government tiles reuse at most twelve Direct WHEP sessions. CONTROL slots never open a government stream. Modes: VIDEO / VEHICLES / PEOPLE / ANPR / FULL."],
    ["Model 3 — Federation & event bus (kept)",
     "VMSAdapter contract (RTSP / ONVIF / Generic). DEMO/TEST connected-systems rows are not government VMS integrations. In-process bus with a Kafka-shaped publish/subscribe seam."],
    ["Model 4 — Central intelligence command (own golden feeds)",
     "Centralized analytics and command orchestration with regional media/AI pools for statewide deployment. Own Feed A + Own Feed B run FULL ANALYTICS (video, people, vehicles, tracking, ANPR, watchlist, alerts, evidence, GIS). This is not 80,000-camera central recording."],
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
/* Four was chosen when a capture could hold a slot for ever; with a deadline
 * on every request the risk of a wider pipe is bounded, and the browser allows
 * six connections per origin. The wall's own camera-list request is issued
 * before any capture, so widening this cannot starve the paint. */
const LIVE_MAX_INFLIGHT = 6;
/* Warm captures answer in 0.03-0.16s and cold ones in a couple of seconds,
 * but a genuinely cold camera behind a busy grid can take far longer and
 * still succeed. Eight seconds cut those off and turned twelve requests with
 * eight answers into twenty-four requests with four. The deadline exists to
 * release a slot that will never come back, not to race a slow camera. */
const SNAPSHOT_TIMEOUT_MS = 20000;
const LIVE_MAX_QUEUE = 12;
function hubPlane() {
  return state.liveConfig?.plane === "local_hub" || state.liveConfig?.hub;
}
function localRelay() {
  return state.liveConfig?.plane === "local_relay" || state.liveConfig?.relay;
}
function directGovernmentOnDemand() {
  return !localRelay() && !hubPlane() && state.liveConfig?.plane === "direct_whep";
}
function mediaPlane() {
  return hubPlane() || localRelay();
}
function liveMaxInflight() {
  return hubPlane() ? 12 : LIVE_MAX_INFLIGHT;
}
function liveMaxQueue() {
  /* A queued preview is not an open source connection.  Keep enough bounded
   * bookkeeping for the complete government wall so cameras 13-30 are not
   * starved behind the first twelve; pumpStills still enforces four actual
   * concurrent captures on the direct plane. */
  if (directGovernmentOnDemand()) return 30;
  return hubPlane() ? 36 : LIVE_MAX_QUEUE;
}
let liveInflight = 0;
const liveQueue = [];
let liveTimer = null;
let livePlayer = null;

/* Only tiles the operator can actually see are captured. A thirty-camera wall
 * on a laptop shows about eight at a time; capturing the other twenty-two is
 * stream capacity spent on pixels nobody is looking at. */
let liveObserver = null;
let liveCaptureEnabled = true;
let liveLayout = "grid";
let liveDistrict = "all";
let liveCamsAll = [];
let liveLoadGeneration = 0;
/* All thirty cameras are on the wall, but the default Grid layout shows them
 * as a scrolling column of large tiles rather than thirty thumbnails: only the
 * handful on screen hold a stream, at full source quality, and the scheduler
 * opens the next ones a screen ahead. Dense gives the 6x5 control-room wall. */
let liveWallMode = 30;
let livePriority = "all";
let liveDomain = "government";
/* A government catalogue wall is an operational index, not permission to open
 * a burst of remote streams.  Direct Sentinel playback is opened only after
 * an operator selects a camera into Focus; the loopback relay may fan out its
 * separate, normalized rendition within its measured capacity. */
/* Direct-grid budget. This was 0 because a catalogue wall must not open a
 * burst of thirty remote streams - the integration contract is explicit that
 * every client gets its own copy and asks callers to open only what they are
 * actively using. That reasoning still holds; what changed is that the wall no
 * longer tries to open everything. Streams follow the viewport, so this caps
 * the few tiles actually on screen rather than the whole catalogue. */
const TILE_WHEP_BUDGET = 12;
const TILE_WHEP_STAGGER_MS = 400;
function tileWhepBudget() {
  /* Two policies, and which one is in force is stated on screen rather than
   * inferred. CONTROL ROOM (the Dense 6x5 wall) holds a session per tile,
   * because an operator watching a control-room wall is watching all of it.
   * OPTIMIZED VIEW (the scrolling wall) keeps only what is near the viewport,
   * honouring the integration contract's request to open only the cameras you
   * are actively using. They are never swapped silently. */
  if (liveLayout === "dense") return localRelay() ? 32 : 30;
  return localRelay() ? 32 : TILE_WHEP_BUDGET;
}
function tileWhepStagger() {
  /* MediaMTX is loopback-fast, but a 30-tile wall still has thirty ICE/SDP
   * negotiations and decoder allocations.  Starting them 90ms apart creates
   * a burst that can leave an otherwise healthy final tile without a track.
   * Keep direct-grid behavior unchanged and pace only the local fan-out. */
  return localRelay() ? 450 : TILE_WHEP_STAGGER_MS;
}
/* How far beyond the viewport a tile is still worth streaming, and how long
 * a tile that has scrolled away keeps its session before it is released. */
const WHEP_PREFETCH_PX = 600;
const WHEP_KEEPALIVE_MS = 15000;
const tileWhepIdleSince = new Map();
let whepSyncTimer = null;
let whepScrollBound = false;
/* Scroll and resize change which tiles deserve a stream, so the wall has to
 * re-evaluate on both. Debounced, because a scroll fires far more often than
 * a peer connection should ever be opened. */
function scheduleTileWhepSync() {
  if (whepSyncTimer) return;
  whepSyncTimer = setTimeout(() => { whepSyncTimer = null; syncTileWhep(); }, 180);
}
/* Command mode: chrome collapses so the wall owns the viewport. Pure layout -
 * it must never start, stop or rebuild a media session, so nothing here
 * touches tileWhep, and the class toggle alone drives the CSS. The wall is
 * fully usable with the command bar hidden, which is the default. */
let commandBarOpen = false;
function applyCommandChrome() {
  document.body.classList.toggle("wall-focus", !commandBarOpen);
  const b = $("#btn-command-bar");
  if (b) b.setAttribute("aria-pressed", commandBarOpen ? "true" : "false");
}
/* Which media policy is in force, stated rather than inferred. The 6x5 Dense
 * wall holds a session per tile; the scrolling Grid wall follows the viewport.
 * They are different contracts and the operator is told which one applies. */
function applyMediaPolicy() {
  const el = $("#media-policy");
  if (!el) return;
  const controlRoom = liveLayout === "dense";
  el.dataset.policy = controlRoom ? "control-room" : "optimized";
  el.textContent = controlRoom ? "CONTROL ROOM" : "OPTIMIZED VIEW";
  el.title = controlRoom
    ? "Control room: one live session per tile on the wall."
    : "Optimized: sessions follow the viewport, ranked by distance from centre.";
}
function bindWhepScroll() {
  if (whepScrollBound) return;
  const grid = $("#live-grid");
  if (!grid) return;
  grid.addEventListener("scroll", scheduleTileWhepSync, { passive: true });
  window.addEventListener("scroll", scheduleTileWhepSync, { passive: true });
  window.addEventListener("resize", scheduleTileWhepSync, { passive: true });
  whepScrollBound = true;
}
/* A paused <video> beside a healthy peer connection is recoverable, and is
 * never the operator's intent. Retry, with a ceiling so a genuinely blocked
 * element does not spin. */
const tileWhep = new Map();
/* The local relay produces browser-safe baseline H.264 renditions.  Its wall
 * uses local WHEP rather than a packet-copy HLS muxer because the government
 * sources can carry B-frames and non-monotonic timestamps. */
const tileHls = new Map();
const tileWhepTimers = new Set();
/* A relay path can become WHEP-ready after its tile was first painted.  Keep
 * exactly one bounded retry timer per camera so an early 503 does not leave a
 * healthy, later-ready stream permanently dark.  This is deliberately not a
 * busy loop: retries back off and are cancelled when a tile leaves the wall. */
const tileWhepRetries = new Map();
function scheduleTileWhep(fn, delay) {
  const timer = setTimeout(() => {
    tileWhepTimers.delete(timer);
    fn();
  }, delay);
  tileWhepTimers.add(timer);
}
function clearTileWhepTimers() {
  for (const timer of tileWhepTimers) clearTimeout(timer);
  tileWhepTimers.clear();
}
const productState = { mode: "operations" };
const intelState = {
  analytics: true,
  mode: "full",
  people: true,
  vehicles: true,
  anpr: true,
  tracking: true,
  compare: false,
  cadence: "BALANCED",
  overlayPollMs: 1000,
};
const snapshotInflight = new Map();
/* Snapshot captures on this estate take one to ten seconds each, and the
 * browser allows only six connections per origin. Leaving Live used to clear
 * the pending queue but had no way to cancel the captures already in flight,
 * so they kept their sockets. Navigating back to Live then issued the wall's
 * camera-list request behind that backlog, where it waited indefinitely: the
 * loader sat on its await, the grid was never painted, and the view stayed
 * blank however long you waited. Track a controller per capture so leaving the
 * view can actually release the connections it borrowed. */
const snapshotAborts = new Set();
function abortSnapshots() {
  for (const ctl of snapshotAborts) { try { ctl.abort(); } catch { /* already settled */ } }
  snapshotAborts.clear();
  liveQueue.length = 0;
  registryStillQueue.length = 0;
}
const snapshotCache = new Map();
let telemetryTimer = null;

function telemetryValue(started, completed) {
  if (!started) return "not started";
  if (!completed) return "in progress";
  return `${Math.round(completed - started)} ms`;
}

/* The simulation wall opens one WHEP session per visible tile (syncTileWhep /
 * negotiateTileWhep) and never touches the single-session t.whep/t.reconnect
 * fields those were written for — those stay at their initial "not started" /
 * "idle" values even while every tile is decoding frames. Report what the
 * browser actually knows about that per-tile fleet instead of a single-session
 * figure that was never wired up to it, and don't invent an aggregate startup
 * latency across sessions that started at different times. */
function simulationTileWhepStats() {
  const sessions = [...tileWhep.values()];
  // firstFrameAt only records that a frame was decoded at some point in the
  // session; it is not re-checked against current playback, so it cannot
  // prove the tile is decoding right now.
  const everDecoded = sessions.filter((s) => s.firstFrameAt).length;
  return { total: sessions.length, everDecoded };
}

function simulationWhepSummary() {
  const { total, everDecoded } = simulationTileWhepStats();
  const base = total
    ? `${everDecoded} of ${total} per-tile WHEP sessions have received/observed at least one decoded frame (historical per-session state, not current-frame health)`
    : "no per-tile WHEP sessions open";
  return base + (state.telemetry.whep.error ? ` · last error: ${state.telemetry.whep.error}` : "");
}

function simulationPlaybackSummary() {
  const { total, everDecoded } = simulationTileWhepStats();
  const base = total
    ? `WHEP REPLAY · ${everDecoded} of ${total} tiles have received/observed at least one decoded frame (historical, not current-frame health)`
    : "WHEP REPLAY · idle — no tiles connected";
  return base + (state.telemetry.playbackError ? ` · error: ${state.telemetry.playbackError}` : "");
}

/* "Browser playback" reports t.browser.state, which is written by the
 * single-session live player's video element events and never touched by
 * the simulation wall's per-tile WHEP sessions — so it sits at its initial
 * "IDLE" forever while tiles are actually decoding. Reuse the same per-tile
 * WHEP fleet used by the WHEP startup / Playback rows above instead of
 * reporting that stale single-session field, and say plainly that this is a
 * per-tile "ever decoded" count, not a per-video-element browser readout and
 * not a live health signal. */
function simulationBrowserPlaybackSummary() {
  const { total, everDecoded } = simulationTileWhepStats();
  return total
    ? `${everDecoded} of ${total} tiles have received/observed at least one decoded frame (per-tile WHEP state, historical not current-frame health; not a browser video-element readout)`
    : "no per-tile WHEP sessions open";
}

function updateTelemetry() {
  const t = state.telemetry;
  const videos = $$("video").filter((v) => !v.paused && v.readyState >= 2);
  /* The focus filmstrip duplicates wall tiles but is hidden outside focus
   * mode. Operator telemetry must describe the wall itself, not those hidden
   * navigation duplicates. */
  const wallTiles = $$("#live .live-grid .live-tile");
  const tiles = wallTiles.filter((tile) => {
    const r = tile.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
      && r.top < innerHeight && r.left < innerWidth;
  });
  const set = (id, text) => { const n = $(`#${id}`); if (n) n.textContent = text; };
  set("telemetry-video", `${videos.length} active / ${$$("video").length} total`);
  set("telemetry-visible", `${tiles.length} of ${wallTiles.length}`);
  set("telemetry-snapshot", liveDomain === "simulation"
    ? "NOT APPLICABLE — WHEP-only replay"
    : telemetryValue(t.snapshot.started, t.snapshot.completed)
      + (t.snapshot.error ? ` · error: ${t.snapshot.error}` : ""));
  set("telemetry-whep", liveDomain === "simulation"
    ? simulationWhepSummary()
    : telemetryValue(t.whep.started, t.whep.completed)
      + (t.whep.error ? ` · error: ${t.whep.error}` : ""));
  set("telemetry-playback", liveDomain === "simulation"
    ? simulationPlaybackSummary()
    : `${t.reconnect}${t.playbackError ? ` · error: ${t.playbackError}` : ""}`);
  const b = t.browser;
  const browserText = b.state === "LIVE"
    ? `LIVE · ${b.fps == null ? "FPS unavailable" : `${b.fps.toFixed(1)} FPS`}`
    : b.state;
  set("telemetry-browser", liveDomain === "simulation"
    ? simulationBrowserPlaybackSummary()
    : browserText);
  set("telemetry-frames", b.framesDecoded == null
    ? "UNAVAILABLE" : `${b.framesDecoded} decoded · ${b.framesDropped ?? 0} dropped`);
  set("telemetry-network", b.packetsReceived == null
    ? "UNAVAILABLE"
    : `${b.packetsReceived} received · ${b.packetsLost ?? 0} lost · `
      + `${b.jitterMs == null ? "jitter unavailable" : `${b.jitterMs.toFixed(1)} ms jitter`}`);
  set("telemetry-codec", b.codec || "not reported");
  set("telemetry-resources", "CPU NOT_MEASURED · GPU NOT_MEASURED");
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

function sourceDomain(cam) {
  if (cam?.source_domain) return cam.source_domain;
  const id = String(cam?.camera_id || "");
  if (/^OWN-/i.test(id)) return "OWN_FEED";
  if (/^cam\d+/i.test(id)) return "GOVERNMENT";
  return "SYNTHETIC_CONTROL";
}

function domainBadge(cam) {
  const d = sourceDomain(cam);
  if (d === "GOVERNMENT") return "GOVERNMENT";
  if (d === "OWN_FEED") return "OWN FEED";
  if (d === "ARCHIVAL_REPLAY") return "ARCHIVAL REPLAY";
  return "CONTROL";
}

function tileStatusLabel(cam) {
  if (cam?.tile_status) return cam.tile_status;
  const st = String(cam?.state || "").toUpperCase();
  if (st === "RECONNECTING") return "RECONNECTING";
  if (st === "DEGRADED") return "DEGRADED";
  if (st === "STREAMING" && (cam.whep_capable || cam.local_replay)) return "LIVE";
  if (st === "STREAMING" && cam.rtsp_capable) return "RTSP_ONLY_AI";
  if (["DOWN", "FAILED", "OPEN_FAILED"].includes(st)) return "NO SIGNAL";
  if (st === "STREAMING" || st === "OBSERVED" || st === "OK") return "PREVIEW";
  if (cam?.local_replay) return "PREVIEW";
  return "NO SIGNAL";
}

function padControlSlots(cams, size) {
  const out = cams.slice();
  let n = 1;
  while (out.length < size) {
    out.push({
      camera_id: `CTL-SLOT-${String(n).padStart(2, "0")}`,
      name: "logical control slot",
      source_domain: "SYNTHETIC_CONTROL",
      domain_badge: "CONTROL",
      tile_status: "NO SIGNAL",
      state: "UNKNOWN",
      enabled: true,
      synthetic_slot: true,
    });
    n += 1;
  }
  return out;
}

function wallCams(cams) {
  const filtered = livePriority === "all"
    ? cams
    : cams.filter((cam) => streamPriority(cam).toLowerCase() === livePriority);
  /* The relay publishes only as many cameras as the host can actually encode,
   * so the catalogue is routinely larger than the set with a local stream.
   * Taking the first N of the catalogue filled the wall with tiles that could
   * never play while published cameras sat unwatched off the end of the list.
   * Put the published set first and keep catalogue order within each group, so
   * the wall is stable between refreshes rather than reshuffling under the
   * operator. */
  const published = new Set(state.liveConfig?.relay_cameras || []);
  const ordered = published.size
    ? filtered.filter((c) => published.has(c.camera_id))
        .concat(filtered.filter((c) => !published.has(c.camera_id)))
    : filtered;
  return ordered.slice(0, liveWallMode);
}

/* All visual representations of a camera share this request and blob URL.
 * The grid, filmstrip and table are intentionally separate accessible views,
 * but they must never become separate upstream consumers. */
async function sharedSnapshot(id) {
  const overlay = hubPlane() ? "off" : (intelState.analytics ? intelState.mode : "off");
  const key = `${id}:${overlay}:${intelState.people}:${intelState.vehicles}:${intelState.anpr}`;
  const cached = snapshotCache.get(key);
  const ttl = localRelay() ? 1500 : (hubPlane() ? 180 : 1000);
  if (cached && Date.now() - cached.fetchedAt < ttl) return cached;
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
  const ctl = new AbortController();
  snapshotAborts.add(ctl);
  /* A capture with no deadline holds one of four in-flight slots for as long
   * as the grid cares to think about it. Measured on a cold wall: twelve
   * requests issued, eight answered, and the four that never returned pinned
   * every slot - the wall froze at 4 of 9 tiles from t+7s to t+34s, twenty-
   * seven seconds in which nothing could be fetched for anybody. A slot is a
   * shared resource, so holding one is a promise to give it back. */
  const deadline = setTimeout(() => {
    try { ctl.abort(); } catch { /* already settled */ }
  }, SNAPSHOT_TIMEOUT_MS);
  const request = fetch(`/cameras/${encodeURIComponent(id)}/snapshot?${qs}`,
                         { headers: authHeaders(), signal: ctl.signal })
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
        video: (res.headers.get("X-Video-State") || "").toUpperCase(),
        sourceState: (res.headers.get("X-Source-State") || "").toUpperCase(),
        ai: (res.headers.get("X-Ai-State") || "").toUpperCase(),
        fps: res.headers.get("X-Hub-Fps") || "",
        fetchedAt: Date.now(),
      };
      snapshotCache.set(key, value);
      state.telemetry.snapshot.completed = performance.now();
      return value;
    })
    .catch((err) => {
      /* An abort is this view releasing a connection it no longer needs, not
       * the grid refusing a capture. Reporting it as a snapshot error made
       * leaving Live look like an estate fault. */
      if (err?.name !== "AbortError") {
        state.telemetry.snapshot.error = err.message || "request failed";
      }
      throw err;
    })
    .finally(() => {
      clearTimeout(deadline);
      snapshotInflight.delete(key);
      snapshotAborts.delete(ctl);
    });
  snapshotInflight.set(key, request);
  return request;
}

/* `front` is for a tile the operator has just scrolled to. Without it a newly
 * visible tile joined the back of a queue behind twenty cameras that had
 * scrolled off, so the wall filled everywhere except where anyone was looking. */
function queueStill(img, id, front = false) {
  if (!img || !id) return;
  if (/^CTL-SLOT-/i.test(id)) return;
  const cam = cameraRecord(id);
  if (cam?.synthetic_slot) return;
  /* The local relay already owns a single upstream ingest for an eligible
   * government tile.  Opening JPEG previews while WHEP is warming creates
   * extra local RTSP readers and can starve a 30-camera wall.  Keep the tile
   * explicitly CONNECTING and let the bounded WHEP retry establish video;
   * JPEG remains available for non-WHEP and unavailable camera paths. */
  if (localRelay() && tileWhepEligible(cam)) return;
  /* Direct government cards may request a bounded still.  A preview capture
   * closes immediately and is never labelled LIVE; only the selected camera
   * may open a moving WHEP session. */
  /* The isolated demo simulation plane has no per-camera still endpoint —
   * CAM-001..030 never exist in the government store/GIS registry, so a
   * snapshot fetch here would just be a 404 loop. Its tile state comes
   * entirely from the WHEP session in syncTileWhep. */
  if (sourceDomain(cam) === "ARCHIVAL_REPLAY") return;
  if (liveQueue.some(([im, cid]) => im === img || cid === id)) return;
  if (!front && liveQueue.length >= liveMaxQueue()) return;
  if (front) liveQueue.unshift([img, id]);
  else liveQueue.push([img, id]);
  if (liveQueue.length > liveMaxQueue()) liveQueue.length = liveMaxQueue();
  pumpStills();
}

function pumpStills() {
  while (liveInflight < liveMaxInflight() && liveQueue.length) {
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
  /* Count what the browser is actually decoding, not what a dataset attribute
   * claims. The tile state is set by the media lifecycle and does not always
   * reach `live` on the direct plane, which had the wall reporting "0 live
   * sessions" while eight tiles were visibly playing. A status line that
   * disagrees with the screen is worse than no status line. */
  const decoding = tiles.filter((t) => {
    const v = t.querySelector("video");
    return v && v.readyState >= 2 && v.videoWidth > 0;
  }).length;
  const live = Math.max(n("live") + n("replay"), decoding);
  const total = tiles.length || $$("#live .live-tile").length;
  const previews = n("preview");
  /* Direct Sentinel cameras use cached, explicitly-labelled stills across the
   * wall and reserve moving WHEP for the selected tile. */
  const directOnDemand = directGovernmentOnDemand();
  const parts = [directOnDemand
    ? `${total} cameras · ${previews} preview frame${previews === 1 ? "" : "s"} · ${live} live session${live === 1 ? "" : "s"}`
    : `${live} of ${total} showing a frame`];
  if (liveInflight) parts.push(`${liveInflight} capturing`);
  if (liveQueue.length) parts.push(`${liveQueue.length} queued`);
  const waiting = n("waiting");
  if (waiting) parts.push(`${waiting} waiting for ingest`);
  const failed = n("failed");
  if (failed) parts.push(`${failed} unavailable`);
  box.textContent = parts.join(" · ");
}

/* A tile's frame area always states where it actually is. It must never read
 * "connecting…" for a camera nothing has tried to connect to.
 *
 * On the direct government plane nothing *is* trying: the wall is a catalogue.
 * Such a tile reads READY and says what would make it live, because an
 * operator who reads CONNECTING on thirty tiles is being told thirty sessions
 * are being negotiated, and none are. */
function setTileState(id, state, text) {
  const onDemand = directGovernmentOnDemand()
    && sourceDomain(cameraRecord(id)) === "GOVERNMENT"
    && livePlayer?.id !== id;
  const readyOnly = onDemand && (state === "idle" || state === "ready");
  for (const tile of $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`)) {
    const frame = tile.querySelector(".frame");
    if (!frame) continue;
    if (frame.querySelector("img.tile-pic, video.tile-whep, video.tile-hls")) continue;
    frame.dataset.state = readyOnly ? "ready" : state;
    const known = frame.dataset.known || "";
    const ph = frame.querySelector(".placeholder") || el("div", { class: "placeholder" });
    clear(ph);
    ph.append(
      el("div", { text: readyOnly ? "READY" : (text || {
        idle: known || "CONNECTING",
        queued: "CONNECTING",
        waiting: "waiting for ingest",
        capturing: "CONNECTING",
      }[state] || state) }),
      readyOnly
        ? el("div", { class: "known", text: "preview queued · select for verified WHEP" })
        : known && state !== "idle"
          ? el("div", { class: "known", text: known }) : null);
    if (!ph.isConnected) frame.append(ph);
  }
}

/* The mandatory replay disclosure must survive every #live-count rerender
 * (wall size change, layout change, etc.), not just the initial paint —
 * losing it on a wall-size click hides that the wall is ARCHIVAL_REPLAY. */
function renderLiveCount(cams) {
  const node = $("#live-count");
  if (!node) return;
  const isSimulation = liveDomain === "simulation"
    || (cams || []).some((c) => sourceDomain(c) === "ARCHIVAL_REPLAY");
  if (isSimulation) {
    node.textContent =
      `${Math.min(cams.length, liveWallMode)} of ${cams.length} cameras · wall ${liveWallMode} · `
      + `LIVE SIMULATION / ARCHIVAL REPLAY · 12h virtual window · repeated 4-minute assets`;
  } else if (directGovernmentOnDemand()
             && cams.every((c) => sourceDomain(c) === "GOVERNMENT")) {
    node.textContent =
      `${cams.length} government cameras indexed · wall ${liveWallMode} · `
      + "BOUNDED PREVIEWS — cached stills rotate across the wall; select one camera for verified WHEP";
  } else {
    node.textContent = `${cams.length} cameras · wall ${liveWallMode}`;
  }
}

/* The isolated demo simulation catalog (CAM-001..CAM-030, ARCHIVAL_REPLAY)
 * is its own plane: fetched only from /demo-simulation/cameras and never
 * merged with GIS/store rows, so a government "NO SIGNAL" tile is never
 * confused with a disabled demo feature. */
async function loadSimulationWall(box) {
  /* The wall is WHEP-only here (no /cameras/{id}/snapshot store endpoint on
   * this plane), so any snapshot telemetry from a prior domain is stale and
   * must not be shown alongside the replay tiles. */
  state.telemetry.snapshot = { started: 0, completed: 0, error: "" };
  let payload;
  try {
    payload = await api("/demo-simulation/cameras");
  } catch (err) {
    liveCamsAll = [];
    $("#live-count").textContent =
      "LIVE SIMULATION / ARCHIVAL REPLAY · 12h virtual window · repeated 4-minute assets · unavailable on this process";
    $("#n-live").textContent = "0";
    labelCount("#n-live", "cameras on the wall");
    box.append(el("div", { class: "notice warn" },
      el("strong", { text: "LIVE SIMULATION / ARCHIVAL REPLAY is not available here." }),
      el("div", { text: err.message || "the isolated demo simulation plane is disabled on this process" })));
    paintLiveFilters([]);
    return;
  }
  const cams = (payload.cameras || []).filter((c) => c.enabled !== false);
  liveCamsAll = cams;
  renderLiveCount(cams);
  $("#n-live").textContent = String(cams.length);
  labelCount("#n-live", "cameras on the wall");

  paintLiveFilters(cams);
  paintLiveWorkspace(cams);
  liveCaptureEnabled = true;
  liveProgress();
  startLiveRefresh();
}

loaders.live = async () => {
  const generation = ++liveLoadGeneration;
  /* Captures still running from a previous visit would otherwise hold every
   * available connection while the request below waits for one. */
  abortSnapshots();
  startTelemetry();
  const box = $("#live");
  clear(box);
  liveLayout = liveLayout || "grid";
  box.dataset.layout = liveLayout;
  box.dataset.wall = String(liveWallMode);
  const liveView = $("#view-live");
  if (liveView) {
    liveView.dataset.wall = String(liveWallMode);
    liveView.dataset.layout = liveLayout;
  }

  if (liveDomain === "simulation") {
    await loadSimulationWall(box);
    return;
  }

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
  /* A prior navigation may still be awaiting GIS while a preset starts a
   * newer load. Never allow that stale response to rebuild the wall and cancel
   * the peer connections owned by the current request. */
  if (generation !== liveLoadGeneration
      || !$("#view-live")?.classList.contains("active")) return;
  cams.sort((a, b) => String(a.camera_id).localeCompare(String(b.camera_id)));
  cams = cams.filter((c) => c.enabled !== false);
  const demoWall = state.dataHolds === "DEMONSTRATION";
  if (liveDomain === "government") {
    cams = cams.filter((c) => sourceDomain(c) === "GOVERNMENT");
    cams.sort((a, b) => {
      const score = (c) => (c.whep_capable ? 4 : 0) + (c.state === "STREAMING" ? 2 : 0)
        + (Number(c.published_marks) || 0) * 0.01;
      return score(b) - score(a);
    });
  } else if (liveDomain === "intelligence") {
    const keep = ["OWN-PEOPLE", "OWN-TRAFFIC"];
    const rank = new Map(keep.map((id, i) => [id, i]));
    cams = cams.filter((c) => rank.has(c.camera_id));
    cams.sort((a, b) => rank.get(a.camera_id) - rank.get(b.camera_id));
    applyIntelMode("full");
  } else if (demoWall && liveDomain === "all") {
    const keep = ["OWN-PEOPLE", "OWN-TRAFFIC", "C-014", "C-021"];
    const rank = new Map(keep.map((id, i) => [id, i]));
    cams = cams.filter((c) => rank.has(c.camera_id));
    cams.sort((a, b) => rank.get(a.camera_id) - rank.get(b.camera_id));
  }
  if (liveWallMode === 50) cams = padControlSlots(cams, 50);
  liveCamsAll = cams;
  renderLiveCount(cams);
  $("#n-live").textContent = String(cams.length);
  labelCount("#n-live", "cameras on the wall");

  paintLiveFilters(cams);
  paintLiveWorkspace(cams);
  liveCaptureEnabled = true;
  liveProgress();
  startLiveRefresh();

  if (livePlayer?.id) return;
  /* Auto-opening a hero tile is an automatic WHEP session. On the direct
   * government plane the operator's selection is the only thing that may open
   * one, so the focus stage stays empty until they choose a camera. */
  if (directGovernmentOnDemand() && liveDomain === "government") return;
  if (liveLayout === "focus" || liveLayout === "twoup") {
    const heroId = demoWall ? "OWN-PEOPLE" : (cams[0] && cams[0].camera_id);
    if (heroId) {
      const hero = $(`#live-strip .live-tile[data-camera="${CSS.escape(heroId)}"]`)
        || $(`#live-grid .live-tile[data-camera="${CSS.escape(heroId)}"]`);
      if (hero) setTimeout(() => openLive(hero, heroId), 400);
    }
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

/* A fixed row height cannot fit an arbitrary viewport: 784px of wall divided
 * into 260px rows leaves 2.98 rows, so the bottom of every screen was a band of
 * sliced tiles. Measure the wall and publish a row height that divides it into
 * whole rows, keeping tiles as close to 16/9 as a whole number of rows allows.
 * Layout only - it never touches a video element or a peer connection. */
function fitWall() {
  const grid = $("#live-grid");
  if (!grid || !$("#view-live")?.classList.contains("active")) return;
  const h = grid.clientHeight;
  const w = grid.clientWidth;
  /* A collapsed or not-yet-laid-out wall measures nothing useful; publishing a
   * row height from it would pin every tile at a few pixels. */
  if (h < 120 || w < 120 || !grid.children.length) return;
  const cs = getComputedStyle(grid);
  const gap = parseFloat(cs.rowGap) || 0;
  const cols = cs.gridTemplateColumns.split(" ").filter(Boolean).length || 1;
  const colW = (w - gap * (cols - 1)) / cols;
  const ideal = colW * 9 / 16;
  const rows = Math.max(1, Math.round((h + gap) / (ideal + gap)));
  const rowH = Math.floor((h - gap * (rows - 1)) / rows);
  if (rowH > 40) grid.style.setProperty("--wall-row-h", `${rowH}px`);
}

/* A <video> can decode without ever painting: an occluded or throttled
 * surface drops frames at the compositor, so `videoWidth` reports 1920 while
 * nothing reaches the screen. Measured on an unfocused pane: eight ready
 * tiles, 99.6% of frames dropped, zero rendered in five seconds - and because
 * the tile had already hidden its still, the operator saw nine black squares
 * on a wall that believed it was live. Having a frame and showing black is
 * the one state this wall must never be in. Demote such a tile back to its
 * still, and promote it again the moment it starts painting. */
function reviewRenderedFrames() {
  const grid = $("#live-grid");
  if (!grid) return;
  for (const tile of grid.children) {
    const video = tile.querySelector("video.tile-whep");
    if (!video || typeof video.getVideoPlaybackQuality !== "function") continue;
    const q = video.getVideoPlaybackQuality();
    const painted = (q.totalVideoFrames || 0) - (q.droppedVideoFrames || 0);
    const last = Number(tile.dataset.painted || -1);
    tile.dataset.painted = String(painted);
    if (last < 0) continue;                       // first sample, no delta yet
    const moving = painted - last > 1;
    const frame = tile.querySelector(".frame");
    const img = frame?.querySelector("img");
    if (moving) {
      tile.dataset.stalledPaints = "0";
      if (video.dataset.ready !== "1" && video.videoWidth > 16) {
        markTileVideoReady(video);
      }
      continue;
    }
    if (video.dataset.ready !== "1") continue;    // already showing the still
    const n = Number(tile.dataset.stalledPaints || 0) + 1;
    tile.dataset.stalledPaints = String(n);
    /* Two consecutive quiet samples, so a single slow beat does not flicker
     * a healthy tile back to a still. */
    if (n < 2) continue;
    delete video.dataset.ready;
    if (img && img.getAttribute("src")) img.style.display = "";
  }
}

let fitWallTimer = null;
function scheduleFitWall() {
  clearTimeout(fitWallTimer);
  fitWallTimer = setTimeout(fitWall, 60);
}
window.addEventListener("resize", scheduleFitWall);

function paintLiveWorkspace(all) {
  const box = $("#live");
  if (!box) return;
  closeTileHlsAll();
  /* The wall is being rebuilt; every camera starts again with a full budget. */
  tileWhepReopens.clear();
  primeVisibleStills.done = false;
  /* A WebRTC track decodes into the element it was attached to. Rebuilding the
   * wall - which changing the wall size does - used to destroy those elements
   * and hand the same MediaStream to fresh ones, and a fresh element has no
   * keyframe to start from: the sender will not resend one unasked, so twelve
   * negotiated sessions sat at zero frames indefinitely. Measured: switching
   * from the 30-wall to the 12-wall left 12 sessions open and 0 decoding, two
   * minutes later still 0. Carry the elements across the rebuild instead. */
  const survivors = new Map();
  for (const v of $$("#live-grid video.tile-whep")) {
    const cam = v.closest(".live-tile")?.dataset.camera;
    if (cam && v.videoWidth > 16) { v.remove(); survivors.set(cam, v); }
  }
  const keep = livePlayer?.id;
  const cams = wallCams(visibleLiveCams(all || liveCamsAll));
  liveQueue.length = 0;
  clear(box);
  box.dataset.layout = liveLayout;
  box.dataset.wall = String(liveWallMode);
  const liveView = $("#view-live");
  if (liveView) {
    liveView.dataset.wall = String(liveWallMode);
    liveView.dataset.layout = liveLayout;
    const shell = liveView.querySelector(".live-shell");
    if (shell) shell.dataset.wall = String(liveWallMode);
  }

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
      tile.dataset.requested = "1";
      queueStill(tile._img, tile.dataset.camera, true);
    }
  }, { rootMargin: "80px", threshold: 0.05 });

  const captureGrid = liveLayout === "grid" || liveLayout === "dense"
    || liveLayout === "twoup";
  const captureStrip = liveLayout === "focus";

  for (const [index, c] of cams.entries()) {
    const tile = liveTile(c, { state: c.state, frames: c.frames, last_error: c.last_error });
    tile.dataset.wallIndex = String(index);
    grid.append(tile);
    const mini = liveTile(c, { state: c.state, frames: c.frames, last_error: c.last_error });
    mini.dataset.wallIndex = String(index);
    strip.append(mini);
    if (captureGrid) liveObserver.observe(tile);
    if (captureStrip) liveObserver.observe(mini);

    const thumb = el("img", { alt: c.camera_id, "data-camera": c.camera_id });
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

  /* Re-home the preserved decoders before anything measures the wall. */
  for (const [cam, video] of survivors) {
    const frame = grid.querySelector(
      `.live-tile[data-camera="${CSS.escape(cam)}"] .frame`);
    if (!frame) continue;
    frame.prepend(video);
    const img = frame.querySelector("img");
    if (img) img.style.display = "none";
    const ph = frame.querySelector(".placeholder");
    if (ph) ph.style.display = "none";
    video.dataset.ready = "1";
  }

  box.append(focus, grid, strip, tab, plates);
  /* Two frames: the grid has no measurable height until it has been laid out. */
  requestAnimationFrame(() => requestAnimationFrame(fitWall));
  /* Populate the complete 30-camera control-room wall.  The queue contains
   * only work descriptors; pumpStills opens at most four short-lived captures
   * and SnapshotService reuses ingest/cache data wherever available. */
  if (directGovernmentOnDemand() && liveDomain === "government"
      && (liveLayout === "grid" || liveLayout === "dense")) {
    for (const tile of $$("#live-grid .live-tile")) {
      if (tile._img) queueStill(tile._img, tile.dataset.camera);
    }
  }
  fillLivePlates();
  liveProgress();
  if (keep) {
    const tile = $(`#live-strip .live-tile[data-camera="${CSS.escape(keep)}"]`)
      || $(`#live-grid .live-tile[data-camera="${CSS.escape(keep)}"]`);
    if (tile) setTimeout(() => openLive(tile, keep), 80);
  }
  requestAnimationFrame(() => requestAnimationFrame(() => {
    bindWhepScroll();
    applyCommandChrome();
    applyMediaPolicy();
    syncTileWhep();
  }));
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
    .then((r) => { if (r.status === 204 || !r.ok) throw new Error(String(r.status)); return r.blob(); })
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
    /* Whether the store has actually answered for this camera, and whether it
     * returned anything. "AI is running" is a claim about persisted data, not
     * about the position of the analytics toggle. */
    metaSeen: false, persisted: 0,
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
      overlayState.metaSeen = true;
      overlayState.persisted = overlayState.tracks.size;
      const counts = res.counts || res;
      const node = $("#live-counts");
      if (node) {
        node.textContent =
          `People: ${Number(counts.people || 0)} · Vehicles: ${Number(counts.vehicles || 0)} · Tracked: ${Number(counts.tracked || 0)} · Plates: ${Number(counts.plates || 0)}`;
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
    if (intelState.analytics && tracks.size === 0) {
      const iso = state.isolation || {};
      const chips = [];
      if (iso.ai_worker?.state === "UNAVAILABLE") chips.push("AI DEGRADED");
      if (iso.ocr?.state === "UNAVAILABLE") chips.push("OCR DEGRADED");
      if (chips.length) {
        ctx.fillStyle = "rgba(0,0,0,0.55)";
        ctx.fillRect(8, 8, 12 * chips.join(" · ").length + 16, 22);
        ctx.fillStyle = "#f5c542";
        ctx.font = "600 12px ui-sans-serif, sans-serif";
        ctx.fillText(chips.join(" · "), 16, 24);
      }
    }
    overlayState.raf = requestAnimationFrame(paint);
  };
  overlayState.poll = setInterval(poll, intelState.overlayPollMs || 1000);
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
  const isSimulation = sourceDomain(cam) === "ARCHIVAL_REPLAY";
  clear(stage);
  const img = el("img", { alt: `Live ${id}` });
  if (isSimulation) img.style.display = "none";
  const fps = cam.measured_fps ? `${Number(cam.measured_fps).toFixed(0)} fps` : "";
  const simUnavailable = isSimulation && !state.simulationConfig?.available;
  const hud = el("div", { class: "hud" },
    el("span", { class: "hud-chip live", text: simUnavailable ? "Unavailable" : "Opening" }),
    isSimulation ? el("span", { class: "hud-chip", text: "ARCHIVAL REPLAY" }) : null,
    (state.liveConfig?.whep || (isSimulation && state.simulationConfig?.available))
      ? el("span", { class: "hud-chip", text: "WHEP" }) : null,
    el("span", { class: "hud-chip", text: cam.codec || "h264" }),
    el("span", { class: "hud-chip", text: cam.width && cam.height ? `${cam.width}×${cam.height}` : id }),
    fps ? el("span", { class: "hud-chip", text: fps }) : null,
    el("span", { class: "hud-chip hud-clock", text: istClock() }));
  const caption = el("div", { class: "stage-cap",
    text: `${cam.name || id} · ${cam.camera_id || id}` });
  const note = el("div", { class: "stage-note",
    text: isSimulation
      ? "LIVE SIMULATION / ARCHIVAL REPLAY — a looped archival asset over an isolated relay, not this camera's current view."
      : "Timestamp is the camera's own burned-in clock." });
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
  const isSimulation = sourceDomain(cam) === "ARCHIVAL_REPLAY";
  const onDemand = !isSimulation && sourceDomain(cam) === "GOVERNMENT"
    && directGovernmentOnDemand();
  const initialVideo = onDemand ? "READY" : "CONNECTING";
  const st = health?.state || cam.state;
  const known = isSimulation
    ? (cam.ready ? "archival replay ready · not yet connected" : "archival replay connecting")
    : !st || st === "UNKNOWN"
      ? "never ingested"
      : st === "OBSERVED"
        ? "observed · health not yet persisted"
        : st === "STREAMING"
          ? `streaming · ${Number(health?.frames || cam.frames || 0).toLocaleString()} frames`
          : `${String(st).toLowerCase()}${health?.last_error ? " · " + health.last_error : ""}`;
  const img = el("img", { class: "tile-pic", alt: `Frame from ${id}` });
  const frame = el("div", { class: "frame", "data-state": initialVideo.toLowerCase() },
    onDemand ? null : el("div", { class: "connect-ring", "aria-hidden": "true" }),
    el("div", { class: "placeholder" },
      el("div", { text: onDemand ? "READY" : "CONNECTING" }),
      el("div", { class: "known", text: onDemand ? "select for verified WHEP live video" : known })));
  frame.dataset.known = known;
  const loc = cam.located === false
    ? "not on the map"
    : (cam.district || cam.location || "district unknown");
  const codecLabel = (cam.codec || "h264").toString();
  const domain = domainBadge(cam);
  const domainClass = sourceDomain(cam) === "GOVERNMENT" ? "gov"
    : sourceDomain(cam) === "OWN_FEED" ? "own"
      : isSimulation ? "sim" : "ctl";
  /* A registry row may *declare* analytics for a camera. On the on-demand wall
   * nothing is decoding that camera, so no detection can have been persisted
   * for it — the tile reports OFF rather than repeating the declaration. The
   * chip is corrected by applyPlane() from measured server state once the
   * camera is actually connected. */
  const aiDeclared = cam.ai_state || (isSimulation ? "NOT_MEASURED" : "OFF");
  const aiLabel = onDemand ? "OFF" : aiDeclared;
  const tile = el("div", { class: "live-tile", "data-camera": id,
    "data-priority": streamPriority(cam).toLowerCase(),
    "data-domain": sourceDomain(cam) },
    el("div", { class: "tile-head" },
      el("span", { class: "vid-chip", "data-plane": "HEADVID",
                   "data-state": initialVideo.toLowerCase(), text: initialVideo }),
      el("span", { class: "name", text: cam.name || id }),
      el("span", { class: "cid mono", text: id }),
      el("span", { class: "ai-head", text: aiLabel === "ACTIVE" ? "AI" : "" }),
      el("span", { class: `domain-badge ${domainClass}`, text: domain })),
    frame,
    el("div", { class: "tile-planes" },
      el("span", { class: "plane-chip", "data-plane": "SRC", text: onDemand ? "SOURCE REGISTERED" : "SOURCE —" }),
      el("span", { class: "plane-chip", "data-plane": "VID",
                   "data-state": initialVideo.toLowerCase(),
                   text: `VIDEO ${initialVideo}` }),
      el("span", { class: "plane-chip", "data-plane": "AI", text: `AI ${aiLabel}` })),
    el("div", { class: "tile-foot" },
      el("span", { class: "loc", text: loc }),
      el("span", { class: "mono res", text: codecLabel }),
      el("span", { class: "fps", text: "" })));
  tile._img = img;
  tile.addEventListener("click", () => {
    if (cam.synthetic_slot) {
      toast("CONTROL slot — not a government camera");
      return;
    }
    openLive(tile, id);
  });
  return tile;
}

function applyPlane(tile, source, video, ai, ageS, fps, extra) {
  if (!tile) return;
  const set = (plane, text, cls) => {
    const n = tile.querySelector(`.plane-chip[data-plane="${plane}"]`);
    if (!n) return;
    n.textContent = text;
    n.dataset.state = (cls || "").toLowerCase().replace(/\s+/g, "-");
  };
  if (source) set("SRC", `SOURCE ${source}`, source);
  if (video) set("VID", `VIDEO ${video}`, video);
  if (ai) set("AI", `AI ${ai}`, ai);
  const head = tile.querySelector(".vid-chip");
  if (head && video) {
    head.textContent = video;
    head.dataset.state = String(video).toLowerCase().replace(/\s+/g, "-");
  }
  const frame = tile.querySelector(".frame");
  if (frame && video) {
    frame.dataset.state = String(video).toLowerCase().replace(/\s+/g, "-");
    frame.classList.toggle("is-live", video === "LIVE");
    frame.classList.toggle("is-preview", video === "PREVIEW" || video === "REPLAY");
    frame.classList.toggle("is-reconnect", video === "RECONNECTING" || video === "DEGRADED");
  }
  const fpsN = tile.querySelector(".tile-foot .fps");
  if (fpsN) {
    fpsN.textContent = fps ? `${fps} fps` : (Number.isFinite(ageS) ? `${ageS.toFixed(1)}s` : "");
  }
  const resN = tile.querySelector(".tile-foot .res");
  if (resN && extra?.width && extra?.height) {
    resN.textContent = `${extra.codec || ""} ${extra.width}×${extra.height}`.trim();
  }
  const aiHead = tile.querySelector(".ai-head");
  if (aiHead) aiHead.textContent = (ai || "").includes("ACTIVE") ? "AI" : "";
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
    if (!inStage && frame && !frame.querySelector("img.tile-pic") && !pumping) {
      setTileState(id, "capturing");
    }
  try {
    const snapshot = await sharedSnapshot(id);
    const url = snapshot.url;
    const ageS = snapshot.age;
    const kind = snapshot.kind;
    const src = snapshot.source;
    img.dataset.url = url;
    img.classList.add("tile-pic");
    img.src = url;
    const videoState = (snapshot.video || "").toUpperCase();
    const isLive = videoState === "LIVE";
    const isPreview = videoState === "PREVIEW" || (!videoState && Number.isFinite(ageS));
    if (inStage) {
      const chip = host.querySelector(".hud-chip.live");
      if (chip) {
        chip.textContent = isLive ? "Live" : (kind === "file-view" ? "Replay" : "Preview");
        chip.classList.toggle("live", isLive);
      }
      return;
    }
    if (frame && img === (tile._img || img)) {
      const ph = frame.querySelector(".placeholder");
      if (ph) ph.remove();
      if (!img.isConnected) frame.prepend(img);
      applyPlane(tile, snapshot.sourceState || snapshot.source,
        videoState || (isPreview ? "PREVIEW" : "NO SIGNAL"),
        snapshot.ai || "OFF", ageS, snapshot.fps);
      let badge = frame.querySelector(".badge");
      if (badge) badge.remove();
      let ageEl = frame.querySelector(".age");
      if (ageEl) ageEl.remove();
    }
  } catch (err) {
    /* The view was left or repainted; this tile is going away. */
    if (err?.name === "AbortError") return;
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
  /* The simulation wall is WHEP-only: every tile is ARCHIVAL_REPLAY, so a
   * still-capture loop or hub-plane poll here would just churn against
   * endpoints the isolated demo plane never exposes. */
  if (liveDomain === "simulation") return;
  const hub = hubPlane();
  const relay = localRelay();
  const direct = !hub && !relay && state.liveConfig?.plane === "direct_whep";
  const ms = hub ? 160 : (relay ? 1200 : (direct ? 20_000 : LIVE_REFRESH_MS));
  liveTimer = setInterval(() => {
    const box = $("#live-refresh");
    if (box && !box.checked) return;
    if (!$("#view-live")?.classList.contains("active")) return;
    if (!liveCaptureEnabled) return;
    if (liveQueue.length > liveMaxQueue() || liveInflight > liveMaxInflight()) return;
    for (const tile of $$("#live-grid .live-tile")) {
      const r = tile.getBoundingClientRect();
      if (r.height < 8 || r.bottom < 0 || r.top > innerHeight) continue;
      if (tileWhep.has(tile.dataset.camera) || tileHls.has(tile.dataset.camera)) continue;
      if (tile.querySelector("video.tile-whep, video.tile-hls")) continue;
      if (tile._img) queueStill(tile._img, tile.dataset.camera);
    }
  }, ms);
  if (mediaPlane()) startHubPlanePoll();
}

let hubPlaneTimer = null;
function startHubPlanePoll() {
  if (hubPlaneTimer) return;
  const tick = async () => {
    if (!mediaPlane() || !$("#view-live")?.classList.contains("active")) return;
    try {
      const snap = await api("/media/hub");
      for (const row of snap.cameras || []) {
        const tiles = $$(`#live .live-tile[data-camera="${CSS.escape(row.camera_id)}"]`);
        for (const tile of tiles) {
          let video = row.video;
          if (localRelay()) {
            const v = tile.querySelector("video.tile-whep, video.tile-hls");
            const sess = tileWhep.get(row.camera_id) || tileHls.get(row.camera_id);
            const renderedRecently = sess?.lastRenderedAt != null
              && performance.now() - sess.lastRenderedAt <= 3000;
            /* The relay health row describes the publisher, not Chromium's
             * compositor. Once this exact tile is visibly receiving frames,
             * browser evidence is authoritative for the VIDEO plane even if
             * a concurrent publisher poll still says RECONNECTING. Conversely,
             * a relay-ready path without a decoded frame is only CONNECTING. */
            if (v && v.readyState >= 2 && v.videoWidth > 0 && renderedRecently) {
              video = decodedPlaybackState(row.camera_id);
            } else if (video === "LIVE" || video === "REPLAY") {
              video = row.source === "CONNECTED" ? "CONNECTING" : video;
            }
          }
          applyPlane(tile, row.source, video, row.ai, row.age_s, row.fps || row.jpeg_fps, row);
        }
      }
      const n = $("#live-progress");
      if (n && snap.government_live != null) {
        n.textContent = `${snap.government_live}/${snap.government_connected || 0} government LIVE · ${snap.browser_replay || 0} replay`;
      }
    } catch { /* hub optional */ }
  };
  hubPlaneTimer = setInterval(tick, 400);
  tick();
}

function stopLiveRefresh() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  if (hubPlaneTimer) { clearInterval(hubPlaneTimer); hubPlaneTimer = null; }
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
      if (img && liveInflight < liveMaxInflight() + 4) {
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
        b.state = decodedPlaybackState(id);
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
          if ((delta ?? 0) > 0) {
            b.lastFrameAt = performance.now();
            b.state = decodedPlaybackState(id);
          }
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

function cameraRecord(id) {
  return liveCamsAll.find((c) => c.camera_id === id) || { camera_id: id };
}

function decodedPlaybackState(id) {
  return sourceDomain(cameraRecord(id)) === "ARCHIVAL_REPLAY" ? "REPLAY" : "LIVE";
}

function tileWhepEligible(cam) {
  if (hubPlane()) return false;
  /* The isolated demo simulation plane is gated on config.simulation, not on
   * the primary government WHEP flag — it runs its own dedicated relay and
   * must stay eligible (or ineligible) independently of that toggle. */
  if (cam && !cam.synthetic_slot && sourceDomain(cam) === "ARCHIVAL_REPLAY") {
    return Boolean(state.simulationConfig?.available);
  }
  if (!state.liveConfig?.whep) return false;
  if (!cam || cam.synthetic_slot) return false;
  if (sourceDomain(cam) === "SYNTHETIC_CONTROL") return false;
  if (localRelay()) {
    const available = state.liveConfig?.relay_cameras;
    if (Array.isArray(available)) return available.includes(cam.camera_id);
    return sourceDomain(cam) === "GOVERNMENT" || sourceDomain(cam) === "OWN_FEED";
  }
  if (sourceDomain(cam) !== "GOVERNMENT") return false;
  /* Direct WHEP is deliberately proxied by the application when it holds the
   * organiser credential.  Registry/GIS responses omit stream URLs by design,
   * so a public camera row may not carry `whep_url` even though the server has
   * attached the documented endpoint internally.  `live.proxy` is the safe
   * authority in that case: it means the server, not the browser, has already
   * confirmed a credential and an eligible registry source. */
  return Boolean(state.liveConfig?.proxy || cam.whep_capable || cam.whep_url);
}

function tileHlsEligible(cam) {
  /* Local WHEP is the primary command-wall transport. HLS remains an explicit
   * diagnostic fallback only (`?transport=hls`), never the default wall. The
   * standalone 30-camera Chromium success used persistent WHEP peers; making
   * the product use another transport recreated none of that proven lifecycle. */
  const forcedFallback = new URLSearchParams(location.search).get("transport") === "hls";
  return Boolean(forcedFallback && localRelay() && state.liveConfig?.hls && cam
    && !cam.synthetic_slot && sourceDomain(cam) === "GOVERNMENT"
    && (liveLayout === "grid" || liveLayout === "dense" || liveLayout === "twoup"));
}

function markTileLive(id, live, fps = null, extra = {}) {
  if (!live) return;
  const cam = cameraRecord(id);
  const domain = sourceDomain(cam);
  const video = (domain === "OWN_FEED" || domain === "ARCHIVAL_REPLAY") ? "REPLAY" : "LIVE";
  for (const tile of $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`)) {
    applyPlane(tile, "CONNECTED", video, null, 0, fps, extra);
    const frame = tile.querySelector(".frame");
    if (frame) {
      frame.dataset.state = video.toLowerCase();
      frame.classList.add("is-settling");
      setTimeout(() => frame.classList.remove("is-settling"), 480);
    }
  }
  liveProgress();
}

function markTileVideoState(id, state, fps = null, extra = {}) {
  for (const tile of $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`)) {
    applyPlane(tile, "CONNECTED", state, null, null, fps, extra);
  }
  liveProgress();
}

/* A WHEP track event only proves that signaling produced a media track. It does
 * not prove that Chromium decoded or rendered a frame. The decoded/rendered
 * state is therefore set exclusively by requestVideoFrameCallback, which runs
 * after a real frame is submitted to the compositor, and is source-provenance-
 * aware (ARCHIVAL_REPLAY cameras report REPLAY, never LIVE). */
function watchRenderedFrames(id, video, sess) {
  if (!video || !sess || video._saakshyaFrameSession === sess) return;
  video._saakshyaFrameSession = sess;
  if (typeof video.requestVideoFrameCallback !== "function") {
    const first = () => {
      sess.firstFrameAt ||= performance.now();
      sess.firstFrameMs ||= sess.firstFrameAt - sess.openedAt;
      sess.lastRenderedAt = performance.now();
      markTileLive(id, true, sess.metrics?.fps ?? null, sess.metrics || {});
    };
    video.addEventListener("loadeddata", first, { once: true });
    return;
  }
  const rendered = (now, metadata) => {
    if ((sess.stream && video.srcObject !== sess.stream) || !video.isConnected) return;
    const first = !sess.firstFrameAt;
    /* This camera decoded, so whatever reopen attempts it needed to get here
     * are spent history. Without this the cap is permanent and global: a
     * camera that used its two attempts early could never be reopened again
     * for the life of the page, so any later repaint - changing the wall size
     * does exactly that - left it dead for good. */
    tileWhepReopens.delete(id);
    sess.firstFrameAt ||= now;
    sess.firstFrameMs ||= sess.firstFrameAt - sess.openedAt;
    sess.lastRenderedAt = now;
    sess.presentedFrames = metadata?.presentedFrames ?? sess.presentedFrames;
    /* A layout change rebuilds the tile DOM but deliberately retains the
     * healthy peer connection.  Reassert LIVE on the replacement card when
     * it renders; otherwise the moving video survives while the counter
     * incorrectly resets to zero. */
    const expected = decodedPlaybackState(id).toLowerCase();
    const marked = $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`)
      .some((tile) => tile.querySelector(".frame")?.dataset.state === expected);
    if (first || !marked) {
      markTileLive(id, true, sess.metrics?.fps ?? null, sess.metrics || {});
    }
    video._saakshyaVfc = video.requestVideoFrameCallback(rendered);
  };
  video._saakshyaVfc = video.requestVideoFrameCallback(rendered);
}

/* HLS may attach and decode its first frame before the media element is ready
 * to honour play(). Calling play() only once, immediately after attachMedia(),
 * left Chromium with a perfectly decoded but paused poster frame. That looked
 * like a live wall while every camera was actually frozen. Retry playback at
 * the media lifecycle points that prove the element can run, and retain the
 * rejection so the UI can report PAUSED instead of claiming LIVE. */
function ensureTilePlayback(id, video, sess) {
  if (!video || !sess || !video.isConnected) return;
  video.muted = true;
  video.defaultMuted = true;
  video.playsInline = true;
  const attempt = video.play();
  if (attempt?.then) {
    attempt.then(() => {
      sess.playError = null;
      sess.lastPlayAt = performance.now();
    }).catch((err) => {
      sess.playError = err?.name || "play rejected";
      markTileVideoState(id, "PAUSED");
    });
  }
}

/* SDP success and even an ontrack callback are not evidence that Chromium has
 * decoded a frame. Do not leave an operator with a permanent CONNECTING tile
 * when a source joins mid-GOP or never sends usable video. The selected,
 * explicit camera may fall back to a labelled still; the rest of the
 * government catalogue remains strictly on-demand. */
function waitForRenderedFrame(video, sess, timeoutMs = 10_000) {
  return new Promise((resolve) => {
    const deadline = performance.now() + timeoutMs;
    const timer = setInterval(() => {
      const rendered = Boolean(sess?.firstFrameAt)
        && video?.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
        && video.videoWidth > 0 && video.videoHeight > 0;
      if (rendered || performance.now() >= deadline) {
        clearInterval(timer);
        resolve(rendered);
      }
    }, 125);
  });
}

async function sampleTileWhep(id, sess) {
  if (!sess?.pc?.getStats) return;
  try {
    const reports = await sess.pc.getStats();
    let inbound = null;
    let codec = "";
    reports.forEach((r) => {
      if (r.type === "inbound-rtp" && r.kind === "video") inbound = r;
      if (r.type === "codec" && r.mimeType?.startsWith("video/")) codec = r.mimeType;
    });
    if (!inbound) return;
    /* Frame rate from the decoder's own counter over wall time, not from
     * `framesPerSecond`. That field reports 0 on a track the decoder is still
     * servicing, which put "0.0s" under a tile that was visibly playing - a
     * number the operator cannot act on and should not be shown. Fall back to
     * the reported value only when there is no interval to measure over. */
    const now = performance.now();
    const decoded = inbound.framesDecoded ?? null;
    let measuredFps = null;
    if (decoded != null && sess.lastDecoded != null && sess.lastDecodedAt != null) {
      const dt = (now - sess.lastDecodedAt) / 1000;
      if (dt >= 0.5) measuredFps = Math.max(0, (decoded - sess.lastDecoded) / dt);
    }
    if (decoded != null && (sess.lastDecodedAt == null || now - sess.lastDecodedAt >= 500)) {
      sess.lastDecoded = decoded;
      sess.lastDecodedAt = now;
    }
    if (measuredFps != null) sess.fpsMeasured = Math.round(measuredFps * 10) / 10;

    sess.metrics = {
      framesDecoded: decoded,
      framesDropped: inbound.framesDropped ?? null,
      packetsLost: inbound.packetsLost ?? null,
      /* Carried so the stall check can tell a connection that is alive and
       * waiting for a keyframe from one that is receiving nothing at all. */
      packetsReceived: inbound.packetsReceived ?? null,
      fps: sess.fpsMeasured ?? inbound.framesPerSecond ?? null,
      width: inbound.frameWidth ?? null,
      height: inbound.frameHeight ?? null,
      codec: codec.replace(/^video\//i, "").toLowerCase(),
    };
    const renderedAgo = sess.lastRenderedAt == null
      ? null : now - sess.lastRenderedAt;
    /* Decoding counts as alive even where the compositor is throttled and
     * requestVideoFrameCallback is not firing: `framesDecoded` advancing is
     * the authoritative signal that video is arriving. */
    const decodingNow = measuredFps != null && measuredFps > 0.2;

    if ((sess.firstFrameAt && renderedAgo <= 3000) || decodingNow) {
      markTileLive(id, true, sess.metrics.fps, sess.metrics);
      sess.lastProgressAt = now;
    } else if (sess.firstFrameAt && renderedAgo > 3000) {
      markTileVideoState(id, "RECONNECTING", sess.metrics.fps, sess.metrics);
    } else {
      markTileVideoState(id, "CONNECTING", null, sess.metrics);
    }
  } catch {
    /* Per-tile metrics are best-effort; playback remains authoritative. */
  }
}

/* Chrome reports a freshly negotiated WHEP track as 2x2 until the first IDR
 * arrives. Treating "a <video> exists" as "this camera is live" blacked out
 * the tile and threw away the one image we did have. A tile is only allowed to
 * drop its still once the decoder reports a real frame size. */
function markTileVideoReady(video) {
  if (!video || video.dataset.ready === "1") return;
  if (video.videoWidth > 16 && video.videoHeight > 16) {
    video.dataset.ready = "1";
    const frame = video.closest(".frame");
    const img = frame?.querySelector("img");
    if (img) img.style.display = "none";
    const ph = frame?.querySelector(".placeholder");
    if (ph) ph.style.display = "none";
    const ring = frame?.querySelector(".connect-ring");
    if (ring) ring.style.display = "none";
  }
}

function watchTileVideoReady(video) {
  const check = () => markTileVideoReady(video);
  video.addEventListener("loadedmetadata", check);
  video.addEventListener("resize", check);
  video.addEventListener("playing", check);
  /* Neither `resize` nor `loadedmetadata` is guaranteed to fire again once a
   * track that opened at 2x2 finally receives its keyframe, so poll briefly
   * rather than leave a live camera showing a stale still for ever. */
  let n = 0;
  const timer = setInterval(() => {
    check();
    if (++n > 60 || video.dataset.ready === "1") clearInterval(timer);
  }, 500);
}

function attachStreamToTile(id, stream, sess = tileWhep.get(id)) {
  /* Focus owns the single visible video element in its stage.  Attaching the
   * same remote track to a hidden grid video as well can stall both Chromium
   * consumers after the first rendered frame. */
  if (liveLayout === "focus") return;
  for (const tile of $$(`#live-grid .live-tile[data-camera="${CSS.escape(id)}"]`)) {
    const frame = tile.querySelector(".frame");
    if (!frame) continue;
    let video = frame.querySelector("video.tile-whep");
    if (!video) {
      video = el("video", { autoplay: true, muted: true, playsInline: true, class: "tile-whep" });
      video.setAttribute("playsinline", "");
      /* The still, the placeholder and the ring stay until this track actually
       * decodes a frame - see markTileVideoReady. */
      watchTileVideoReady(video);
      frame.prepend(video);
    }
    if (video.srcObject !== stream) video.srcObject = stream;
    if (!video._saakshyaPlaybackBound) {
      video._saakshyaPlaybackBound = true;
      video.addEventListener("loadedmetadata", () => ensureTilePlayback(id, video, sess));
      video.addEventListener("canplay", () => ensureTilePlayback(id, video, sess));
      video.addEventListener("playing", () => {
        sess.playError = null;
        sess.lastPlayAt = performance.now();
      });
    }
    ensureTilePlayback(id, video, sess);
    watchRenderedFrames(id, video, sess);
  }
}

function closeTileWhep(id) {
  const retry = tileWhepRetries.get(id);
  if (retry) clearTimeout(retry);
  tileWhepRetries.delete(id);
  const sess = tileWhep.get(id);
  if (!sess) return;
  if (sess.statsTimer) clearInterval(sess.statsTimer);
  try { sess.pc && sess.pc.close(); } catch { /* already closed */ }
  tileWhep.delete(id);
  for (const tile of $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`)) {
    const frame = tile.querySelector(".frame");
    const video = frame?.querySelector("video.tile-whep");
    if (video) {
      if (video._saakshyaVfc && typeof video.cancelVideoFrameCallback === "function") {
        video.cancelVideoFrameCallback(video._saakshyaVfc);
      }
      video.remove();
    }
    const img = frame?.querySelector("img") || tile._img;
    if (img) img.style.display = "";
  }
}

function closeTileWhepAll() {
  clearTileWhepTimers();
  tileWhepIdleSince.clear();
  for (const timer of tileWhepRetries.values()) clearTimeout(timer);
  tileWhepRetries.clear();
  for (const id of [...tileWhep.keys()]) closeTileWhep(id);
}

function closeTileHls(id) {
  const sess = tileHls.get(id);
  if (!sess) return;
  if (sess.retryTimer) clearTimeout(sess.retryTimer);
  try { sess.hls?.destroy(); } catch { /* already disposed */ }
  tileHls.delete(id);
  const video = $(`#live-grid .live-tile[data-camera="${CSS.escape(id)}"] video.tile-hls`);
  if (video) {
    if (video._saakshyaVfc && typeof video.cancelVideoFrameCallback === "function") {
      video.cancelVideoFrameCallback(video._saakshyaVfc);
    }
    video.removeAttribute("src");
    video.load();
    video.remove();
  }
}

function closeTileHlsAll() {
  for (const id of [...tileHls.keys()]) closeTileHls(id);
}

function openTileHls(id) {
  if (tileHls.has(id) || !tileHlsEligible(cameraRecord(id))) return;
  const tile = $(`#live-grid .live-tile[data-camera="${CSS.escape(id)}"]`);
  const frame = tile?.querySelector(".frame");
  if (!frame || !HlsEngine) return;
  const video = el("video", { autoplay: true, muted: true, playsInline: true, class: "tile-hls" });
  video.setAttribute("playsinline", "");
  frame.querySelector("img")?.style && (frame.querySelector("img").style.display = "none");
  frame.querySelector(".placeholder")?.remove();
  frame.prepend(video);
  const sess = { hls: null, stream: null, openedAt: performance.now(),
    firstFrameAt: null, firstFrameMs: null, lastRenderedAt: null,
    presentedFrames: 0, metrics: {}, playError: null, lastPlayAt: null };
  const hlsBase = String(state.liveConfig.hls_base || "").replace(/\/$/, "");
  const url = /^https?:\/\//i.test(hlsBase)
    ? `${hlsBase}/${encodeURIComponent(id)}/index.m3u8`
    : `${hlsBase}/${encodeURIComponent(id)}/hls/index.m3u8`;
  try {
    if (HlsEngine.isSupported()) {
      sess.hls = new HlsEngine({ liveSyncDurationCount: 2, backBufferLength: 4,
        maxBufferLength: 8, enableWorker: true,
        /* HLS.js owns playlist and segment requests, so the normal api()
         * wrapper cannot attach the officer credential. Apply the same
         * in-memory bearer header to every media request; never put it in the
         * URL where it would leak through history, logs or a recording. */
        xhrSetup: (xhr, requestUrl) => {
          // API-proxied media requires the officer bearer token. The direct
          // loopback HLS data plane deliberately receives no application
          // credential and exposes no Sentinel secret or control endpoint.
          if (String(requestUrl || "").startsWith(location.origin)) {
            for (const [key, value] of Object.entries(authHeaders())) {
              xhr.setRequestHeader(key, value);
            }
          }
        },
      });
      tileHls.set(id, sess);
      sess.hls.on(HlsEngine.Events.MEDIA_ATTACHED, () =>
        ensureTilePlayback(id, video, sess));
      sess.hls.on(HlsEngine.Events.MANIFEST_PARSED, () =>
        ensureTilePlayback(id, video, sess));
      sess.hls.loadSource(url);
      sess.hls.attachMedia(video);
      sess.hls.on(HlsEngine.Events.ERROR, (_event, data) => {
        if (!data?.fatal) return;
        markTileVideoState(id, "RECONNECTING");
        // A path that was not ready during the paced wall start can become
        // healthy seconds later. Hls.js stops after a fatal manifest error;
        // without an application retry that tile stays dark forever even
        // though MediaMTX is now publishing it.
        if (!sess.retryTimer) {
          sess.retryTimer = setTimeout(() => {
            sess.retryTimer = null;
            closeTileHls(id);
            if (tileHlsEligible(cameraRecord(id))) openTileHls(id);
          }, 5000);
        }
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      tileHls.set(id, sess);
      video.src = url;
    } else {
      throw new Error("HLS unsupported by this browser");
    }
    video.addEventListener("loadeddata", () => ensureTilePlayback(id, video, sess));
    video.addEventListener("canplay", () => ensureTilePlayback(id, video, sess));
    video.addEventListener("playing", () => {
      sess.playError = null;
      sess.lastPlayAt = performance.now();
    });
    ensureTilePlayback(id, video, sess);
    watchRenderedFrames(id, video, sess);
  } catch {
    closeTileHls(id);
    markTileVideoState(id, "NO SIGNAL");
  }
}

function tileWhepStillEligible(id) {
  const tile = $(`#live-grid .live-tile[data-camera="${CSS.escape(id)}"]`);
  if (!tile || !tile.isConnected) return false;
  const r = tile.getBoundingClientRect();
  if (r.width < 8 || r.height < 8) return false;
  return tileWhepEligible(cameraRecord(id));
}

function scheduleTileWhepRetry(id, attempt = 0, delay = 0) {
  if (tileWhep.has(id) || tileWhepRetries.has(id) || !tileWhepStillEligible(id)) return;
  const ceiling = localRelay() ? 8000 : 15000;
  const wait = delay || Math.min(ceiling, 350 * (1.65 ** attempt));
  const timer = setTimeout(() => {
    tileWhepRetries.delete(id);
    if (!tileWhepStillEligible(id) || tileWhep.has(id)) return;
    negotiateTileWhep(id).then((sess) => {
      if (sess) {
        attachStreamToTile(id, sess.stream, sess);
        return;
      }
      /* A local relay returns 503 while its upstream publisher is warming.
       * Keep trying at a modest cadence; the current DOM and eligibility gate
       * prevent off-wall or closed tiles from consuming a connection. */
      scheduleTileWhepRetry(id, attempt + 1);
    });
  }, wait);
  tileWhepRetries.set(id, timer);
}

async function negotiateTileWhep(id) {
  if (tileWhep.has(id)) return tileWhep.get(id);
  /* The isolated demo simulation plane signals only against its own
   * same-origin, isolated endpoint — never the government relay's WHEP path
   * and never a locally-constructed port. Everything below this branch is
   * the unmodified primary Sentinel/relay WHEP path. */
  const isSimulation = sourceDomain(cameraRecord(id)) === "ARCHIVAL_REPLAY";
  const live = state.liveConfig || {};
  const sim = state.simulationConfig || {};
  if (isSimulation) {
    if (!sim.available) return null;
  } else if (!live.whep) {
    return null;
  }
  const url = isSimulation
    ? `/demo-simulation/cameras/${encodeURIComponent(id)}/whep`
    : (live.proxy
      ? `/cameras/${encodeURIComponent(id)}/whep`
      : `${live.base}/${encodeURIComponent(id)}/whep`);
  const headers = { "Content-Type": "application/sdp", "Accept": "application/sdp" };
  if (isSimulation || live.proxy) Object.assign(headers, authHeaders());
  const pc = new RTCPeerConnection({
    iceServers: localRelay() ? [] : [{ urls: "stun:stun.l.google.com:19302" }],
  });
  const stream = new MediaStream();
  const sess = {
    pc, stream, openedAt: performance.now(), ownsPc: true,
    firstFrameAt: null, firstFrameMs: null, lastRenderedAt: null,
    presentedFrames: 0, metrics: {}, statsTimer: null,
    playError: null, lastPlayAt: null,
  };
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });
  pc.ontrack = (e) => {
    if (!stream.getTracks().includes(e.track)) stream.addTrack(e.track);
    attachStreamToTile(id, stream, sess);
  };
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
      setTimeout(resolve, localRelay() ? 400 : 2500);
    });
    const sdp = pc.localDescription?.sdp || offer.sdp;
    const res = await fetch(url, { method: "POST", headers, body: sdp });
    if (!res.ok) throw new Error(`WHEP ${res.status}`);
    await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
  } catch (err) {
    try { pc.close(); } catch { /* already closed */ }
    state.telemetry.whep.error = err.message || "negotiation failed";
    return null;
  }
  tileWhep.set(id, sess);
  sess.statsTimer = setInterval(() => sampleTileWhep(id, sess), 1000);
  sampleTileWhep(id, sess);
  return sess;
}

/* An IntersectionObserver delivers its first callback for tiles that are
 * already on screen, once, very soon after observe(). That callback was landing
 * while `liveCaptureEnabled` was still false - it is set immediately after the
 * painter returns - so it was dropped, and because a tile that never left the
 * viewport never intersects again, those tiles were never asked for a still at
 * all. Measured on a fresh wall: 0 of 30 tiles requested, 3 with an image; one
 * scroll (which finally produces intersection *changes*) took it to 15 and 14.
 * The operator should not have to scroll to make the wall fill in. */
const STILL_RETRY_MS = 9000;

function primeVisibleStills() {
  const grid = $("#live-grid");
  if (!grid || !liveCaptureEnabled) return;
  const vh = window.innerHeight || document.documentElement.clientHeight || 900;
  const now = Date.now();
  const wanted = [];
  for (const tile of grid.children) {
    const r = tile.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    if (r.bottom < -80 || r.top > vh + 80) continue;
    if (!tile._img) continue;
    /* A tile showing live video, or holding a frame, needs nothing. */
    const video = tile.querySelector("video");
    if (video && video.dataset.ready === "1") continue;
    const shown = tile.querySelector(".frame img");
    if (shown && shown.getAttribute("src")) continue;
    /* Nothing to show yet. A capture that failed is not a camera that has
     * nothing to give: 503 from this grid means it is declining another
     * consumer at this moment, which the tile's own retry treats as fatal
     * after four attempts. For a tile the operator is looking at, keep
     * asking - on a slow cooldown so a declining grid is not hammered. */
    const last = Number(tile.dataset.stillTry || 0);
    if (last && now - last < STILL_RETRY_MS) continue;
    tile.dataset.stillTry = String(now);
    tile.dataset.requested = "1";
    wanted.push(tile);
  }
  if (!wanted.length) return;
  /* The first paint of the visible tiles does not go through the pump.
   *
   * The pump exists to stop a thirty-tile wall opening thirty captures at
   * once, and for the wall at large that is right. But it also meant the nine
   * tiles an operator is actually looking at filled a few at a time: measured,
   * the wall sat at five of nine from t+7s to past t+19s. Asked directly, the
   * grid answers all nine concurrently in 1.6-7.4s - it was never the
   * bottleneck. So the visible tiles are fetched together once, and everything
   * else keeps queueing.
   */
  if (!primeVisibleStills.done) {
    primeVisibleStills.done = true;
    for (const tile of wanted) {
      refreshTile(tile._img, tile.dataset.camera).catch(() => { /* retried */ });
    }
    return;
  }
  for (const tile of wanted) {
    queueStill(tile._img, tile.dataset.camera, true);
  }
}

/* A WHEP session can negotiate cleanly and then never decode a frame: the
 * answer arrives, ICE connects, and no keyframe follows. The tile sits on
 * "CONNECTING · 0 frames" for as long as the operator leaves it there, because
 * nothing in the scheduler distinguishes a session that is starting from one
 * that has silently failed. Give it a deadline and renegotiate - a fresh offer
 * asks the grid for a new keyframe, which is the thing that was missing. */
/* 14s was too aggressive. A government camera with a long GOP can take longer
 * than that to emit a keyframe, and a renegotiation discards the wait and
 * starts it over - so a deadline shorter than the keyframe interval turns a
 * slow camera into one that never decodes at all. Measured: a full recording
 * made with a 14s deadline carried nine covered tiles and *no moving video*,
 * where the run before it had five live tiles. Give the grid time, and give
 * up after a couple of attempts rather than looping on a camera that is not
 * going to answer. */
const WHEP_FIRST_FRAME_MS = 30000;
const WHEP_MAX_REOPENS = 2;
const tileWhepReopens = new Map();
/* The entry retries stop after four seconds, and the still loop runs every
 * twenty on this plane and returns early whenever its queue is busy. Neither
 * is a health check for the wall itself, so a session that stalled at second
 * fifteen stayed stalled. This heartbeat is that check. syncTileWhep is
 * idempotent - it reattaches what it holds and negotiates only what is
 * missing - so running it on a timer costs nothing when all is well. */
const WALL_HEARTBEAT_MS = 5000;
let wallTimer = null;

function startWallHeartbeat() {
  stopWallHeartbeat();
  wallTimer = setInterval(() => {
    if (!$("#view-live")?.classList.contains("active")) return;
    reviewRenderedFrames();
    syncTileWhep();
  }, WALL_HEARTBEAT_MS);
}

function stopWallHeartbeat() {
  if (wallTimer) { clearInterval(wallTimer); wallTimer = null; }
}

function reopenStalledTileWhep() {
  const now = performance.now();
  for (const [id, sess] of [...tileWhep.entries()]) {
    if (!sess || sess.firstFrameAt) continue;
    if (now - (sess.openedAt || now) < WHEP_FIRST_FRAME_MS) continue;
    const video = $(`#live-grid .live-tile[data-camera="${CSS.escape(id)}"] video`);
    /* Decoding already? Then it is healthy and simply had no firstFrameAt
     * recorded; never tear down a session that is delivering pictures. */
    if (video && video.videoWidth > 16) continue;
    /* Packets arriving means the connection is alive and we are waiting on a
     * keyframe, not on the network. Restarting that throws the wait away and
     * begins it again, which is how a slow camera becomes a dead one. */
    if ((sess.metrics?.packetsReceived || 0) > 0) continue;
    const tries = tileWhepReopens.get(id) || 0;
    if (tries >= WHEP_MAX_REOPENS) continue;
    tileWhepReopens.set(id, tries + 1);
    closeTileWhep(id);
    markTileVideoState(id, "RECONNECTING");
  }
}

function syncTileWhep() {
  clearTileWhepTimers();
  reopenStalledTileWhep();
  primeVisibleStills();
  const layout = $("#live")?.dataset.layout || liveLayout;
  /* Stream what the operator can actually see, plus a screen either side, and
   * let the rest of the wall wait. Thirty simultaneous full-resolution decodes
   * is more than a laptop will hold smoothly, but the ten or so on screen are
   * comfortable - so the visible tiles get real video at full quality instead
   * of every tile getting a degraded one. The prefetch margin means a tile is
   * already playing by the time a scroll brings it into view. */
  const vh = window.innerHeight || document.documentElement.clientHeight || 900;
  /* CONTROL ROOM shows the whole wall at once and every tile is meant to be
   * live, so the prefetch window covers it rather than the screen. */
  const margin = liveLayout === "dense"
    ? Number.POSITIVE_INFINITY
    : Math.max(WHEP_PREFETCH_PX, vh);
  const candidates = $$("#live-grid .live-tile").filter((t) => {
    if (layout === "focus" || layout === "tab") return false;
    const r = t.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return false;
    if (r.bottom < -margin || r.top > vh + margin) return false;
    const cam = cameraRecord(t.dataset.camera);
    return tileWhepEligible(cam) && !tileHlsEligible(cam);
  });
  /* Rank by distance from the middle of the screen before applying the budget.
   * Taking the first N in DOM order instead looks correct until you scroll:
   * the prefetch margin keeps far more tiles eligible than the budget allows,
   * so the earliest tiles in the document win every time and the selection
   * never changes no matter where the operator is looking. Sorting by
   * proximity is what makes the streams actually follow the viewport. */
  const centre = vh / 2;
  const distance = (t) => {
    const r = t.getBoundingClientRect();
    return Math.abs((r.top + r.bottom) / 2 - centre);
  };
  const visible = candidates
    .map((t) => [t, distance(t)])
    .sort((a, b) => a[1] - b[1])
    .slice(0, tileWhepBudget())
    .map(([t]) => t);
  const keep = new Set(visible.map((t) => t.dataset.camera));
  if (livePlayer?.id && tileWhepEligible(cameraRecord(livePlayer.id))) keep.add(livePlayer.id);
  /* Scrolling a tile just past the margin must not tear its session down at
   * once: a scroll that overshoots and comes back would otherwise close and
   * renegotiate the same camera, which is the flicker this wall is meant to be
   * free of. Give a departed tile a grace period and close it only if the
   * operator has genuinely moved on. */
  const now = Date.now();
  for (const id of [...tileWhep.keys()]) {
    if (keep.has(id)) { tileWhepIdleSince.delete(id); continue; }
    const since = tileWhepIdleSince.get(id);
    if (since === undefined) { tileWhepIdleSince.set(id, now); continue; }
    if (now - since >= WHEP_KEEPALIVE_MS) {
      tileWhepIdleSince.delete(id);
      closeTileWhep(id);
    }
  }
  let delay = 0;
  for (const tile of visible) {
    const id = tile.dataset.camera;
    if (tileWhep.has(id)) {
      const sess = tileWhep.get(id);
      attachStreamToTile(id, sess.stream, sess);
      continue;
    }
    const wait = delay;
    delay += tileWhepStagger();
    scheduleTileWhep(() => {
      negotiateTileWhep(id).then((sess) => {
        if (sess) { attachStreamToTile(id, sess.stream, sess); return; }
        markTileVideoState(id, "RECONNECTING");
        scheduleTileWhepRetry(id);
      });
    }, wait);
  }
  const hlsVisible = $$("#live-grid .live-tile").filter((t) => {
    if (layout === "focus" || layout === "tab") return false;
    const r = t.getBoundingClientRect();
    return r.width >= 8 && r.height >= 8 && tileHlsEligible(cameraRecord(t.dataset.camera));
  });
  const hlsKeep = new Set(hlsVisible.map((t) => t.dataset.camera));
  for (const id of [...tileHls.keys()]) if (!hlsKeep.has(id)) closeTileHls(id);
  // MediaMTX creates an HLS muxer on the first playlist request. Starting
  // thirty muxers in one browser task floods the same-origin proxy and makes
  // every request appear broken. Pace starts across a few seconds; existing
  // sessions remain attached immediately on subsequent wall renders.
  let hlsDelay = 0;
  for (const tile of hlsVisible) {
    const id = tile.dataset.camera;
    if (tileHls.has(id)) continue;
    scheduleTileWhep(() => openTileHls(id), hlsDelay);
    hlsDelay += 250;
  }
}

/* WHEP: the browser offers, the media server answers, and the video arrives on
 * the peer connection. Falls back to the selected-camera still pump if anything
 * in that exchange fails, rather than leaving a black rectangle. */
async function openLive(tile, id) {
  closeLive();
  $$(`.live-tile[data-camera="${CSS.escape(id)}"]`).forEach((t) => t.classList.add("selected"));
  livePlayer = { pc: null, tile, id, statsTimer: null, ownsPc: false };
  fillLiveStage(id);

  const camRec = cameraRecord(id);
  const isSimulation = sourceDomain(camRec) === "ARCHIVAL_REPLAY";

  /* The isolated demo simulation catalog has no still/registry endpoint —
   * CAM-001..030 never exist in the government store — so the still pump
   * would just 404-loop. Its stage relies entirely on the WHEP path below. */
  let fileView = false;
  /* On the direct government plane WHEP itself is the selected-camera view.
   * Calling /view first opens a second RTSP decoder for the same source and
   * can leave the subsequent browser session negotiated but starved of an
   * IDR/frame.  /view remains necessary for own/local file feeds. */
  if (!isSimulation && !directGovernmentOnDemand()) {
    try {
      const vr = await fetch(`/cameras/${encodeURIComponent(id)}/view`, {
        method: "POST", headers: authHeaders(),
      });
      if (vr.ok) {
        const body = await vr.json().catch(() => ({}));
        fileView = body.source === "file";
      }
    } catch { /* stills still refresh */ }
  }

  /* A still is an explicit *degraded fallback*. It is started only once the
   * WHEP path for this camera is known to be unavailable or to have failed —
   * never racing a negotiation that is still in flight, because a capture that
   * lands first would relabel live video as Preview. The stage says which of
   * the two it is showing and why. */
  const fallbackToSnapshot = (reason) => {
    state.telemetry.reconnect = `fallback to snapshot: ${reason}`;
    const stage = $("#live-stage");
    const chip = stage?.querySelector(".hud-chip.live");
    if (chip) {
      chip.textContent = "Preview";
      chip.classList.remove("live");
    }
    const note = stage?.querySelector(".stage-note");
    if (note) {
      note.textContent = `No verified WHEP session — ${reason}. `
        + "Anything shown here is a cached PREVIEW, not live video.";
    }
    /* A tile must carry the same provenance as the focus stage. Without this
     * explicit state, a successful still fetch can make a rejected WHEP
     * request look like a normal preview, hiding an upstream admission error
     * from the operator who selected it. */
    for (const candidate of $$(`#live .live-tile[data-camera="${CSS.escape(id)}"]`)) {
      applyPlane(candidate, "DEGRADED", "PREVIEW", "OFF");
      candidate.title = `WHEP unavailable: ${reason}. Cached preview only.`;
      let warning = candidate.querySelector(".tile-whep-warning");
      if (!warning) {
        warning = el("span", { class: "tile-whep-warning" });
        candidate.querySelector(".tile-planes")?.append(warning);
      }
      warning.textContent = `WHEP unavailable — ${reason}`;
    }
    if (!localRelay() && !isSimulation) startStillPump(id);
  };

  if (!isSimulation) {
    const live = state.liveConfig || {};
    if (!live.whep) {
      fallbackToSnapshot("WHEP is not enabled on this process");
      return;
    }
    if (fileView && !localRelay()) {
      fallbackToSnapshot("this camera resolves to a stored file view");
      return;
    }
  }
  if (!tileWhepEligible(camRec) && sourceDomain(camRec) !== "OWN_FEED") {
    fallbackToSnapshot("this camera is not WHEP-capable on this plane");
    return;
  }

  resetBrowserTelemetry();
  state.telemetry.whep.started = performance.now();
  state.telemetry.whep.completed = 0;
  state.telemetry.whep.error = "";
  state.telemetry.reconnect = "negotiating";
  let video = el("video", { autoplay: true, muted: true, playsInline: true, class: "live-whep" });
  video.setAttribute("playsinline", "");

  const sess = tileWhep.get(id) || await negotiateTileWhep(id);
  if (!livePlayer || livePlayer.id !== id) return;
  if (!sess) {
    const message = String(state.telemetry.whep.error || "");
    const status = message.match(/\bWHEP\s+(\d{3})\b/i)?.[1];
    const reason = status === "401"
      ? "source authorization rejected the WHEP request (HTTP 401)"
      : status
        ? `source rejected the WHEP request (HTTP ${status})`
        : "WHEP negotiation did not produce a session";
    fallbackToSnapshot(reason);
    return;
  }
  livePlayer.pc = sess.pc;
  livePlayer.ownsPc = false;
  const stageOwnsVideo = liveLayout === "focus";
  if (!stageOwnsVideo) {
    const tileVideo = $(`#live-grid .live-tile[data-camera="${CSS.escape(id)}"] video.tile-whep`);
    if (tileVideo) video = tileVideo;
  }
  video.srcObject = sess.stream;
  video.play().catch(() => {
    state.telemetry.playbackError = "autoplay blocked";
    updateTelemetry();
  });
  const stage = $("#live-stage");
  if (!stage) return;
  stopStillPump();
  if (stageOwnsVideo) {
    const img = stage.querySelector("img");
    if (img) img.style.display = "none";
    if (!stage.querySelector("video.live-whep")) {
      stage.insertBefore(video, stage.firstChild);
    }
  }
  watchRenderedFrames(id, video, sess);
  const rendered = await waitForRenderedFrame(video, sess);
  if (!livePlayer || livePlayer.id !== id) return;
  if (!rendered) {
    state.telemetry.browser.state = "NO_FRAME";
    state.telemetry.whep.error = "WHEP negotiated but no browser-decoded frame within 10 s";
    markTileVideoState(id, "DEGRADED", null, sess.metrics || {});
    video.srcObject = null;
    video.remove();
    if (tileWhep.get(id) === sess) closeTileWhep(id);
    fallbackToSnapshot("WHEP negotiated but no decoded frame arrived within 10 s");
    updateTelemetry();
    return;
  }
  if (stageOwnsVideo && intelState.compare) {
    stage.querySelector(".live-compare")?.remove();
    mountCompare(stage, video);
  }
  const chip = stage.querySelector(".hud-chip.live");
  if (chip) {
    chip.textContent = isSimulation ? "Replay" : "Live";
    chip.classList.add("live");
  }
  state.telemetry.whep.completed = performance.now();
  state.telemetry.reconnect = "connected";
  livePlayer.statsTimer = startBrowserWatchdog(video, sess.pc, id);
  updateTelemetry();
}

function closeLive() {
  stopStillPump();
  stopLiveClock();
  stopDetectionOverlay();
  if (!livePlayer) return;
  if (livePlayer.statsTimer) clearInterval(livePlayer.statsTimer);
  /* Shared tile sessions stay open so returning to the wall does not open a
   * second WHEP. Only a privately owned hero PC is closed here. */
  if (livePlayer.ownsPc) {
    try { livePlayer.pc && livePlayer.pc.close(); } catch { /* already closed */ }
  }
  const stageVideo = $("#live-stage")?.querySelector("video.live-whep");
  if (stageVideo) {
    if (stageVideo._saakshyaVfc && typeof stageVideo.cancelVideoFrameCallback === "function") {
      stageVideo.cancelVideoFrameCallback(stageVideo._saakshyaVfc);
    }
    stageVideo.srcObject = null;
    stageVideo.remove();
  }
  state.telemetry.browser.state = "IDLE";
  const id = livePlayer.id || livePlayer.tile?.dataset.camera;
  $$(`.live-tile[data-camera="${CSS.escape(id || "")}"]`).forEach((t) => t.classList.remove("selected"));
  livePlayer = null;
}

$("#live-reload")?.addEventListener("click", () => {
  liveQueue.length = 0;
  for (const tile of $$("#live .live-tile")) {
    delete tile.dataset.requested;
    if (tile._img) queueStill(tile._img, tile.dataset.camera);
  }
});

$("#btn-command-bar")?.addEventListener("click", () => {
  commandBarOpen = !commandBarOpen;
  applyCommandChrome();
  /* The wall just changed size, so which tiles are near the viewport centre
   * changed with it. Re-rank; this opens or releases sessions by the same
   * rules as a scroll and rebuilds nothing. */
  scheduleTileWhepSync();
});

$$("[data-live-layout]").forEach((b) => b.addEventListener("click", () => {
  liveLayout = b.dataset.liveLayout || "grid";
  $$("[data-live-layout]").forEach((x) => x.classList.toggle("on", x === b));
  const box = $("#live");
  if (box) box.dataset.layout = liveLayout;
  /* #view-live carries the layout too: the wall's geometry rules key off it,
   * and without this a Grid<->Dense switch changed nothing visually. */
  const liveView = $("#view-live");
  if (liveView) liveView.dataset.layout = liveLayout;
  applyMediaPolicy();
  /* Reuse existing sessions across the switch. A layout change is not a
   * reason to renegotiate a stream that is already playing. */
  scheduleTileWhepSync();
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

/* A wall-size or priority change repaints the grid, which destroys the tiles
 * the media scheduler was tracking. The layout buttons already re-sync after
 * their repaint; these two did not, so changing the wall size left a grid of
 * cached stills reading "0 live sessions" until something else happened to
 * trigger a sync. Same reason, same fix, and the repaint is async so the sync
 * has to be retried rather than fired once. */
function resyncAfterRepaint() {
  for (const delay of [0, 300, 900, 2000]) {
    setTimeout(() => {
      if (!$("#view-live")?.classList.contains("active")) return;
      bindWhepScroll();
      applyCommandChrome();
      applyMediaPolicy();
      syncTileWhep();
    }, delay);
  }
}

$$("[data-live-wall]").forEach((b) => b.addEventListener("click", () => {
  liveWallMode = Number(b.dataset.liveWall) || 9;
  renderLiveCount(liveCamsAll);
  $$("[data-live-wall]").forEach((x) => {
    const active = x === b;
    x.classList.toggle("on", active);
    x.setAttribute("aria-pressed", active ? "true" : "false");
  });
  if ($("#view-live")?.classList.contains("active")) {
    paintLiveWorkspace(liveCamsAll);
    resyncAfterRepaint();
  }
}));

$$("[data-live-priority]").forEach((b) => b.addEventListener("click", () => {
  livePriority = b.dataset.livePriority || "all";
  $$("[data-live-priority]").forEach((x) => {
    const active = x === b;
    x.classList.toggle("on", active);
    x.setAttribute("aria-pressed", active ? "true" : "false");
  });
  if ($("#view-live")?.classList.contains("active")) {
    paintLiveWorkspace(liveCamsAll);
    resyncAfterRepaint();
  }
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
            el("button", { class: "ghost", onclick: () => trackEntity(a.plate, a) }, "TRACK VEHICLE"),
            el("button", { class: "ghost", onclick: () => routeAlert(a) }, "ROUTE"),
            el("button", { class: "ghost", onclick: () => { show("map"); toast("GIS: camera " + (a.camera_id || "")); } }, "OPEN GIS"),
            a.status === "OPEN" ? el("button", { class: "ghost", onclick: async (e) => {
              e.target.disabled = true;
              try {
                await api(`/alerts/${encodeURIComponent(a.alert_id)}/acknowledge`, { method: "POST" });
                toast("Acknowledged"); loaders.alerts();
              } catch (err) { toast(`${err.code}: ${err.message}`, true); }
            } }, "ACKNOWLEDGE") : el("span", { class: "chip", text: a.status })
          )
        )
      ))
    );
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
    const { MapView } = await import("/ui/map.js?v=cr100");
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

    /* Model 1 asks the registry to report its own gaps. A registry that lists
     * only what it holds hides the fields that actually block onboarding a
     * department, so the missing ones are named here, above the inventory. */
    try {
      const gaps = await api("/gis/gaps");
      const card = el("div", { class: "ov-card", style: "margin:12px" },
        el("h3", { text: "Registry gap analysis" }),
        el("p", { class: "lede", text:
          `${gaps.cameras} cameras onboarded, ${gaps.capacity_slots} capacity `
          + "slots. What no department has supplied yet:" }));
      const absent = gaps.departments_absent || [];
      if (absent.length) {
        card.append(el("div", { class: "notice warn" },
          el("strong", { text: `${absent.length} expected department`
            + `${absent.length === 1 ? "" : "s"} with no camera onboarded` }),
          el("div", { text: absent.join(" · ") })));
      }
      const present = Object.entries(gaps.departments_present || {});
      if (present.length) {
        card.append(el("div", { class: "sid", style: "margin:8px 0",
          text: "Onboarded by department — "
            + present.map(([d, n]) => `${d}: ${n}`).join(" · ") }));
      }
      const tbl = el("table", { class: "data" },
        el("thead", {}, el("tr", {},
          el("th", { text: "Field" }), el("th", { text: "Missing" }),
          el("th", { text: "Of" }), el("th", { text: "Share" }))));
      const tb = el("tbody");
      for (const g of (gaps.field_gaps || [])) {
        if (!g.missing) continue;
        tb.append(el("tr", {},
          el("td", { class: "mono", text: g.field }),
          el("td", { class: "num", text: String(g.missing) }),
          el("td", { class: "num", text: String(g.of) }),
          el("td", { class: "num", text: `${g.pct}%` })));
      }
      if (!tb.children.length) {
        tb.append(el("tr", {}, el("td", { colspan: "4" },
          el("span", { class: "sid", text: "No missing registry fields." }))));
      }
      tbl.append(tb);
      card.append(tbl);
      if (gaps.note) card.append(el("div", { class: "sid", text: gaps.note }));
      box.append(card);
    } catch (err) {
      box.append(el("div", { class: "notice", style: "margin:12px" },
        `Gap analysis unavailable: ${err.message || err}`));
    }

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
    /* Eighteen of the fifty rows in this estate are capacity slots, not
     * cameras: no stream, no samples, coordinates in open water. Grading them
     * produced three UNKNOWN chips apiece and eighteen rows of apparent
     * breakage above the real estate. A slot with nothing to measure is not a
     * camera awaiting a grade, and the table should say which it is. Real
     * cameras first, and a slot states what it is instead of pretending to be
     * ungraded. */
    const isSlot = (f) => f.source_domain === "SYNTHETIC_CONTROL"
      || /^CTL-/.test(String(f.camera_id || ""));
    const ordered = [...res.features].sort((a, b) => Number(isSlot(a)) - Number(isSlot(b)));
    for (const f of ordered) {
      if (isSlot(f)) {
        tb.append(el("tr", { class: "slot-row" },
          el("td", { class: "mono", text: f.camera_id }),
          el("td", { class: "mono", text: f.resolution || "—" }),
          el("td", { text: f.codec || "—" }),
          el("td", { colspan: "9" },
            el("span", { class: "chip unknown", text: "CAPACITY SLOT" }),
            el("span", { class: "sid", style: "margin-left:8px",
                         text: "reserved headroom — no stream, nothing to grade" }))));
        continue;
      }
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

function kpiCell(title, item) {
  const display = item?.display ?? item?.value ?? "NOT_MEASURED";
  const src = item?.source || item?.label || "";
  const meta = [item?.scope, item?.timestamp].filter(Boolean).join(" · ");
  return el("div", { class: "kpi kpi-sourced" },
    el("h4", { text: title }),
    el("div", { class: "big", text: String(display) }),
    src ? el("div", { class: "sub", text: src }) : null,
    meta ? el("div", { class: "sub kpi-meta", text: meta }) : null);
}

function paintIntelCommand(cmd) {
  if (cmd?.isolation) state.isolation = cmd.isolation;
  const health = $("#intel-health");
  if (health) {
    clear(health);
    health.append(
      el("div", { class: "chip", text: `Online ${cmd?.kpis?.cameras_online?.display ?? cmd?.healthy ?? "—"}` }),
      el("div", { class: "chip", text: `Alerts ${cmd?.kpis?.active_alerts?.display ?? cmd?.active_alerts ?? "—"}` }),
      el("div", { class: "chip", text: `AI P50 ${cmd?.kpis?.ai_latency_p50?.display ?? "NOT_MEASURED"}` }),
    );
    for (const row of Object.values(cmd?.isolation || {})) {
      if (row?.chip) health.append(el("div", { class: "chip verify", text: row.chip }));
    }
  }
  const kpiBox = $("#intel-kpis");
  if (kpiBox && cmd?.kpis) {
    clear(kpiBox);
    const order = [
      ["Cameras online", "cameras_online"],
      ["Cameras degraded", "cameras_degraded"],
      ["Active WHEP", "active_whep"],
      ["Preview", "preview"],
      ["AI streams", "ai_streams"],
      ["Active alerts", "active_alerts"],
      ["ANPR reads/min", "anpr_reads_per_min"],
      ["Vehicles", "vehicles"],
      ["People", "people"],
      ["Events/min", "events_per_min"],
      ["AI latency P50", "ai_latency_p50"],
      ["AI latency P95", "ai_latency_p95"],
      ["Watchlist alert latency", "watchlist_alert_latency"],
    ];
    for (const [title, key] of order) kpiBox.append(kpiCell(title, cmd.kpis[key]));
  }
  const resBox = $("#intel-resources");
  if (resBox && cmd?.resources) {
    clear(resBox);
    resBox.append(el("div", { class: "sid", text: "AI RESOURCE PANEL" }));
    const order = [
      ["AI workers", "ai_workers"],
      ["Detector FPS", "detector_fps"],
      ["OCR FPS", "ocr_fps"],
      ["Inference P50", "inference_p50"],
      ["Inference P95", "inference_p95"],
      ["Queue depth", "queue_depth"],
      ["CPU", "cpu"],
      ["GPU", "gpu"],
      ["RAM", "ram"],
    ];
    for (const [title, key] of order) resBox.append(kpiCell(title, cmd.resources[key]));
  }
}

function paintCommandStatus(cmd, o) {
  const health = $("#cc-health");
  const alerts = $("#cc-alerts");
  const ai = $("#cc-ai");
  if (health) {
    const online = cmd?.kpis?.cameras_online?.display ?? cmd?.healthy ?? "—";
    const deg = cmd?.kpis?.cameras_degraded?.display ?? cmd?.degraded ?? "—";
    health.textContent = `Online ${online} · degraded ${deg} (store)`;
  }
  if (alerts) {
    alerts.textContent = `Alerts ${o?.alerts?.open ?? cmd?.kpis?.active_alerts?.display ?? cmd?.active_alerts ?? "—"}`;
  }
  if (ai) {
    const chips = Object.values(cmd?.isolation || {})
      .map((row) => row?.chip).filter(Boolean);
    const p50 = cmd?.kpis?.ai_latency_p50?.display ?? "NOT_MEASURED";
    ai.textContent = chips.length ? chips.join(" · ") : `AI P50 ${p50}`;
    ai.classList.toggle("verify", chips.length > 0);
  }
}

function applyIntelMode(mode, repaint = true) {
  intelState.mode = mode;
  intelState.analytics = mode !== "video" && mode !== "off";
  if (mode === "video") intelState.analytics = false;
  if (mode === "vehicles") { intelState.vehicles = true; intelState.people = false; intelState.anpr = false; }
  if (mode === "people") { intelState.vehicles = false; intelState.people = true; intelState.anpr = false; }
  if (mode === "anpr") { intelState.vehicles = true; intelState.people = false; intelState.anpr = true; }
  if (mode === "both") {
    intelState.vehicles = true; intelState.people = true; intelState.anpr = false;
  }
  if (mode === "full" || mode === "incident") {
    intelState.vehicles = true; intelState.people = true; intelState.anpr = true;
  }
  snapshotCache.clear();
  const cam = livePlayer?.id;
  const canvas = $("#live-overlay");
  if (cam && canvas) startDetectionOverlay(cam, canvas);
  if (repaint && $("#view-live")?.classList.contains("active")) paintLiveWorkspace(liveCamsAll);
}

function applyCadence(id) {
  const map = { FAST: 400, BALANCED: 1000, DEEP: 1000 };
  intelState.cadence = id;
  intelState.overlayPollMs = map[id] || 1000;
  $$("[data-cadence]").forEach((x) => {
    const on = x.dataset.cadence === id;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  const cam = livePlayer?.id;
  const canvas = $("#live-overlay");
  if (cam && canvas) startDetectionOverlay(cam, canvas);
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

$$("[data-cadence]").forEach((b) => b.addEventListener("click", () => applyCadence(b.dataset.cadence)));

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
    "overview-30": { wall: 30, mode: "video", view: "live", domain: "government" },
    "overview-50": { wall: 50, mode: "video", view: "live", domain: "fifty" },
    "government": { wall: 30, mode: "video", view: "live", domain: "government" },
    "intelligence-demo": { wall: 2, mode: "full", view: "intelligence", domain: "intelligence" },
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
  /* The destination loader paints once after wall/domain/mode are all set.
   * Repainting here used the previous domain, scheduled a first WHEP fleet,
   * and then let show() rebuild the DOM underneath it. */
  applyIntelMode(spec.mode, false);
  if (spec.domain) liveDomain = spec.domain;
  $$("[data-live-domain]").forEach((x) => {
    const on = x.dataset.liveDomain === liveDomain;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  show(spec.view);
  /* show() already invokes the destination loader. Starting the live loader a
   * second time races two async GIS requests: each rebuilds the wall and
   * closes the other's peer connections, leaving decoded last frames labelled
   * CONNECTING and a misleading 0/30 counter. */
}));

async function trackEntity(plate, alert) {
  if (!plate) { toast("No plate on this alert", true); return; }
  try {
    const card = await api(`/command/track/${encodeURIComponent(plate)}`);
    lastTrackCard = card;
    paintTrackPanel(card, alert);
    paintIntelHops(card, alert);
    if (intelMap) intelMap.focusTarget(card.hops || []);
    if (map1) map1.focusTarget(card.hops || []);
    show("investigate");
    if ($("#q-plate")) $("#q-plate").value = plate;
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
    body.append(el("div", { class: "track-hop hero-hop",
      onclick: () => hop.observation_id && jumpObservation(hop.observation_id, hop.camera_id) },
      el("div", { class: "rail" }),
      el("div", {},
        el("div", { class: "role", text: hop.role }),
        el("div", { class: "mono", text: hop.camera_id || "—" }),
        el("div", { class: "muted", text: `${hop.signal || ""} · ${hop.t || ""}` }),
        hop.observation_id ? el("button", { class: "ghost", onclick: (e) => {
          e.stopPropagation();
          jumpObservation(hop.observation_id, hop.camera_id);
        } }, "JUMP TO EVENT") : null)));
  }
  const summary = trackingTransitionSummary(card.transitions || []);
  for (const t of summary.visible) {
    const verdict = t.verdict || t.result;
    body.append(el("div", { class: "notice " + (verdict === "CONTRADICTION" ? "bad" : "neutral") },
      el("strong", { class: `verdict-${verdict}`, text: verdict }),
      `  ${t.from_camera} → ${t.to_camera}`,
      el("div", { class: "muted", text:
        transitionMetrics(t) }),
      t.operator_reason || t.reason
        ? el("div", { text: t.operator_reason || t.reason }) : null));
  }
  if (summary.hidden) body.append(el("div", { class: "section-note", text:
    `Showing ${summary.visible.length} distinct transition decisions; ${summary.hidden} more remain in the case API.` }));
  if (alert?.camera_id) {
    body.append(el("div", { class: "live-actions", style: "display:flex" },
      el("button", { class: "primary", onclick: () => jumpAlert(alert) }, "VIEW VIDEO")));
  }
}

function paintIntelHops(card, alert) {
  const box = $("#intel-hops");
  const ev = $("#intel-evidence");
  if (!box) return;
  clear(box);
  box.append(el("div", { class: "sid", text:
    `ALERT · ${card.identifier || ""} · ${card.subject || card.target}` }));
  for (const hop of card.hops || []) {
    const gap = hop.elapsed_label
      ? el("div", { class: "hop-gap", text: `↓ ${hop.elapsed_label}` })
      : null;
    if (gap) box.append(gap);
    box.append(el("div", { class: "hero-hop",
      onclick: () => hop.observation_id && jumpObservation(hop.observation_id, hop.camera_id) },
      el("div", { class: "rail" }),
      el("div", {},
        el("div", { class: "role", text: hop.role }),
        el("div", { class: "mono", text: hop.t || "—" }),
        el("div", { class: "mono", text: hop.camera_id || "—" }),
        el("div", { text: hop.signal || hop.location || "" }),
        hop.confidence != null
          ? el("div", { class: "muted", text: `confidence ${hop.confidence}` }) : null,
        hop.distance_km != null
          ? el("div", { class: "muted", text: `${hop.distance_km} km` }) : null)));
  }
  const summary = trackingTransitionSummary(card.transitions || []);
  for (const t of summary.visible) {
    box.append(el("div", { class: "notice " + ((t.verdict || t.result) === "CONTRADICTION" ? "bad" : "neutral") },
      `${t.verdict || t.result}: ${t.from_camera} → ${t.to_camera} · ${transitionMetrics(t)}`));
  }
  if (summary.hidden) box.append(el("div", { class: "section-note", text:
    `Showing ${summary.visible.length} distinct transition decisions; ${summary.hidden} more remain in the case API.` }));
  if (ev) {
    clear(ev);
    ev.append(el("div", { class: "sid", text: "EVIDENCE" }),
      el("div", { text: alert?.plate || card.identifier || "—" }),
      el("div", { class: "muted", text: alert?.match_reason || card.label || "" }));
    if (alert?.observation_id) {
      ev.append(el("button", { class: "ghost", onclick: () => jumpObservation(alert.observation_id, alert.camera_id) },
        "OPEN EVIDENCE"));
    } else {
      ev.append(el("div", { class: "section-note", text:
        "Manual tracking query — select a stored observation before opening evidence." }));
    }
  }
}

function transitionMetrics(t) {
  const km = Number(t.distance_km);
  const measuredMinimum = Number(t.expected_minimum_s);
  const minimum = Number.isFinite(measuredMinimum) && measuredMinimum > 0
    ? measuredMinimum
    : (Number.isFinite(km) && km > 0 ? Math.round(km / 200 * 3600 * 10) / 10 : null);
  return `distance ${Number.isFinite(km) ? km : "?"} km · `
    + `elapsed ${t.elapsed_s ?? "?"}s · minimum plausible travel `
    + `${minimum ?? "not calibrated"}${minimum == null ? "" : "s"}`;
}

function trackingTransitionSummary(transitions) {
  /* One busy camera can emit many observations for the same next camera.
   * Keep the complete list in the API, but turn the command surface into a
   * decision aid: one representative per verdict/camera pair, with impossible
   * transitions first and the strongest remaining leads after them. */
  const distinct = new Map();
  for (const t of transitions || []) {
    const verdict = t.verdict || t.result || "CANDIDATE";
    const key = `${verdict}:${t.from_camera || "?"}->${t.to_camera || "?"}`;
    const old = distinct.get(key);
    if (!old || Number(t.confidence || 0) > Number(old.confidence || 0)
        || Number(t.implied_speed_kmh || 0) > Number(old.implied_speed_kmh || 0)) {
      distinct.set(key, t);
    }
  }
  const ranked = [...distinct.values()].sort((a, b) => {
    const ac = (a.verdict || a.result) === "CONTRADICTION" ? 0 : 1;
    const bc = (b.verdict || b.result) === "CONTRADICTION" ? 0 : 1;
    return ac - bc || Number(b.confidence || 0) - Number(a.confidence || 0);
  });
  const visible = ranked.slice(0, 6);
  return { visible, hidden: Math.max(0, ranked.length - visible.length) };
}

async function jumpObservation(oid, cameraId) {
  try {
    const j = await api(`/command/jump/${encodeURIComponent(oid)}`);
    const dlg = $("#jump-dialog");
    const eventEl = $("#jump-event-time");
    const liveEl = $("#jump-live-pos");
    const noteEl = $("#jump-note");
    if (eventEl) eventEl.textContent = `EVENT TIMESTAMP: ${j.event_timestamp || j.event_time || "—"}`;
    if (liveEl) {
      liveEl.textContent = j.playback?.seekable
        ? `REPLAY POSITION: seek to ${j.pts_s ?? "—"}s on own-feed recording`
        : `CURRENT LIVE POSITION: live WHEP cannot seek to this event`;
    }
    if (noteEl) noteEl.textContent = j.note || j.playback?.note || "";
    const openCam = async () => {
      show("live");
      openLive($(`.live-tile[data-camera="${CSS.escape(j.camera_id)}"]`) || el("div"), j.camera_id);
      if (j.seekable && j.pts_s != null) {
        try {
          await api(`/command/cameras/${encodeURIComponent(j.camera_id)}/seek?pts_s=${encodeURIComponent(j.pts_s)}`,
            { method: "POST" });
        } catch { /* view may not be started yet */ }
      }
    };
    if (dlg?.showModal) {
      dlg.returnValue = "";
      dlg.showModal();
      dlg.addEventListener("close", () => {
        if (dlg.returnValue === "open") openCam();
      }, { once: true });
    } else {
      toast(`EVENT ${j.event_time || ""} · live is not this timestamp`);
      await openCam();
    }
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
  const hud = el("div", { class: "ai-hud", id: "compare-hud",
    text: "AI NOT MEASURED · no persisted detection read yet · overlay 1 Hz" });
  right.append(canvas, hud);
  wrap.append(left, right);
  stage.append(wrap);
  const src = videoOrImg;
  const paint = () => {
    if (!intelState.compare) return;
    const w = src.clientWidth || 320, h = src.clientHeight || 180;
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    try { ctx.drawImage(src, 0, 0, w, h); } catch { /* not ready */ }
    const n = overlayState?.tracks?.size || 0;
    /* The analytics switch being on is not evidence that anything is being
     * analysed. This pane is only allowed to call AI active when the store has
     * actually returned persisted detections for this camera. */
    const ai = !intelState.analytics
      ? "AI OFF"
      : n > 0
        ? "AI ACTIVE · persisted detections"
        : overlayState?.metaSeen
          ? "AI REQUESTED · no persisted detection for this camera"
          : "AI REQUESTED · no metadata read yet";
    hud.textContent = `${ai} · cadence ${intelState.cadence} · detector FPS NOT_MEASURED · `
      + `overlay ${intelState.overlayPollMs} ms · objects ${n} · tracks ${n}`;
    requestAnimationFrame(paint);
  };
  requestAnimationFrame(paint);
}

$$("[data-product]").forEach((b) => b.addEventListener("click", () => {
  const id = b.dataset.product;
  const dest = {
    operations: "live",
    intelligence: "intelligence",
    investigation: "investigate",
    system: "system",
  }[id];
  if (id === "operations") liveDomain = liveDomain || "government";
  if (id === "intelligence") {
    liveDomain = "intelligence";
    applyIntelMode("full");
  }
  show(dest);
}));

$$("[data-live-domain]").forEach((b) => b.addEventListener("click", () => {
  liveDomain = b.dataset.liveDomain;
  $$("[data-live-domain]").forEach((x) => {
    const on = x.dataset.liveDomain === liveDomain;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  if (liveDomain === "intelligence") {
    show("intelligence");
    return;
  }
  if (liveDomain === "fifty") liveWallMode = 50;
  /* The government catalogue is exactly thirty indexed cameras. Carrying a
   * larger wall size over from the 50-slot overview would pad it with CONTROL
   * slots and misreport how many government cameras this process holds. */
  if (liveDomain === "government") liveWallMode = 30;
  $$("[data-live-wall]").forEach((x) => {
    const on = Number(x.dataset.liveWall) === liveWallMode;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  show("live");
}));

$$("[data-scene-filter]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-scene-filter]").forEach((x) => {
    x.classList.remove("on"); x.setAttribute("aria-pressed", "false");
  });
  b.classList.add("on"); b.setAttribute("aria-pressed", "true");
  const f = b.dataset.sceneFilter;
  if (f === "vehicles") applyIntelMode("vehicles");
  else if (f === "people") applyIntelMode("people");
  else applyIntelMode(intelState.mode === "video" ? "full" : intelState.mode);
}));

let intelWlCat = "";
$$("[data-wl-cat]").forEach((b) => b.addEventListener("click", () => {
  intelWlCat = b.dataset.wlCat || "";
  $$("[data-wl-cat]").forEach((x) => x.classList.toggle("on", x === b));
  loaders.intelligence?.();
}));

$("#intel-open-a")?.addEventListener("click", () => {
  show("live");
  liveDomain = "intelligence";
  openLive($(`.live-tile[data-camera="OWN-PEOPLE"]`) || el("div"), "OWN-PEOPLE");
});
$("#intel-open-b")?.addEventListener("click", () => {
  show("live");
  liveDomain = "intelligence";
  openLive($(`.live-tile[data-camera="OWN-TRAFFIC"]`) || el("div"), "OWN-TRAFFIC");
});
$("#intel-plate-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const plate = $("#intel-plate")?.value.trim();
  if (!plate) return;
  show("investigate");
  if ($("#q-plate")) $("#q-plate").value = plate;
  $("#search-form")?.requestSubmit?.();
});
$("#intel-track-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const plate = $("#intel-track-q")?.value.trim();
  if (plate) trackEntity(plate, { plate });
});
$("#intel-focus")?.addEventListener("click", () => {
  if (lastTrackCard && intelMap) intelMap.focusTarget(lastTrackCard.hops || []);
  else toast("Track a target first");
});

async function paintIntelStage(id, host) {
  if (!host) return;
  if (host._intelTimer) { clearInterval(host._intelTimer); host._intelTimer = null; }
  clear(host);
  const img = el("img", { alt: id });
  const canvas = el("canvas", { class: "live-overlay" });
  const badge = el("div", { class: "pane-label",
    text: `${id} · OWN FEED · FILE REPLAY · not a live camera` });
  host.append(img, canvas, badge);
  const tick = async () => {
    try {
      const snap = await sharedSnapshot(id);
      if (snap?.url) img.src = snap.url;
    } catch { /* waiting for first file frame */ }
    try {
      const res = await api(`/command/cameras/${encodeURIComponent(id)}/boxes?overlay=full&people=true&vehicles=true&anpr=true`);
      const draw = () => {
        canvas.width = host.clientWidth || 480;
        canvas.height = host.clientHeight || 220;
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const ts = res.boxes?.[0]?.pts_s;
        for (const m of res.boxes || []) {
          const bbox = m.bbox || m.box;
          if (!bbox || bbox.length < 4) continue;
          const [x1, y1, x2, y2] = bbox;
          const norm = Math.max(x1, y1, x2, y2) <= 1.5;
          const rx1 = norm ? x1 * canvas.width : x1;
          const ry1 = norm ? y1 * canvas.height : y1;
          const rx2 = norm ? x2 * canvas.width : x2;
          const ry2 = norm ? y2 * canvas.height : y2;
          ctx.strokeStyle = (m.object_type || "") === "person" ? "#3ec8dc" : "#f1c40f";
          ctx.lineWidth = 2;
          ctx.strokeRect(rx1, ry1, Math.max(1, rx2 - rx1), Math.max(1, ry2 - ry1));
          const label = [m.track_id, m.object_type,
                         m.confidence != null ? Number(m.confidence).toFixed(2) : "",
                         m.plate].filter(Boolean).join(" · ");
          if (label) {
            ctx.fillStyle = "rgba(0,0,0,0.55)";
            ctx.fillRect(rx1, Math.max(0, ry1 - 16), 8 * label.length + 8, 14);
            ctx.fillStyle = "#fff";
            ctx.font = "11px ui-monospace, monospace";
            ctx.fillText(label, rx1 + 4, Math.max(12, ry1 - 4));
          }
        }
        if (ts != null) {
          ctx.fillStyle = "rgba(0,0,0,0.45)";
          ctx.fillRect(8, canvas.height - 22, 120, 16);
          ctx.fillStyle = "#ddd";
          ctx.font = "11px ui-monospace, monospace";
          ctx.fillText(`pts ${Number(ts).toFixed(2)}s`, 12, canvas.height - 10);
        }
      };
      if (img.complete) draw();
      else img.addEventListener("load", draw, { once: true });
    } catch { /* no stored detections — never invented */ }
  };
  await tick();
  host._intelTimer = setInterval(tick, 450);
}

loaders.intelligence = async () => {
  applyIntelMode("full");
  try {
    const cmd = await api("/command/summary");
    paintIntelCommand(cmd);
    paintCommandStatus(cmd, null);
  } catch { /* KPIs stay NOT_MEASURED */ }
  if (!intelMap && $("#intel-map")) {
    intelMap = new MapView($("#intel-map"), {
      ...(state.mapOpts || {}),
      onSelect: (hit) => {
        if (hit?.data?.observation_id) jumpObservation(hit.data.observation_id, hit.id);
        else if (hit?.id) {
          show("live");
          openLive($(`.live-tile[data-camera="${CSS.escape(hit.id)}"]`) || el("div"), hit.id);
        }
      },
    });
  }
  // Start the two participant feed previews together. Serial first-frame
  // capture made the second panel look broken for several seconds even though
  // its relay was healthy; each preview is already isolated per camera.
  await Promise.all([
    paintIntelStage("OWN-PEOPLE", $("#intel-stage-a")),
    paintIntelStage("OWN-TRAFFIC", $("#intel-stage-b")),
  ]);
  const scene = $("#intel-scene");
  if (scene) {
    clear(scene);
    let a = {}, b = {};
    try { a = await api("/command/cameras/OWN-PEOPLE/scene"); } catch { a = {}; }
    try { b = await api("/command/cameras/OWN-TRAFFIC/scene"); } catch { b = {}; }
    const sum = (k) => Number(a[k] || 0) + Number(b[k] || 0);
    const cls = (k) => Number((a.classes || {})[k] || 0) + Number((b.classes || {})[k] || 0);
    const kpis = [
      ["People", sum("people")],
      ["Vehicles", sum("vehicles")],
      ["Tracked", sum("tracked")],
      ["Plates", sum("plates")],
      ["Watchlist", sum("watchlist")],
      ["Alerts", sum("alerts")],
      ["Cars", cls("cars")],
      ["Buses", cls("buses")],
      ["Trucks", cls("trucks")],
      ["Motorcycles", cls("motorcycles")],
      ["Persons", cls("persons")],
    ];
    for (const [lab, n] of kpis) {
      scene.append(el("div", { class: "kpi" },
        el("b", { text: String(n) }), el("span", { text: lab })));
    }
  }
  const platesBox = $("#intel-plates");
  if (platesBox) {
    clear(platesBox);
    try {
      const res = await api("/command/plates?limit=24");
      if (!(res.plates || []).length) {
        platesBox.append(el("div", { class: "empty", text: "No plate reads in this store." }));
      }
      for (const p of res.plates || []) {
        platesBox.append(el("div", { class: "alert-card" },
          el("div", { class: "pl", text: p.plate || "—" }),
          el("div", { class: "meta", text:
            `${p.camera_id || "—"} · ${p.t_norm || p.t || ""} · ${p.location || ""} · ${p.vehicle_class || ""} · ${p.confidence ?? ""}` }),
          el("div", { class: "actions" },
            el("button", { class: "ghost", onclick: () => {
              show("live");
              openLive($(`.live-tile[data-camera="${CSS.escape(p.camera_id)}"]`) || el("div"), p.camera_id);
            } }, "OPEN VIDEO"),
            el("button", { class: "ghost", onclick: () => trackEntity(p.plate, p) }, "TRACK VEHICLE"),
            el("button", { class: "ghost", onclick: () => { show("map"); trackEntity(p.plate, p); } }, "SHOW GIS"),
            p.observation_id
              ? el("button", { class: "ghost", onclick: () => jumpObservation(p.observation_id, p.camera_id) },
                  "OPEN EVIDENCE") : null,
            el("button", { class: "ghost", onclick: () => trackEntity(p.plate, p) }, "SHOW HISTORY"))));
      }
    } catch (err) {
      platesBox.append(el("div", { class: "notice bad", text: `${err.code}: ${err.message}` }));
    }
  }
  const wlBox = $("#intel-watchlist");
  if (wlBox) {
    clear(wlBox);
    try {
      const res = await api(`/alerts?status=&limit=50`);
      let rows = res.alerts || [];
      if (intelWlCat) rows = rows.filter((a) => a.category === intelWlCat);
      if (!rows.length) wlBox.append(el("div", { class: "empty", text: "No watchlist matches in this filter." }));
      for (const a of rows.slice(0, 16)) {
        wlBox.append(el("div", { class: "alert-card" },
          el("div", { class: "pl", text: "WATCHLIST MATCH" }),
          el("div", { class: "meta", text:
            `${a.plate || a.entity || "—"} · ${String(a.category || "").replaceAll("_", " ")} · ${a.camera_id || "—"}` }),
          el("div", { class: "tm", text:
            `${fmtAlertClock(a)} · ${a.priority || ""} · ${a.status || ""} · ${a.confidence != null ? (Number(a.confidence) * 100).toFixed(1) + "%" : ""}` }),
          el("div", { class: "actions" },
            el("button", { class: "ghost", onclick: () => jumpAlert(a) }, "VIEW VIDEO"),
            el("button", { class: "ghost", onclick: () => trackEntity(a.plate, a) }, "TRACK VEHICLE"),
            el("button", { class: "ghost", onclick: () => routeAlert(a) }, "ROUTE"),
            el("button", { class: "ghost", onclick: () => { show("map"); } }, "GIS"),
            a.status === "OPEN" ? el("button", { class: "ghost", onclick: async () => {
              await api(`/alerts/${encodeURIComponent(a.alert_id)}/acknowledge`, { method: "POST" });
              loaders.intelligence();
            } }, "ACKNOWLEDGE") : null,
            el("button", { class: "ghost", onclick: async () => {
              await api(`/alerts/${encodeURIComponent(a.alert_id)}/investigate`, { method: "POST" });
              show("investigate");
            } }, "INVESTIGATE"))));
      }
    } catch (err) {
      wlBox.append(el("div", { class: "notice bad", text: `${err.code}: ${err.message}` }));
    }
  }
};

/* ─── start ──────────────────────────────────────────────────────────────── */
(async function start() {
  await identify();
  // The operational default is the full government wall. Keep the controls
  // and ARIA state aligned with the actual initial variables so a reload does
  // not visually claim 12/ALL while rendering 30/GOVERNMENT.
  $$('[data-live-wall]').forEach((button) => {
    const active = Number(button.dataset.liveWall) === liveWallMode;
    button.classList.toggle('on', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  $$('[data-live-domain]').forEach((button) => {
    const active = button.dataset.liveDomain === liveDomain;
    button.classList.toggle('on', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
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

/* ─── Model 1 · camera onboarding ────────────────────────────────────────── */
/* The mandatory model's named deliverable is "bulk AND manual camera-onboarding
 * demonstration", and until now all three registry endpoints were reachable
 * only with a shell. A registry portal nobody can onboard through is not a
 * registry portal, and an assessor cannot be asked to take curl on trust.
 *
 * The refusals matter as much as the successes here: an import applies wholly
 * or not at all, and the server names the offending row. Collapsing that into
 * "import failed" would throw away the only thing that makes a bad spreadsheet
 * fixable, so the row number and reason are shown verbatim. */

const OB_FIELDS = {
  "#ob-camera-id": "camera_id", "#ob-name": "name",
  "#ob-department": "department", "#ob-district": "district",
  "#ob-lat": "lat", "#ob-lon": "lon", "#ob-vms": "vms",
  "#ob-vendor": "vendor", "#ob-camera-type": "camera_type",
  "#ob-storage": "storage_location", "#ob-retention": "retention_days",
  "#ob-rtsp": "rtsp_url",
};
const OB_NUMERIC = new Set(["lat", "lon", "retention_days"]);

function obResult(node, ok, headline, detail = "") {
  node.className = `onboard-result ${ok ? "ok" : "bad"}`;
  node.replaceChildren(
    el("b", { text: headline }),
    ...(detail ? [el("div", { class: "onboard-detail", text: detail })] : []));
}

function obReadManual() {
  const body = {};
  for (const [sel, field] of Object.entries(OB_FIELDS)) {
    const raw = ($(sel)?.value || "").trim();
    if (!raw) continue;
    if (OB_NUMERIC.has(field)) {
      const n = Number(raw);
      if (!Number.isFinite(n)) throw new Error(`${field} must be a number`);
      body[field] = field === "retention_days" ? Math.round(n) : n;
    } else {
      body[field] = raw;
    }
  }
  return body;
}

/** Say what the server actually said.
 *
 * The import refuses a batch by raising one {code, message} — there is no
 * per-row error array to iterate, and the message already carries the row
 * number ("row 3: MC-0002 is already onboarded"). It reaches us through
 * api()'s ApiError, so the only job here is the success shape. */
function obReport(node, res, { dry }) {
  const created = res.created ?? 0;
  const updated = res.updated ?? 0;
  const headline = dry
    ? `Valid — nothing was written. ${created} row(s) would be onboarded` +
      (updated ? `, ${updated} amended.` : ".")
    : `Onboarded ${created} camera(s)` + (updated ? `, amended ${updated}.` : ".");
  obResult(node, true, headline, res.note || "");
  return true;
}

function obShowPane(which) {
  for (const b of $$("[data-onboard]")) {
    const on = b.dataset.onboard === which;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", String(on));
  }
  for (const id of ["manual", "bulk", "export"]) {
    const pane = $(`#onboard-${id}`);
    if (pane) pane.hidden = id !== which;
  }
}

$("#btn-onboard-toggle")?.addEventListener("click", () => {
  const panel = $("#onboard-panel");
  const open = panel.hidden;
  panel.hidden = !open;
  $("#btn-onboard-toggle").setAttribute("aria-expanded", String(open));
  if (open) {
    obShowPane("manual");
    $("#ob-camera-id")?.focus();
    // Offer the departments already in the estate rather than making an
    // operator retype one and create a near-duplicate.
    const seen = [...new Set((state.cameras || [])
      .map((c) => c.department).filter(Boolean))].sort();
    $("#ob-departments")?.replaceChildren(
      ...seen.map((d) => el("option", { value: d })));
  }
});

for (const b of $$("[data-onboard]")) {
  b.addEventListener("click", () => obShowPane(b.dataset.onboard));
}

async function obSubmitManual(dry) {
  const node = $("#onboard-result");
  let cam;
  try {
    cam = obReadManual();
  } catch (err) {
    obResult(node, false, err.message);
    return;
  }
  if (!cam.camera_id) {
    obResult(node, false, "A camera id is required.");
    $("#ob-camera-id")?.focus();
    return;
  }
  try {
    const res = await api("/registry/cameras/import", {
      method: "POST",
      body: JSON.stringify({
        // dry_run is a field on ImportRequest, not a query parameter. Passing
        // it in the query string is silently ignored, and "Validate only"
        // then onboards for real.
        dry_run: !!dry,
        update_existing: !!$("#ob-update-existing")?.checked,
        cameras: [cam],
      }),
    });
    if (obReport(node, res, { dry }) && !dry) {
      toast(`Onboarded ${cam.camera_id}`);
      loaders.cameras?.();
    }
  } catch (err) {
    obResult(node, false, `${err.code}: ${err.message}`);
  }
}

$("#onboard-manual")?.addEventListener("submit", (e) => {
  e.preventDefault();
  obSubmitManual(false);
});
$("#btn-ob-dry")?.addEventListener("click", () => obSubmitManual(true));

$("#ob-file")?.addEventListener("change", async (e) => {
  const f = e.target.files?.[0];
  if (!f) return;
  $("#ob-csv").value = await f.text();
  obResult($("#onboard-result"), true,
    `Loaded ${f.name} — validate it before importing.`);
});

$("#btn-ob-sample")?.addEventListener("click", () => {
  $("#ob-csv").value = [
    "camera_id,name,department,district,lat,lon,vms,retention_days",
    "MC-0002,Riverfront east,Municipal Corporation,Ahmedabad,23.02,72.57,Milestone,15",
    "RTO-0007,Testing track,RTO,Rajkot,,,,",
  ].join("\n");
});

async function obSubmitBulk(dry) {
  const node = $("#onboard-result");
  const csv = ($("#ob-csv")?.value || "").trim();
  if (!csv) {
    obResult(node, false, "Paste a CSV, or choose a file.");
    return;
  }
  const params = new URLSearchParams();
  if (dry) params.set("dry_run", "true");
  if ($("#ob-bulk-update")?.checked) params.set("update_existing", "true");
  const q = params.toString() ? `?${params}` : "";
  try {
    const res = await api(`/registry/cameras/import.csv${q}`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: csv,
    });
    if (obReport(node, res, { dry }) && !dry) {
      toast("Bulk import applied");
      loaders.cameras?.();
    }
  } catch (err) {
    obResult(node, false, `${err.code}: ${err.message}`);
  }
}

$("#btn-ob-bulk-dry")?.addEventListener("click", () => obSubmitBulk(true));
$("#btn-ob-bulk")?.addEventListener("click", () => obSubmitBulk(false));

$("#btn-ob-export")?.addEventListener("click", async (e) => {
  // A plain <a href> would arrive unauthenticated and come back 401 — the
  // ANPR report download already learned that the hard way.
  e.target.disabled = true;
  try {
    const res = await fetch("/registry/cameras/export.csv",
                            { headers: authHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: "camera_metadata.csv" });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    obResult($("#onboard-result"), true, "Registry exported.");
  } catch (err) {
    obResult($("#onboard-result"), false, `Export failed: ${err.message}`);
  } finally {
    e.target.disabled = false;
  }
});
