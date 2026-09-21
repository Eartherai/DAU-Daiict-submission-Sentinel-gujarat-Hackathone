/* Canvas map renderer.
 *
 * Written rather than pulled in, for one reason that outranks the rest: the
 * deployment target may have no route to the internet. A mapping library that
 * fetches raster tiles from a public host degrades, on a government network,
 * into a grey rectangle — and it does so silently, at the moment an operator
 * most needs the map. So the base layer here is a graticule and a scale bar
 * derived from the data itself, and a raster tile layer is an optional extra
 * that is off unless a deployment supplies its own tile server.
 *
 * The second reason is control. Clustering, leg-kind styling and the
 * distinction between "observed" and "could not observe" are the substance of
 * this map, not decoration on top of a generic one.
 *
 * Projection is Web Mercator, matching the server-side clustering exactly so a
 * cluster the server computed lands where the client draws it.
 */

const TILE = 256;

export function project(lat, lon, zoom) {
  const scale = TILE * Math.pow(2, zoom);
  const x = ((lon + 180) / 360) * scale;
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const s = Math.sin((clamped * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * scale;
  return [x, y];
}

export function unproject(x, y, zoom) {
  const scale = TILE * Math.pow(2, zoom);
  const lon = (x / scale) * 360 - 180;
  const n = Math.PI - 2 * Math.PI * (y / scale);
  const lat = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  return [lat, lon];
}

const LEG_STYLE = {
  OBSERVED:      { dash: [],       width: 3,   token: "--confirmed" },
  COVERAGE_GAP:  { dash: [2, 5],   width: 2,   token: "--unknown" },
  UNOBSERVED:    { dash: [8, 5],   width: 2,   token: "--verify" },
  CONTRADICTION: { dash: [10, 4],  width: 3.5, token: "--conflict" },
};

const STATE_TOKEN = {
  STREAMING: "--confirmed", OK: "--confirmed",
  DEGRADED: "--verify", RECONNECTING: "--verify",
  DOWN: "--conflict", OPEN_FAILED: "--conflict",
  UNKNOWN: "--unknown",
};

const GRADE_TOKEN = {
  GOOD: "--confirmed", DEGRADED: "--verify",
  UNSUITABLE: "--conflict", UNKNOWN: "--unknown",
};

/* How far a position can be trusted, in metres.
 *
 * Drawn, not merely recorded. A camera placed from its name — "Paldi Circle" —
 * is near the right junction; one placed from a town name is somewhere in that
 * town. Rendering both as the same dot quietly upgrades a guess into a fact,
 * and an investigator reading a corridor off this map deserves to see which is
 * which. The radius is the uncertainty, to scale. */
const PRECISION_METRES = {
  LANDMARK: 150, LOCALITY: 1500, CITY: 6000,
};

/* Raster basemap.
 *
 * Off unless a deployment configures a tile URL. The system must run on a
 * government network with no route to the internet, so a basemap is an
 * enhancement and never a dependency: with no tiles the graticule and scale bar
 * still give the eye a frame of reference, and every marker is still where it
 * belongs.
 *
 * Tiles are cached in memory, bounded, and never blocked on — a tile that has
 * not arrived simply is not drawn. */
class TileLayer {
  constructor(template, { maxTiles = 256, attribution = "" } = {}) {
    this.template = template;
    this.attribution = attribution;
    this.maxTiles = maxTiles;
    this.tiles = new Map();       // "z/x/y" -> HTMLImageElement | "pending" | "failed"
    this.onLoad = () => {};
    this.failures = 0;
  }

  get(z, x, y) {
    const key = `${z}/${x}/${y}`;
    const have = this.tiles.get(key);
    if (have) return have instanceof Image ? have : null;

    // Too many consecutive failures means the host is unreachable — a
    // government network with no egress, most likely. Stop asking.
    if (this.failures > 24) return null;

    const img = new Image();
    // Painted, never exported. Forcing CORS made OSM tiles fail on hosts that
    // omit Access-Control-Allow-Origin, which is how the estate map looked empty.
    this.tiles.set(key, "pending");
    img.onload = () => {
      this.tiles.set(key, img);
      this.failures = 0;
      if (this.tiles.size > this.maxTiles) {
        const oldest = this.tiles.keys().next().value;
        this.tiles.delete(oldest);
      }
      this.onLoad();
    };
    img.onerror = () => {
      this.tiles.set(key, "failed");
      this.failures += 1;
    };
    img.src = this.template
      .replace("{z}", z).replace("{x}", x).replace("{y}", y)
      .replace("{s}", "abc"[(x + y) % 3]);
    return null;
  }

  get unreachable() { return this.failures > 24; }
}

let _googleMaps = null;

function hopsToTrajectory(hops) {
  const nodes = (hops || []).filter((h) => h.lat != null && h.lon != null);
  const legs = [];
  for (let i = 1; i < nodes.length; i++) {
    const a = nodes[i - 1], b = nodes[i];
    const kind = (b.verdict === "CONTRADICTION" || b.kind === "CONTRADICTION")
      ? "CONTRADICTION" : "OBSERVED";
    legs.push({
      from_lat: a.lat, from_lon: a.lon,
      to_lat: b.lat, to_lon: b.lon,
      kind,
      elapsed: b.elapsed_label || b.elapsed,
      distance_km: b.distance_km,
    });
  }
  return { nodes, legs };
}

function loadGoogleMaps(loaderUrl) {
  if (window.google?.maps?.Map) return Promise.resolve(window.google.maps);
  if (_googleMaps) return _googleMaps;
  const base = loaderUrl || "/maps/google-api";
  _googleMaps = new Promise((resolve, reject) => {
    const cb = "__saakshyaGmapsReady";
    window[cb] = () => {
      try { delete window[cb]; } catch { /* ignore */ }
      resolve(window.google.maps);
    };
    const s = document.createElement("script");
    const join = base.includes("?") ? "&" : "?";
    s.src = `${base}${join}callback=${cb}`;
    s.async = true;
    s.onerror = () => reject(new Error("Google Maps script failed to load"));
    document.head.appendChild(s);
  });
  return _googleMaps;
}

export class MapView {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.googleLoader = opts.googleLoader || "";
    this.googleEnabled = Boolean(this.googleLoader);
    this._tileFallback = {
      template: opts.tileTemplate || "",
      attribution: opts.attribution || "",
    };
    this.tiles = (!this.googleEnabled && opts.tileTemplate)
      ? new TileLayer(opts.tileTemplate, { attribution: opts.attribution })
      : null;
    if (this.tiles) this.tiles.onLoad = () => this._scheduleDraw();
    this.gmap = null;
    this._googleReady = false;
    this.centre = opts.centre || [23.05, 72.62];
    this.zoom = opts.zoom ?? 11;
    this.layers = {
      cameras: [], alerts: [], coverage: [], trajectory: null, observations: [],
    };
    this.mode = "health";                 // health | capability | tier
    this.show = { alerts: true, coverage: false, labels: false };
    this.selected = null;
    this.hover = null;
    this._pendingFit = null;
    this._lastFit = null;
    this.onSelect = opts.onSelect || (() => {});
    this.onViewport = opts.onViewport || (() => {});
    this._hit = [];
    this._bind();
    this.resize();
    if (this.googleEnabled) this._initGoogle();
  }

  setRasterBasemap(template, attribution) {
    if (!template || this._googleReady) return;
    this.tiles = new TileLayer(template, { attribution: attribution || "" });
    this.tiles.onLoad = () => this._scheduleDraw();
    this._scheduleDraw();
  }

  /* ── interaction ────────────────────────────────────────────────────── */
  _bind() {
    const c = this.canvas;
    let dragging = false, last = null, moved = 0;

    /* Pointer capture is a convenience for dragging, not a precondition for
     * selecting. It throws when the pointer is not one the element can capture
     * — and the release below then throws too, aborting the handler *before*
     * the hit test runs, so clicking a camera silently stops working. Guarding
     * both keeps selection working wherever capture is unavailable. */
    c.addEventListener("pointerdown", (e) => {
      dragging = true; moved = 0; last = [e.offsetX, e.offsetY];
      try { c.setPointerCapture(e.pointerId); } catch { /* not capturable */ }
    });
    c.addEventListener("pointermove", (e) => {
      if (dragging) {
        const dx = e.offsetX - last[0], dy = e.offsetY - last[1];
        moved += Math.abs(dx) + Math.abs(dy);
        last = [e.offsetX, e.offsetY];
        this._panPixels(-dx, -dy);
      } else {
        const hit = this._pick(e.offsetX, e.offsetY);
        if ((hit && hit.id) !== (this.hover && this.hover.id)) {
          this.hover = hit;
          this.draw();
        }
      }
    });
    c.addEventListener("pointerup", (e) => {
      dragging = false;
      try { c.releasePointerCapture(e.pointerId); } catch { /* never captured */ }
      // A drag is not a click. Ten pixels of slop keeps a shaky hand from
      // deselecting the camera the operator is reading.
      if (moved < 10) {
        const hit = this._pick(e.offsetX, e.offsetY);
        this.selected = hit ? hit.id : null;
        this.draw();
        this.onSelect(hit);
      } else {
        this.onViewport(this.bbox());
      }
    });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const before = this._screenToLatLon(e.offsetX, e.offsetY);
      const step = this._googleReady || this.googleEnabled ? 1 : 0.4;
      this.zoom = Math.max(4, Math.min(19, this.zoom - Math.sign(e.deltaY) * step));
      if (this._googleReady || this.googleEnabled) this.zoom = Math.round(this.zoom);
      const after = this._screenToLatLon(e.offsetX, e.offsetY);
      // Keep the point under the cursor fixed while zooming.
      this.centre = [this.centre[0] + (before[0] - after[0]),
                     this.centre[1] + (before[1] - after[1])];
      this.draw();
      this.onViewport(this.bbox());
    }, { passive: false });

    // A ResizeObserver rather than a window resize listener. The canvas sits in
    // a flex/grid layout inside a view that can be hidden, so its box changes
    // for reasons the window never hears about — first paint, a view becoming
    // visible, a column being resized. Listening to the window meant the map
    // measured itself at 1x1 during layout and never measured again.
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(this.canvas);
  }

  _panPixels(dx, dy) {
    const [cx, cy] = project(this.centre[0], this.centre[1], this.zoom);
    this.centre = unproject(cx + dx, cy + dy, this.zoom);
    this.draw();
  }

  _screenToLatLon(px, py) {
    const [cx, cy] = project(this.centre[0], this.centre[1], this.zoom);
    return unproject(cx + px - this.w / 2, cy + py - this.h / 2, this.zoom);
  }

  _toScreen(lat, lon) {
    const [cx, cy] = project(this.centre[0], this.centre[1], this.zoom);
    const [x, y] = project(lat, lon, this.zoom);
    return [x - cx + this.w / 2, y - cy + this.h / 2];
  }

  _pick(px, py) {
    // Reverse order so the marker drawn last (on top) is picked first.
    for (let i = this._hit.length - 1; i >= 0; i--) {
      const h = this._hit[i];
      if ((px - h.x) ** 2 + (py - h.y) ** 2 <= (h.r + 3) ** 2) return h;
    }
    return null;
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    if (w === this.w && h === this.h) return;      // observer fires on no-ops
    // Guard against a measure→resize→measure feedback loop. An unstyled canvas
    // takes its size from its width/height attributes, which this method sets
    // from the measured box; if the CSS ever stops applying, the two chase each
    // other downwards and the map silently collapses to a few pixels while
    // still reporting features in view. Below this size it is not a map.
    const prevW = this.w || 0;
    const prevH = this.h || 0;
    if ((w < 80 || h < 80) && prevW > 80 && prevH > 80) {
      console.warn("map canvas measured %dx%d — ignoring; check that the "
                   + "canvas has a CSS size", w, h);
      return;
    }
    this.w = w;
    this.h = h;
    this.canvas.width = this.w * dpr;
    this.canvas.height = this.h * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const pending = this._pendingFit
      // A canvas that has more than doubled was almost certainly measured while
      // its view was hidden, so any fit computed then is wrong.
      || (this._lastFit && (w > prevW * 2 || h > prevH * 2) ? this._lastFit : null);
    if (pending && w > 2) {
      this._pendingFit = null;
      const [extent, pad] = pending;
      this.fit(extent, pad);
      return;
    }
    this.draw();
  }

  bbox() {
    const [s0, w0] = this._screenToLatLon(0, this.h);
    const [n0, e0] = this._screenToLatLon(this.w, 0);
    return { west: w0, south: s0, east: e0, north: n0 };
  }

  fit(extent, pad = 0.25) {
    if (!extent) return;
    const { south, west, north, east } = extent;
    this.centre = [(south + north) / 2, (west + east) / 2];
    // A canvas in a hidden view has no size yet. Computing a zoom from it
    // produces a nonsense viewport and a wasted request, so the fit is
    // remembered and replayed from resize() once the view is shown.
    // Remember the fit so it can be replayed. A canvas in a hidden view has no
    // usable size, and a fit computed against it produces a viewport zoomed out
    // to the whole subcontinent — which is what the estate map showed until the
    // canvas was measured again after the view became visible.
    this._lastFit = [extent, pad];
    if (this.w <= 2 || this.h <= 2) { this._pendingFit = [extent, pad]; return; }
    this._pendingFit = null;

    // Solved rather than searched: the span in projected pixels is linear in
    // 2^zoom, so the largest zoom that still fits is a logarithm, not a loop.
    const lonSpan = Math.max(1e-6, (east - west) * (1 + pad));
    const yOf = (lat) => {
      const s = Math.sin((Math.max(-85, Math.min(85, lat)) * Math.PI) / 180);
      return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
    };
    const ySpan = Math.max(1e-9, Math.abs(yOf(south) - yOf(north)) * (1 + pad));
    const zx = Math.log2((this.w / TILE) * (360 / lonSpan));
    const zy = Math.log2(this.h / TILE / ySpan);
    this.zoom = Math.max(3, Math.min(18, Math.min(zx, zy)));
    if (this._googleReady || this.googleEnabled) this.zoom = Math.round(this.zoom);
    this.draw();
    this.onViewport(this.bbox());
  }

  set(layer, data) { this.layers[layer] = data; this.draw(); }

  focusTarget(hops) {
    const pts = (hops || []).filter((h) => h.lat != null && h.lon != null);
    this.layers.trajectory = hopsToTrajectory(hops);
    if (!pts.length) { this.draw(); return; }
    const lats = pts.map((h) => Number(h.lat));
    const lons = pts.map((h) => Number(h.lon));
    this.fit({
      south: Math.min(...lats), north: Math.max(...lats),
      west: Math.min(...lons), east: Math.max(...lons),
    }, 0.45);
    const last = pts[pts.length - 1];
    this.centre = [Number(last.lat), Number(last.lon)];
    this.selected = last.camera_id;
    this.draw();
  }

  /* ── drawing ────────────────────────────────────────────────────────── */
  _css(token) {
    return getComputedStyle(document.documentElement).getPropertyValue(token).trim()
      || "#888";
  }

  draw() {
    const ctx = this.ctx;
    this._hit = [];
    ctx.clearRect(0, 0, this.w, this.h);
    const googleReady = this._googleReady && this.gmap;
    if (googleReady) {
      this._syncGoogle();
      this.canvas.classList.add("over-basemap");
    } else {
      this.canvas.classList.remove("over-basemap");
      ctx.fillStyle = this._css("--surface-2");
      ctx.fillRect(0, 0, this.w, this.h);
      this._graticule();
      if (this._basemap()) {
        this.canvas.classList.add("over-basemap");
      }
    }
    if (this.show.coverage) this._coverage();
    this._trajectory();
    this._cameras();
    if (this.show.alerts) this._alerts();
    this._scale();
    this._hoverCard();
  }

  _ensureGoogleHost() {
    const parent = this.canvas.parentElement;
    if (!parent) return null;
    let host = this.canvas.previousElementSibling;
    if (host && host.classList.contains("gmap-host")) return host;
    host = document.createElement("div");
    host.className = "gmap-host";
    host.setAttribute("aria-hidden", "true");
    parent.insertBefore(host, this.canvas);
    return host;
  }

  async _initGoogle() {
    const host = this._ensureGoogleHost();
    if (!host) return;
    try {
      const maps = await loadGoogleMaps(this.googleLoader || "/maps/google-api");
      this.gmap = new maps.Map(host, {
        center: { lat: this.centre[0], lng: this.centre[1] },
        zoom: Math.round(this.zoom),
        disableDefaultUI: true,
        gestureHandling: "none",
        keyboardShortcuts: false,
        clickableIcons: false,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
        mapTypeId: "roadmap",
      });
      this._googleReady = true;
      this.draw();
    } catch {
      this._googleReady = false;
      this.googleEnabled = false;
      if (this._tileFallback.template && !this.tiles) {
        this.tiles = new TileLayer(this._tileFallback.template, {
          attribution: this._tileFallback.attribution,
        });
        this.tiles.onLoad = () => this._scheduleDraw();
      }
      this.draw();
    }
  }

  _syncGoogle() {
    if (!this.gmap) return;
    const z = Math.round(this.zoom);
    const c = this.gmap.getCenter();
    if (!c
        || Math.abs(c.lat() - this.centre[0]) > 1e-7
        || Math.abs(c.lng() - this.centre[1]) > 1e-7) {
      this.gmap.setCenter({ lat: this.centre[0], lng: this.centre[1] });
    }
    if (this.gmap.getZoom() !== z) this.gmap.setZoom(z);
  }

  _scheduleDraw() {
    // Tiles arrive one at a time; redrawing per tile would thrash. One frame.
    if (this._drawQueued) return;
    this._drawQueued = true;
    requestAnimationFrame(() => { this._drawQueued = false; this.draw(); });
  }

  _basemap() {
    /* Returns true when tiles actually covered the view. A partially loaded
       basemap still draws the graticule underneath, so the map is never a blank
       rectangle while tiles are in flight. */
    if (!this.tiles || this.tiles.unreachable) return false;
    const z = Math.max(1, Math.min(19, Math.round(this.zoom)));
    const scale = TILE * Math.pow(2, z);
    const [cx, cy] = project(this.centre[0], this.centre[1], z);
    const left = cx - this.w / 2;
    const top = cy - this.h / 2;
    const x0 = Math.floor(left / TILE);
    const y0 = Math.floor(top / TILE);
    const x1 = Math.floor((left + this.w) / TILE);
    const y1 = Math.floor((top + this.h) / TILE);
    const n = Math.pow(2, z);
    let drawn = 0, wanted = 0;
    const ctx = this.ctx;
    ctx.imageSmoothingEnabled = true;
    for (let x = x0; x <= x1; x++) {
      for (let y = y0; y <= y1; y++) {
        if (y < 0 || y >= n) continue;
        wanted++;
        const img = this.tiles.get(z, ((x % n) + n) % n, y);
        if (!img) continue;
        ctx.drawImage(img, Math.round(x * TILE - left),
                      Math.round(y * TILE - top), TILE, TILE);
        drawn++;
      }
    }
    if (drawn) {
      // Markers must stay readable over photographic tiles in both themes. The
      // wash is applied as soon as any tile draws, so the view does not flip
      // appearance as the last tile lands.
      ctx.fillStyle = this._css("--surface-2");
      ctx.globalAlpha = 0.22;
      ctx.fillRect(0, 0, this.w, this.h);
      ctx.globalAlpha = 1;
      if (this.tiles.attribution) {
        ctx.font = "10px ui-monospace, monospace";
        const text = this.tiles.attribution;
        const tw = ctx.measureText(text).width + 8;
        ctx.fillStyle = this._css("--surface");
        ctx.globalAlpha = 0.8;
        ctx.fillRect(this.w - tw - 4, 2, tw, 14);
        ctx.globalAlpha = 1;
        ctx.fillStyle = this._css("--ink-3");
        ctx.fillText(text, this.w - tw, 12);
      }
      return true;
    }
    return false;
  }

  _graticule() {
    /* A measured grid, not decoration: the spacing is a round number of degrees
       chosen for the current zoom, and the scale bar below states what it is.
       It gives the eye a frame of reference without asserting any geography we
       have not been given. */
    const ctx = this.ctx;
    const steps = [10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001];
    const bb = this.bbox();
    const target = (bb.east - bb.west) / 7;
    const step = steps.reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
    ctx.strokeStyle = this._css("--line");
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = this._css("--ink-faint");
    for (let lon = Math.ceil(bb.west / step) * step; lon <= bb.east; lon += step) {
      const [x] = this._toScreen(bb.south, lon);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, this.h); ctx.stroke();
      ctx.fillText(lon.toFixed(step < 0.01 ? 3 : 2) + "°E", x + 3, this.h - 4);
    }
    for (let lat = Math.ceil(bb.south / step) * step; lat <= bb.north; lat += step) {
      const [, y] = this._toScreen(lat, bb.west);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.w, y); ctx.stroke();
      ctx.fillText(lat.toFixed(step < 0.01 ? 3 : 2) + "°N", 4, y - 3);
    }
  }

  _cameras() {
    const ctx = this.ctx;
    for (const f of this.layers.cameras) {
      if (f.lat == null || f.lon == null) continue;
      const [x, y] = this._toScreen(f.lat, f.lon);
      if (x < -40 || y < -40 || x > this.w + 40 || y > this.h + 40) continue;

      if (f.cluster) {
        const r = Math.min(20, 9 + Math.log2(f.count) * 2.6);
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = this._css(STATE_TOKEN[f.state] || "--unknown");
        ctx.globalAlpha = 0.28; ctx.fill(); ctx.globalAlpha = 1;
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = this._css(STATE_TOKEN[f.state] || "--unknown");
        ctx.stroke();
        ctx.fillStyle = this._css("--ink");
        ctx.font = "600 11px ui-monospace, monospace";
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(String(f.count), x, y);
        ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
        this._hit.push({ x, y, r, id: f.cluster_id, kind: "cluster", data: f });
        continue;
      }

      const token = this.mode === "capability"
        ? (GRADE_TOKEN[f.anpr] || "--unknown")
        : this.mode === "tier"
          ? (f.tier === "UNASSIGNED" ? "--unknown" : "--accent")
          : (STATE_TOKEN[f.state] || "--unknown");
      const colour = this._css(token);
      const selected = this.selected === f.camera_id;
      const r = selected ? 8 : 5.5;

      // Uncertainty first, underneath: a soft ring at the true radius, drawn
      // only when it is large enough on screen to mean anything. Below a few
      // pixels it would read as a rendering artefact rather than a bound.
      const metres = PRECISION_METRES[f.location_precision];
      if (metres) {
        const mPerPx = (156543.03392 * Math.cos((f.lat * Math.PI) / 180))
          / Math.pow(2, this.zoom);
        const rp = metres / mPerPx;
        if (rp > r + 3) {
          ctx.beginPath(); ctx.arc(x, y, rp, 0, Math.PI * 2);
          ctx.fillStyle = colour; ctx.globalAlpha = 0.10; ctx.fill();
          ctx.globalAlpha = 0.45; ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
          ctx.strokeStyle = colour; ctx.stroke();
          ctx.setLineDash([]); ctx.globalAlpha = 1;
        }
      }

      // A dark halo under the marker so it reads over a photographic basemap
      // in either theme. Without it, a teal dot on a green field disappears.
      ctx.beginPath(); ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
      ctx.fillStyle = this._css("--surface");
      ctx.globalAlpha = 0.85; ctx.fill(); ctx.globalAlpha = 1;

      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = colour; ctx.fill();
      ctx.lineWidth = selected ? 2.5 : 1.5;
      ctx.strokeStyle = selected ? this._css("--accent") : this._css("--ink");
      ctx.stroke();

      // A camera we could not grade is marked with a hollow centre, so
      // "unknown" is visually distinct from "measured and poor" rather than
      // just a different shade of grey.
      if (this.mode === "capability" && f.anpr === "UNKNOWN") {
        ctx.beginPath(); ctx.arc(x, y, r - 2.5, 0, Math.PI * 2);
        ctx.fillStyle = this._css("--surface"); ctx.fill();
      }

      if (this.show.labels || selected) {
        ctx.font = "10px ui-monospace, monospace";
        ctx.fillStyle = this._css("--ink-2");
        ctx.fillText(f.camera_id, x + r + 4, y + 3);
      }
      this._hit.push({ x, y, r, id: f.camera_id, kind: "camera", data: f });
    }
  }

  _trajectory() {
    const t = this.layers.trajectory;
    if (!t) return;
    const nodes = t.nodes || [];
    let legs = t.legs || [];
    if (!legs.length && nodes.length > 1) {
      legs = hopsToTrajectory(nodes).legs;
    }
    const ctx = this.ctx;
    for (const leg of legs) {
      if (leg.from_lat == null || leg.to_lat == null) continue;
      const [x1, y1] = this._toScreen(leg.from_lat, leg.from_lon);
      const [x2, y2] = this._toScreen(leg.to_lat, leg.to_lon);
      const st = LEG_STYLE[leg.kind] || LEG_STYLE.UNOBSERVED;
      ctx.setLineDash(st.dash);
      ctx.lineWidth = st.width;
      ctx.strokeStyle = this._css(st.token);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.setLineDash([]);
      this._arrow(x1, y1, x2, y2, this._css(st.token));
      const bits = [
        leg.elapsed,
        leg.distance_km != null && Number.isFinite(Number(leg.distance_km))
          ? `${Number(leg.distance_km).toFixed(1)} km` : null,
      ].filter(Boolean);
      if (bits.length) {
        ctx.font = "600 9px ui-sans-serif, sans-serif";
        ctx.fillStyle = this._css("--ink");
        ctx.textAlign = "center";
        ctx.fillText(bits.join(" · "), (x1 + x2) / 2, (y1 + y2) / 2 - 8);
        ctx.textAlign = "left";
      }
    }
    nodes.forEach((n, i) => {
      if (n.lat == null) return;
      const [x, y] = this._toScreen(n.lat, n.lon);
      ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2);
      ctx.fillStyle = this._css("--surface"); ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = this._css("--accent"); ctx.stroke();
      ctx.fillStyle = this._css("--ink");
      ctx.font = "600 11px ui-monospace, monospace";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(String(i + 1), x, y);
      const role = n.role || (i === 0 ? "FIRST SEEN"
        : (i === nodes.length - 1 ? "LAST SEEN" : "NEXT"));
      ctx.font = "600 9px ui-sans-serif, sans-serif";
      ctx.fillStyle = this._css("--seal");
      ctx.fillText(role, x, y + 18);
      ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
      this._hit.push({ x, y, r: 11, id: n.camera_id, kind: "trajectory-node", data: n });
    });
  }

  _arrow(x1, y1, x2, y2, colour) {
    const a = Math.atan2(y2 - y1, x2 - x1);
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const ctx = this.ctx, s = 7;
    ctx.beginPath();
    ctx.moveTo(mx + Math.cos(a) * s, my + Math.sin(a) * s);
    ctx.lineTo(mx + Math.cos(a + 2.5) * s, my + Math.sin(a + 2.5) * s);
    ctx.lineTo(mx + Math.cos(a - 2.5) * s, my + Math.sin(a - 2.5) * s);
    ctx.closePath();
    ctx.fillStyle = colour; ctx.fill();
  }

  _coverage() {
    const ctx = this.ctx;
    for (const g of this.layers.coverage) {
      if (g.lat == null) continue;
      const [x, y] = this._toScreen(g.lat, g.lon);
      const token = g.kind === "AVAILABILITY" ? "--conflict"
        : g.kind === "CAPABILITY" ? "--verify" : "--unknown";
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = this._css(token);
      ctx.beginPath(); ctx.arc(x, y, 15, 0, Math.PI * 2); ctx.stroke();
      if (g.to_lat != null) {
        const [x2, y2] = this._toScreen(g.to_lat, g.to_lon);
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x2, y2); ctx.stroke();
      }
      ctx.setLineDash([]);
      this._hit.push({ x, y, r: 15, id: "gap:" + g.camera_id, kind: "coverage", data: g });
    }
  }

  _alerts() {
    const ctx = this.ctx;
    for (const a of this.layers.alerts) {
      if (a.lat == null) continue;
      const [x, y] = this._toScreen(a.lat, a.lon);
      // A square, not a bigger circle: shape distinguishes an alert from a
      // camera without relying on colour.
      ctx.beginPath();
      ctx.rect(x - 6, y - 6, 12, 12);
      ctx.fillStyle = this._css(a.priority === "HIGH" || a.priority === "CRITICAL"
        ? "--conflict" : "--verify");
      ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = this._css("--surface"); ctx.stroke();
      this._hit.push({ x, y, r: 9, id: a.alert_id, kind: "alert", data: a });
    }
  }

  _scale() {
    const ctx = this.ctx;
    const [lat] = this.centre;
    const mPerPx = (156543.03392 * Math.cos((lat * Math.PI) / 180))
      / Math.pow(2, this.zoom);
    const targets = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];
    const want = 90 * mPerPx;
    const m = targets.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a));
    const px = m / mPerPx;
    const y = this.h - 26, x = this.w - px - 90;
    ctx.strokeStyle = this._css("--ink-3");
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, y - 4); ctx.lineTo(x, y); ctx.lineTo(x + px, y);
    ctx.lineTo(x + px, y - 4);
    ctx.stroke();
    ctx.fillStyle = this._css("--ink-3");
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillText(m >= 1000 ? `${m / 1000} km` : `${m} m`, x + px / 2 - 14, y - 7);
  }

  _hoverCard() {
    const h = this.hover;
    if (!h || h.id === this.selected) return;
    const ctx = this.ctx;
    const lines = this._describe(h);
    ctx.font = "11px ui-monospace, monospace";
    const wide = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 16;
    let x = h.x + 14, y = h.y - 10;
    if (x + wide > this.w) x = h.x - wide - 14;
    const boxH = lines.length * 15 + 10;
    if (y + boxH > this.h) y = this.h - boxH - 4;
    ctx.fillStyle = this._css("--surface");
    ctx.strokeStyle = this._css("--line-strong");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.rect(x, y, wide, boxH);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = this._css("--ink");
    lines.forEach((l, i) => ctx.fillText(l, x + 8, y + 17 + i * 15));
  }

  _describe(h) {
    const d = h.data;
    if (h.kind === "cluster") {
      return [`${d.count} cameras`, `worst state: ${d.state}`, "click to zoom in"];
    }
    if (h.kind === "alert") return [`ALERT ${d.plate || ""}`, `${d.priority} · ${d.status}`];
    if (h.kind === "coverage") return [`${d.kind} GAP`, d.camera_id];
    if (h.kind === "trajectory-node") {
      return [d.role || d.camera_id, d.camera_id,
              (d.t_norm || d.t || "").replace("T", " ").slice(0, 19)];
    }
    const lines = [
      `${d.camera_id}${d.name ? "  " + d.name : ""}`,
      d.source_domain ? String(d.source_domain).replaceAll("_", " ") : null,
      d.tile_status || `state ${d.state}`,
      `anpr ${d.anpr} · appearance ${d.vehicle}`,
    ].filter(Boolean);
    if (d.location_basis === "DERIVED_FROM_NAME") {
      const m = PRECISION_METRES[d.location_precision];
      lines.push(m ? `position from name, +/-${m >= 1000 ? m / 1000 + " km" : m + " m"}`
                   : "position from name, precision unknown");
    }
    return lines;
  }
}
