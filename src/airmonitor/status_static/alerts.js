const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[character]);
const number = (value, digits = 1) => value == null ? null : Number(value).toFixed(digits);

const duration = (seconds) => {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} sec`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} hr`;
  return `${(seconds / 86400).toFixed(1)} days`;
};

const ago = (isoString, now) => {
  if (!isoString) return "—";
  const seconds = Math.max(0, (now - new Date(isoString).getTime()) / 1000);
  return `${duration(seconds)} ago`;
};

const pill = (text, klass) => `<span class="pill ${klass}">${text}</span>`;
const levelPillClass = (level) => ({critical: "offline", warning: "degraded", resolved: "active"})[level] || "";

function alertDetail(item) {
  const parts = [];
  if (item.value != null) {
    parts.push(item.threshold != null ? `${number(item.value, 2)} (threshold ${number(item.threshold, 2)})` : number(item.value, 2));
  }
  return parts.join(" · ");
}

function renderActive(alerts, now) {
  if (!alerts.length) {
    $("active-alerts").innerHTML = '<div class="state-row"><span>No active alerts</span></div>';
    return;
  }
  $("active-alerts").innerHTML = alerts.map((item) => `
    <div class="state-row alert-row alert-row-${escapeHtml(item.level)}">
      <div class="alert-summary">
        <div>
          <div class="alert-key">${escapeHtml(item.alert_key.replaceAll("_", " "))}</div>
          <div class="state-meta">${escapeHtml(item.message)}</div>
          <div class="state-meta telemetry">${[alertDetail(item), `Fired ${escapeHtml(ago(item.fired_at, now))}`].filter(Boolean).join(" · ")}</div>
        </div>
        ${pill(escapeHtml(item.level), levelPillClass(item.level))}
      </div>
    </div>
  `).join("");
}

function renderHistory(alerts, now) {
  if (!alerts.length) {
    $("alert-history").innerHTML = '<div class="state-row"><span>No alerts in recent history</span></div>';
    return;
  }
  $("alert-history").innerHTML = alerts.map((item) => `
    <div class="state-row alert-row alert-row-resolved">
      <div class="alert-summary">
        <div>
          <div class="alert-key">${escapeHtml(item.alert_key.replaceAll("_", " "))}</div>
          <div class="state-meta">${escapeHtml(item.message)}</div>
          <div class="state-meta telemetry">Fired ${escapeHtml(ago(item.fired_at, now))} · Resolved ${escapeHtml(ago(item.resolved_at, now))}</div>
        </div>
        ${pill(escapeHtml(item.level), levelPillClass("resolved"))}
      </div>
    </div>
  `).join("");
}

function render(data) {
  const now = Date.now();
  const active = data.open || [];
  const history = data.resolved || [];

  const worst = active.some((item) => item.level === "critical") ? "critical" : (active.length ? "warning" : null);
  const status = worst === "critical" ? "offline" : (worst === "warning" ? "degraded" : "healthy");
  const label = worst === "critical" ? "Critical" : (worst === "warning" ? "Warning" : "Clear");
  $("overall").textContent = active.length ? `${label} · ${active.length} active` : "Clear";
  $("overall-dot").className = `status-dot ${status}`;
  $("summary").textContent = active.length
    ? "One or more conditions need attention."
    : "No active VOC/PM, sensor-freshness, or filter-mismatch alerts.";
  $("updated").textContent = new Date(data.checked_at || now).toLocaleTimeString([], {hour: "numeric", minute: "2-digit", second: "2-digit"});
  $("active-caption").textContent = data.database_error ? "Database unavailable" : "From airmonitor-alerts";

  renderActive(active, now);
  renderHistory(history, now);
}

async function refresh() {
  try {
    const response = await fetch("/alerts-api", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $("overall").textContent = "Offline";
    $("overall-dot").className = "status-dot offline";
    $("summary").textContent = "The AirMonitor alerts service is unavailable.";
  }
}

refresh();
setInterval(refresh, 15000);
