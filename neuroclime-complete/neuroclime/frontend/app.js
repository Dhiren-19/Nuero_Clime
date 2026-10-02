(() => {
  const CFG = window.NEUROCLIME_CONFIG || { API_BASE_URL: "http://localhost:8000", DEFAULT_CITY_ID: "demo-city-pune" };
  const I18N = window.NEUROCLIME_I18N;
  const HORIZONS = [0, 1, 3, 6];

  const state = {
    lang: localStorage.getItem("nc_lang") || "en",
    view: "citizen",
    role: "citizen",
    userId: localStorage.getItem("nc_user_id") || (() => {
      const id = "citizen-" + Math.random().toString(36).slice(2, 10);
      localStorage.setItem("nc_user_id", id);
      return id;
    })(),
    cityId: CFG.DEFAULT_CITY_ID,
    horizonIndex: 0,
    hexById: {},          // hex_id -> {geom, centroid, static_features}
    predsByHexHorizon: {},// `${hex_id}:${horizon}` -> prediction row
    pickingFor: null,     // 'home' | 'work' | 'route' | 'scenario' | null
    homeHexId: null,
    workHexId: null,
    routePoints: [],
    scenarioHexId: null,
    online: true,
  };

  // ---------- i18n ----------
  function applyI18n() {
    const dict = I18N[state.lang] || I18N.en;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (dict[key]) el.textContent = dict[key];
    });
    document.getElementById("connection-label").textContent = state.online ? dict.live : dict.offline;
  }
  function t(key) { return (I18N[state.lang] || I18N.en)[key] || key; }

  // ---------- API ----------
  async function api(path, opts = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json", "X-Demo-Role": state.role, "X-Demo-User-Id": state.userId },
      opts.headers || {}
    );
    const res = await fetch(CFG.API_BASE_URL + path, Object.assign({}, opts, { headers }));
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }
  function setOnline(isOnline) {
    if (state.online === isOnline) return;
    state.online = isOnline;
    const badge = document.getElementById("connection-badge");
    badge.className = "badge " + (isOnline ? "badge-live" : "badge-offline");
    applyI18n();
  }

  function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  // ---------- Risk bands (mirrors pipeline/heat_index.py) ----------
  const RISK_BANDS = {
    safe: { color: "#0072B2", icon: "🟦" },
    caution: { color: "#E69F00", icon: "🟧" },
    danger: { color: "#D55E00", icon: "🟥" },
    extreme: { color: "#7A0000", icon: "⬛" },
  };

  // ---------- Map setup ----------
  let citizenMap, authorityMap, citizenHexLayer, authorityHexLayer, routeLayerGroup;

  function makeMap(elId) {
    const map = L.map(elId, { zoomControl: true, attributionControl: false }).setView([18.53, 73.85], 11);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    }).addTo(map);
    return map;
  }

  function styleForHex(hexId) {
    const key = `${hexId}:${HORIZONS[state.horizonIndex]}`;
    const pred = state.predsByHexHorizon[key];
    const band = pred ? RISK_BANDS[pred.risk_band] : null;
    return {
      color: band ? band.color : "#3a5654",
      weight: 1,
      fillColor: band ? band.color : "#1a3230",
      fillOpacity: band ? 0.55 : 0.15,
    };
  }

  function buildGeoJSON() {
    return {
      type: "FeatureCollection",
      features: Object.values(state.hexById).map((h) => ({
        type: "Feature",
        properties: { hex_id: h.hex_id },
        geometry: h.geom,
      })),
    };
  }

  function renderHexLayers() {
    const geojson = buildGeoJSON();
    [
      { map: citizenMap, layerRef: "citizenHexLayer" },
      { map: authorityMap, layerRef: "authorityHexLayer" },
    ].forEach(({ map, layerRef }) => {
      if (!map) return;
      if (window[layerRef + "_instance"]) map.removeLayer(window[layerRef + "_instance"]);
      const layer = L.geoJSON(geojson, {
        style: (f) => styleForHex(f.properties.hex_id),
        onEachFeature: (feature, lyr) => {
          lyr.on("click", (e) => onHexClick(feature.properties.hex_id, e.latlng, map === authorityMap ? "authority" : "citizen"));
        },
      }).addTo(map);
      window[layerRef + "_instance"] = layer;
    });
  }

  // ---------- Data loading ----------
  async function loadHexZones() {
    try {
      const data = await api(`/v1/hexzones?city_id=${state.cityId}`);
      state.hexById = {};
      data.hex_zones.forEach((h) => { state.hexById[h.hex_id] = h; });
      localStorage.setItem("nc_hexzones_cache", JSON.stringify(data.hex_zones));
      setOnline(true);
    } catch (e) {
      setOnline(false);
      const cached = localStorage.getItem("nc_hexzones_cache");
      if (cached) {
        JSON.parse(cached).forEach((h) => { state.hexById[h.hex_id] = h; });
      }
    }
  }

  async function loadPredictionsForHorizon(horizon) {
    const path = horizon === 0
      ? `/v1/predictions/current?city_id=${state.cityId}`
      : `/v1/predictions/forecast?city_id=${state.cityId}&horizon=${horizon}`;
    try {
      const data = await api(path);
      data.predictions.forEach((p) => { state.predsByHexHorizon[`${p.hex_id}:${p.horizon_hours}`] = p; });
      localStorage.setItem(`nc_preds_cache_${horizon}`, JSON.stringify({ ts: Date.now(), predictions: data.predictions }));
      setOnline(true);
      return true;
    } catch (e) {
      setOnline(false);
      const cached = localStorage.getItem(`nc_preds_cache_${horizon}`);
      if (cached) {
        const { ts, predictions } = JSON.parse(cached);
        predictions.forEach((p) => { state.predsByHexHorizon[`${p.hex_id}:${p.horizon_hours}`] = p; });
        showOfflineBanner(ts);
      }
      return false;
    }
  }

  async function loadAllHorizons() {
    for (const h of HORIZONS) await loadPredictionsForHorizon(h);
    renderHexLayers();
  }

  function showOfflineBanner(ts) {
    const minutes = Math.max(0, Math.round((Date.now() - ts) / 60000));
    document.getElementById("offline-minutes").textContent = minutes;
    document.getElementById("offline-banner").classList.remove("hidden");
  }
  function hideOfflineBanner() {
    document.getElementById("offline-banner").classList.add("hidden");
  }

  // ---------- Citizen: hex click behavior ----------
  async function onHexClick(hexId, latlng, mapContext) {
    if (mapContext === "citizen") {
      if (state.pickingFor === "home") {
        state.homeHexId = hexId;
        document.getElementById("home-hex-label").textContent = hexId;
        exitPicking();
        return;
      }
      if (state.pickingFor === "work") {
        state.workHexId = hexId;
        document.getElementById("work-hex-label").textContent = hexId;
        exitPicking();
        return;
      }
      if (state.pickingFor === "route") {
        state.routePoints.push({ hexId, latlng });
        if (state.routePoints.length === 1) {
          toast("Start point set — now click the destination.");
          return;
        }
        if (state.routePoints.length === 2) {
          exitPicking();
          await runCoolestRoute();
          return;
        }
      }
      showZoneDetail(hexId);
    } else if (mapContext === "authority") {
      state.scenarioHexId = hexId;
      document.getElementById("scenario-hex-label").textContent = hexId;
      document.getElementById("scenario-hex-label").classList.remove("mono", "muted");
      document.getElementById("scenario-hex-label").classList.add("mono");
      const hz = state.hexById[hexId];
      if (hz) {
        document.getElementById("ndvi-slider").value = hz.static_features.ndvi ?? 0.4;
        document.getElementById("ndvi-readout").textContent = (hz.static_features.ndvi ?? 0.4).toFixed(2);
        document.getElementById("building-slider").value = hz.static_features.building_density_pct ?? 0.4;
        document.getElementById("building-readout").textContent = (hz.static_features.building_density_pct ?? 0.4).toFixed(2);
      }
    }
  }

  function exitPicking() {
    state.pickingFor = null;
    document.getElementById("set-home-btn").classList.remove("picking");
    document.getElementById("set-work-btn").classList.remove("picking");
    document.getElementById("pick-route-btn").classList.remove("picking");
  }

  async function showZoneDetail(hexId) {
    const panel = document.getElementById("zone-panel");
    panel.innerHTML = `<h3 class="mono">${hexId}</h3><p class="muted">Loading…</p>`;
    try {
      const data = await api(`/v1/predictions/hex/${hexId}`);
      const rows = {};
      data.predictions.forEach((p) => { rows[p.horizon_hours] = p; });
      const cur = rows[0] || Object.values(rows)[0];
      const band = cur ? RISK_BANDS[cur.risk_band] : null;
      const staticF = (state.hexById[hexId] || {}).static_features || {};
      panel.innerHTML = `
        <h3 class="mono">${hexId}</h3>
        ${cur ? `<span class="risk-pill" style="background:${band.color}22;color:${band.color};border:1px solid ${band.color}">${band.icon} ${t('band_' + cur.risk_band)}</span>` : ""}
        <div class="zone-stat-grid">
          <div class="zone-stat"><div class="label">Temp</div><div class="value">${cur ? cur.pred_temp_c + "°C" : "—"}</div></div>
          <div class="zone-stat"><div class="label">Feels like</div><div class="value">${cur ? cur.heat_index_c + "°C" : "—"}</div></div>
          <div class="zone-stat"><div class="label">Humidity</div><div class="value">${cur ? cur.pred_humidity_pct + "%" : "—"}</div></div>
          <div class="zone-stat"><div class="label">± Uncertainty</div><div class="value">${cur ? cur.pred_temp_uncertainty_c + "°C" : "—"}</div></div>
        </div>
        <p class="muted" style="margin-top:10px">Land cover: NDVI ${staticF.ndvi ?? "—"} · ${staticF.lcz_class || "—"}</p>
      `;
    } catch (e) {
      panel.innerHTML = `<h3 class="mono">${hexId}</h3><p class="muted">Couldn't load zone detail (offline?).</p>`;
    }
  }

  // ---------- Time slider ----------
  function initTimeSlider() {
    const slider = document.getElementById("horizon-slider");
    slider.addEventListener("input", () => {
      state.horizonIndex = parseInt(slider.value, 10);
      const labels = ["h0", "h1", "h3", "h6"];
      document.getElementById("horizon-readout").textContent = t(labels[state.horizonIndex]);
      renderHexLayers();
    });
  }

  // ---------- Alerts ----------
  function initAlerts() {
    document.getElementById("set-home-btn").addEventListener("click", () => {
      state.pickingFor = state.pickingFor === "home" ? null : "home";
      document.getElementById("set-home-btn").classList.toggle("picking", state.pickingFor === "home");
      document.getElementById("set-work-btn").classList.remove("picking");
      toast("Click a hex on the map to set your home zone.");
    });
    document.getElementById("set-work-btn").addEventListener("click", () => {
      state.pickingFor = state.pickingFor === "work" ? null : "work";
      document.getElementById("set-work-btn").classList.toggle("picking", state.pickingFor === "work");
      document.getElementById("set-home-btn").classList.remove("picking");
      toast("Click a hex on the map to set your work zone.");
    });
    document.getElementById("subscribe-btn").addEventListener("click", async () => {
      try {
        await api("/v1/alerts/subscribe", {
          method: "POST",
          body: JSON.stringify({ home_hex_id: state.homeHexId, work_hex_id: state.workHexId, preferred_language: state.lang }),
        });
        toast("Alert preferences saved.");
        loadAlerts();
      } catch (e) {
        toast("Couldn't save — check your connection.");
      }
    });
  }

  async function loadAlerts() {
    try {
      const data = await api("/v1/alerts");
      const list = document.getElementById("alerts-list");
      list.innerHTML = data.alerts.length
        ? data.alerts.map((a) => `<div class="alert-item">${a.message || (a.risk_band + " — " + a.hex_id)}</div>`).join("")
        : "";
    } catch (e) { /* silent — offline */ }
  }

  // ---------- Coolest route ----------
  function initRoute() {
    document.getElementById("pick-route-btn").addEventListener("click", () => {
      const active = state.pickingFor === "route";
      exitPicking();
      if (!active) {
        state.pickingFor = "route";
        state.routePoints = [];
        document.getElementById("pick-route-btn").classList.add("picking");
        toast("Click the starting point on the map.");
      }
    });
  }

  async function runCoolestRoute() {
    const [origin, dest] = state.routePoints;
    const oHex = state.hexById[origin.hexId], dHex = state.hexById[dest.hexId];
    if (!oHex || !dHex) return;
    const oCoord = oHex.centroid.coordinates, dCoord = dHex.centroid.coordinates;
    try {
      const result = await api(
        `/v1/routes/coolest?origin=${oCoord[0]},${oCoord[1]}&destination=${dCoord[0]},${dCoord[1]}&city_id=${state.cityId}`
      );
      if (routeLayerGroup) citizenMap.removeLayer(routeLayerGroup);
      routeLayerGroup = L.layerGroup().addTo(citizenMap);
      L.polyline(result.path_coords.map((c) => [c[1], c[0]]), { color: "#e69f00", weight: 4 }).addTo(routeLayerGroup);
      document.getElementById("route-result").innerHTML = `
        <div class="route-line">
          ${result.hex_count} zones · avg heat index <strong>${result.avg_heat_index_c}°C</strong>
          ${result.naive_shortest_path_exposure ? `<br/><span class="muted">vs. ${result.naive_shortest_path_exposure} total on the most direct path</span>` : ""}
        </div>`;
    } catch (e) {
      toast("Couldn't compute a route — try two points further apart.");
    }
  }

  // ---------- View switching ----------
  function setView(view) {
    state.view = view;
    document.querySelectorAll(".view-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
    state.role = view === "citizen" ? "citizen" : view; // 'authority' | 'admin'

    if (view === "authority") {
      if (!authorityMap) {
        authorityMap = makeMap("authority-map");
        renderHexLayers();
      }
      loadWardRanking();
    }
    if (view === "admin") loadPipelineStatus();
    if (view === "citizen") loadAlerts();
  }

  function initViewSwitch() {
    document.querySelectorAll(".view-btn").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  }

  // ---------- Language switch ----------
  function initLangSwitch() {
    document.querySelectorAll(".lang-btn").forEach((b) => {
      b.addEventListener("click", () => {
        state.lang = b.dataset.lang;
        localStorage.setItem("nc_lang", state.lang);
        document.querySelectorAll(".lang-btn").forEach((x) => x.classList.toggle("active", x === b));
        applyI18n();
      });
    });
  }

  // ---------- Ward ranking ----------
  async function loadWardRanking() {
    try {
      const data = await api(`/v1/wards/ranking?city_id=${state.cityId}`);
      const tbody = document.getElementById("ward-table-body");
      tbody.innerHTML = data.ranking
        .map((w, i) => `<tr>
          <td>${i + 1}</td><td>${w.name}</td>
          <td class="mono-cell">${w.population?.toLocaleString() ?? "—"}</td>
          <td class="mono-cell">${w.avg_heat_index_c}°C</td>
          <td class="mono-cell">${Math.round(w.exposure_score).toLocaleString()}</td>
        </tr>`).join("");
    } catch (e) {
      document.getElementById("ward-table-body").innerHTML = `<tr><td colspan="5" class="muted">Couldn't load — check the backend is running.</td></tr>`;
    }
  }

  function initReportExport() {
    document.getElementById("export-report-btn").addEventListener("click", async () => {
      try {
        const data = await api("/v1/reports/generate", { method: "POST", body: JSON.stringify({ city_id: state.cityId }) });
        document.getElementById("report-result").innerHTML =
          `<a href="${CFG.API_BASE_URL}${data.file_url}" target="_blank" class="mono">Download report (${data.rows} rows)</a>`;
      } catch (e) {
        toast("Report generation failed.");
      }
    });
  }

  // ---------- Scenario tool ----------
  function initScenarioTool() {
    const ndviSlider = document.getElementById("ndvi-slider");
    const buildingSlider = document.getElementById("building-slider");
    ndviSlider.addEventListener("input", () => { document.getElementById("ndvi-readout").textContent = parseFloat(ndviSlider.value).toFixed(2); });
    buildingSlider.addEventListener("input", () => { document.getElementById("building-readout").textContent = parseFloat(buildingSlider.value).toFixed(2); });

    document.getElementById("run-scenario-btn").addEventListener("click", async () => {
      if (!state.scenarioHexId) { toast("Click a zone on the map below first."); return; }
      try {
        const result = await api("/v1/scenarios", {
          method: "POST",
          body: JSON.stringify({
            hex_id: state.scenarioHexId,
            modified_features: { ndvi: parseFloat(ndviSlider.value), building_density_pct: parseFloat(buildingSlider.value) },
            horizon_hours: 0,
          }),
        });
        const delta = result.predicted_delta_temp_c;
        const cls = delta < 0 ? "cooling" : delta > 0 ? "warming" : "";
        document.getElementById("scenario-result").innerHTML = `
          <div class="scenario-delta ${cls}">${delta > 0 ? "+" : ""}${delta}°C</div>
          <div class="muted">${result.baseline.pred_temp_c}°C → ${result.scenario.pred_temp_c}°C ·
            new band: ${result.scenario_risk_band.icon} ${t('band_' + result.scenario_risk_band.key)}</div>
        `;
      } catch (e) {
        toast("Scenario run failed.");
      }
    });
  }

  // ---------- Admin ----------
  async function loadPipelineStatus() {
    try {
      const data = await api("/internal/pipeline/status");
      const tbody = document.getElementById("pipeline-table-body");
      tbody.innerHTML = data.runs
        .map((r) => `<tr>
          <td>${r.job_type}</td><td>${r.source || "—"}</td>
          <td>${r.status}</td>
          <td class="mono-cell">${r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
          <td class="mono-cell">${r.metrics ? JSON.stringify(r.metrics) : "—"}</td>
        </tr>`).join("");
    } catch (e) {
      document.getElementById("pipeline-table-body").innerHTML = `<tr><td colspan="5" class="muted">Couldn't load.</td></tr>`;
    }
  }
  function initAdmin() {
    document.getElementById("trigger-inference-btn").addEventListener("click", async () => {
      try {
        await api("/internal/pipeline/trigger", { method: "POST", body: JSON.stringify({ job_type: "inference" }) });
        toast("Inference run triggered.");
        setTimeout(loadPipelineStatus, 800);
      } catch (e) {
        toast("Trigger failed.");
      }
    });
  }

  // ---------- Boot ----------
  async function boot() {
    document.querySelectorAll(`.lang-btn[data-lang="${state.lang}"]`).forEach((b) => b.classList.add("active"));
    document.querySelectorAll(".lang-btn").forEach((b) => b.classList.toggle("active", b.dataset.lang === state.lang));
    applyI18n();

    initViewSwitch();
    initLangSwitch();
    initTimeSlider();
    initAlerts();
    initRoute();
    initReportExport();
    initScenarioTool();
    initAdmin();

    citizenMap = makeMap("map");

    await loadHexZones();
    await loadAllHorizons();
    if (state.online) hideOfflineBanner();

    setView("citizen");

    // Poll for fresh predictions every 60s (batch inference refreshes every 15 min per TRD).
    setInterval(loadAllHorizons, 60000);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
