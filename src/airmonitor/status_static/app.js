const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[character]);
const number = (value, digits = 1) => value == null ? "—" : Number(value).toFixed(digits);
const bytes = (value) => {
  if (value == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(value), index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
};
const duration = (seconds) => {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} sec`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} hr`;
  return `${(seconds / 86400).toFixed(1)} days`;
};
const timeAgo = (seconds) => seconds == null ? "No samples" : `${duration(seconds)} ago`;
const pill = (text, klass) => `<span class="pill ${klass}">${text}</span>`;
const serviceLabel = (name) => ({
  "airmonitor.target": "AirMonitor application",
  "airmonitor-status.service": "Status page",
  "airmonitor-voc.service": "VOC sensor",
  "grafana-server.service": "Grafana server",
  "mosquitto.service": "Mosquitto MQTT",
})[name] || name.replace(".service", "").replace("airmonitor-", "").replaceAll("-", " ");
const serviceRuntime = (value) => typeof value === "object" && value !== null
  ? {active: value.active_state || "unknown", sub: value.sub_state || "unknown"}
  : {active: value || "unknown", sub: value || "unknown"};
const targetManagedServices = new Set([
  "airmonitor-status.service", "airmonitor-voc.service", "airmonitor-sps30.service",
  "airmonitor-printer-mqtt.service", "airmonitor-bento.service", "airmonitor-levoit.service",
]);
let session = {authenticated: false, services: {}};
let streamedService = null;
let serviceStreamTimer = null;

function renderSession() {
  const panel = $("auth-panel");
  const user = session.user;
  if (!session.authenticated || !user) {
    stopServiceStatusStream();
    panel.innerHTML = `<a class="grafana-signin" href="https://grafana.airmonitor.example.com/logout">Sign in <span aria-hidden="true">↗</span><small>Administration and dashboards</small></a><a class="password-reset" href="https://grafana.airmonitor.example.com/user/password/send-reset-email">Forgot password?</a>`;
    $("admin-notice").hidden = true;
    $("services-caption").textContent = "Systemd state";
    return;
  }
  panel.innerHTML = `<div class="signed-in"><strong>${escapeHtml(user.name)}</strong><small>${escapeHtml(user.role)} · ${escapeHtml(user.email || user.login)}</small><a class="dashboard-browser-link" href="https://grafana.airmonitor.example.com/dashboards">Browse dashboards <span aria-hidden="true">→</span></a><div class="account-links"><a href="https://grafana.airmonitor.example.com/profile">Account</a><a href="https://grafana.airmonitor.example.com/logout">Sign out</a></div></div>`;
  $("admin-notice").hidden = !user.admin;
  $("services-caption").textContent = user.admin ? "Administrator controls" : "Systemd state";
}

function serviceControl(name) {
  if (!session.user?.admin || !(name in session.services)) return "";
  const labels = {restart: "Restart", start: "Start", stop: "Stop", enable: "Enable and start", disable: "Disable and stop"};
  const options = session.services[name].actions.map((action) => `<option value="${action}">${labels[action]}</option>`).join("");
  return `<div class="service-controls"><select aria-label="Action for ${escapeHtml(serviceLabel(name))}" data-service-action="${escapeHtml(name)}">${options}</select><button type="button" data-service-apply="${escapeHtml(name)}">Apply</button><button class="status-button" type="button" data-service-status="${escapeHtml(name)}">Status</button></div>`;
}

function filterControl(item) {
  if (!session.user?.admin) return "";
  return `<div class="filter-controls" role="group" aria-label="Control ${escapeHtml(item.filter_id)}">
    ${["auto", "on", "off"].map((mode) => `<button type="button" data-filter="${escapeHtml(item.filter_id)}" data-filter-mode="${mode}" class="${item.manual_mode === mode ? "selected" : ""}" aria-pressed="${item.manual_mode === mode}">${mode}</button>`).join("")}
  </div>`;
}

function showServiceStatus(service, output, scroll = false) {
  $("service-status-title").textContent = service;
  $("service-status-output").textContent = output || "No systemctl output.";
  $("service-status-panel").hidden = false;
  if (scroll) $("service-status-panel").scrollIntoView({behavior: "smooth", block: "start"});
}

async function readServiceStatus(service) {
  const response = await fetch(`/service-status-api?service=${encodeURIComponent(service)}`, {cache: "no-store", credentials: "same-origin"});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result.output;
}

function stopServiceStatusStream() {
  streamedService = null;
  if (serviceStreamTimer) window.clearInterval(serviceStreamTimer);
  serviceStreamTimer = null;
  $("service-status-panel").hidden = true;
}

function startServiceStatusStream(service, initialOutput = null) {
  streamedService = service;
  if (serviceStreamTimer) window.clearInterval(serviceStreamTimer);
  showServiceStatus(service, initialOutput || "Loading systemctl status…", true);
  const update = async () => {
    if (streamedService !== service) return;
    try {
      showServiceStatus(service, await readServiceStatus(service));
    } catch (error) {
      showServiceStatus(service, `Unable to refresh service status: ${error.message}`);
    }
  };
  update();
  serviceStreamTimer = window.setInterval(update, 2000);
}

async function fetchServiceStatus(service, button) {
  button.disabled = true;
  try {
    startServiceStatusStream(service, await readServiceStatus(service));
  } catch (error) {
    window.alert(`Unable to read service status: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

function render(data) {
  const status = data.overall || "offline";
  $("overall").textContent = status;
  $("overall-dot").className = `status-dot ${status}`;
  $("summary").textContent = data.warnings?.length ? data.warnings.join(" · ") : "All monitored systems are operating normally.";
  $("updated").textContent = new Date(data.checked_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit", second: "2-digit"});

  const sgx = data.readings?.sgx || {};
  const sps = data.readings?.sps30 || {};
  $("voc").textContent = number(sgx.gas_ppm, 2);
  $("temperature").textContent = number(sgx.temperature_c, 1);
  $("humidity").textContent = number(sgx.humidity_rh, 1);
  $("pm1").textContent = number(sps.mass_pm1_0, 1);
  $("pm25").textContent = number(sps.mass_pm2_5, 1);
  $("pm4").textContent = number(sps.mass_pm4_0, 1);
  $("pm10").textContent = number(sps.mass_pm10, 1);

  const printer = data.printer || {};
  $("printer-state").textContent = printer.last_gcode_state || "Unknown";
  $("printer-availability").textContent = printer.printer_connected === 1 ? "Connected" : (printer.printer_available || "Unknown");
  $("filament").textContent = [printer.filament_type, printer.filament_name].filter(Boolean).join(" · ") || "—";
  $("print-job").textContent = printer.subtask_name || "No active job";

  const levoit = data.levoit || {};
  $("filters").innerHTML = (data.filters || []).map((item) => `
    <div class="state-row filter-row"><div class="filter-summary"><div><div class="state-name">${escapeHtml(item.filter_id)}</div><div class="state-meta">${escapeHtml(item.manual_mode)} · ${escapeHtml(item.reason || "service reported")}</div>${item.filter_id === "levoit" && levoit.sampled_at ? `<div class="state-meta telemetry">Fan ${escapeHtml(levoit.fan_level ?? "—")} · PM2.5 ${escapeHtml(number(levoit.pm2_5, 0))} µg/m³ · ${escapeHtml(levoit.mode || "unknown mode")} · Filter ${escapeHtml(levoit.filter_life_percent ?? "—")}%</div>` : ""}</div>${pill(escapeHtml(item.effective_state), escapeHtml(item.effective_state))}</div>${filterControl(item)}</div>
  `).join("") || '<div class="state-row"><span>No filter state</span></div>';

  $("freshness").innerHTML = Object.entries(data.freshness || {}).map(([name, item]) => {
    const fresh = item.age_seconds != null && item.age_seconds <= 90;
    return `<div class="state-row freshness-row"><div class="freshness-summary"><div><div class="state-name">${escapeHtml(name)}</div><div class="state-meta">${escapeHtml(timeAgo(item.age_seconds))}</div></div>${pill(fresh ? "Fresh" : "Stale", fresh ? "fresh" : "stale")}</div>${!fresh && item.error ? `<pre class="sensor-error">${escapeHtml(item.error)}</pre>` : ""}</div>`;
  }).join("");

  const host = data.host || {};
  $("uptime").textContent = duration(host.uptime_seconds);
  $("disk").textContent = host.disk_used_percent == null ? "—" : `${host.disk_used_percent}% · ${bytes(host.disk_used_bytes)}`;
  $("database-size").textContent = bytes(host.database_size_bytes);
  $("cpu-temperature").textContent = host.cpu_temperature_c == null ? "Unavailable" : `${number(host.cpu_temperature_c, 1)} °C`;

  $("services").innerHTML = Object.entries(data.services || {}).map(([name, state]) => {
    const runtime = serviceRuntime(state);
    const runtimeText = runtime.active;
    const ownership = targetManagedServices.has(name) ? "Target managed" : (session.user?.admin && name in session.services ? session.services[name].enabled : "");
    return `<div class="service-item"><div class="service-summary"><span class="service-label" title="${escapeHtml(name)}">${escapeHtml(serviceLabel(name))}</span><span>${ownership ? `<span class="enabled-state">${escapeHtml(ownership)}</span> ` : ""}${pill(escapeHtml(runtimeText), escapeHtml(runtime.active))}</span></div>${serviceControl(name)}</div>`;
  }).join("");
}

async function refreshSession() {
  try {
    const response = await fetch("/session-api", {cache: "no-store", credentials: "same-origin"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    session = await response.json();
  } catch (_) {
    session = {authenticated: false, services: {}};
  }
  renderSession();
}

async function controlService(service, action, button) {
  if (!session.user?.admin) return;
  if (!window.confirm(`${action} ${service}? This affects live AirMonitor operation.`)) return;
  button.disabled = true;
  try {
    const response = await fetch("/service-control-api", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-AirMonitor-Action": "service-control"},
      body: JSON.stringify({service, action}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    startServiceStatusStream(service, result.output);
    await new Promise((resolve) => setTimeout(resolve, 900));
    await Promise.all([refreshSession(), refresh()]);
  } catch (error) {
    window.alert(`Service action failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function controlFilter(filterId, mode, button) {
  if (!session.user?.admin) return;
  button.disabled = true;
  try {
    const response = await fetch("/filter-control-api", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-AirMonitor-Action": "filter-control"},
      body: JSON.stringify({filter_id: filterId, mode}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    await refresh();
  } catch (error) {
    window.alert(`Filter control failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const filterButton = event.target.closest("[data-filter-mode]");
  if (filterButton) {
    controlFilter(filterButton.dataset.filter, filterButton.dataset.filterMode, filterButton);
    return;
  }
  const statusButton = event.target.closest("[data-service-status]");
  if (statusButton) {
    fetchServiceStatus(statusButton.dataset.serviceStatus, statusButton);
    return;
  }
  const button = event.target.closest("[data-service-apply]");
  if (!button) return;
  const service = button.dataset.serviceApply;
  const select = document.querySelector(`[data-service-action="${CSS.escape(service)}"]`);
  controlService(service, select.value, button);
});

$("service-status-clear").addEventListener("click", stopServiceStatusStream);

async function refresh() {
  try {
    const response = await fetch("/status-api", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $("overall").textContent = "Offline";
    $("overall-dot").className = "status-dot offline";
    $("summary").textContent = "The AirMonitor status service is unavailable.";
  }
}

async function initialize() {
  await refreshSession();
  await refresh();
}

initialize();
setInterval(refresh, 10000);
setInterval(async () => { await refreshSession(); await refresh(); }, 60000);
