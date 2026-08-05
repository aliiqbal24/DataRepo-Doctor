"use strict";

const INTERVALS = [5, 15, 30, 60, 120, 360, 720, 1440];
const body = document.querySelector("#checks-body");
const banner = document.querySelector("#error-banner");
const loading = document.querySelector("#loading");
let requestInFlight = false;

function node(tag, className, text) {
  const value = document.createElement(tag);
  if (className) value.className = className;
  if (text !== undefined) value.textContent = text;
  return value;
}

function label(value) {
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function relativeTime(value) {
  if (!value) return "Never";
  const delta = new Date(value).getTime() - Date.now();
  const minutes = Math.round(Math.abs(delta) / 60000);
  if (minutes < 1) return delta < 0 ? "Just now" : "In <1m";
  if (minutes < 60) return delta < 0 ? `${minutes}m ago` : `In ${minutes}m`;
  const hours = Math.round(minutes / 60);
  return delta < 0 ? `${hours}h ago` : `In ${hours}h`;
}

function detailItem(term, description, code = false) {
  const wrapper = node("div");
  wrapper.append(node("dt", "", term));
  const value = node("dd");
  value.append(code ? node("code", "", description) : document.createTextNode(description));
  wrapper.append(value);
  return wrapper;
}

function detailSection(title) {
  const section = node("section", "detail-section");
  section.append(node("h3", "", title));
  return section;
}

function retrievalDetail(check) {
  const section = detailSection("Retrieval path");
  const grid = node("dl", "detail-grid");
  grid.append(
    detailItem("Catalog", check.catalog), detailItem("Database", check.database),
    detailItem("Table", check.table), detailItem("Access", label(check.access_method)),
    detailItem("Environment", check.environment), detailItem("Identity", check.credential_profile),
  );
  section.append(grid, node("p", "query-copy", check.query_description));
  return section;
}

function sourceDetail(check) {
  const section = detailSection("Data source");
  const grid = node("dl", "detail-grid");
  grid.append(
    detailItem("Owner", check.source_owner), detailItem("Version", check.source_version),
    detailItem("License", check.source_license), detailItem("Location", check.source_uri, true),
  );
  section.append(grid);
  if (check.source_documentation_url) {
    const link = node("a", "", "Source documentation");
    link.href = check.source_documentation_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    section.append(link);
  }
  return section;
}

function queryCodeDetail(check) {
  const section = detailSection("Query code");
  const pre = node("pre", "query-code");
  pre.append(node("code", "", check.query_code));
  section.append(pre);
  return section;
}

function outcomeDetail(check) {
  const section = detailSection("Latest completed run");
  const outcome = check.latest_outcome;
  if (!outcome) {
    section.append(node("p", "", "No completed run yet."));
    return section;
  }
  if (outcome.health === "healthy") {
    const metric = node("div", "hero-metric");
    metric.append(node("strong", "", outcome.user_query_latency_ms.toFixed(1)), node("span", "", "ms user query latency"));
    const phases = node("div", "phases");
    for (const phase of outcome.phase_timings) {
      const row = node("div");
      row.append(node("span", "", label(phase.name)), node("strong", "", `${phase.duration_ms.toFixed(1)} ms`));
      phases.append(row);
    }
    section.append(metric, phases, node("p", "total", `Total probe duration ${outcome.total_probe_duration_ms.toFixed(1)} ms`));
  } else {
    const failure = node("div", "failure-box");
    const stage = node("div");
    stage.append(node("span", "", "Stage"), node("strong", "", label(outcome.failure_stage || "unknown")));
    const mode = node("div");
    mode.append(node("span", "", "Mode"), node("strong", "", label(outcome.failure_mode || "unknown")));
    failure.append(stage, mode, node("p", "", outcome.failure_summary || "The check failed."));
    if (outcome.failure_detail) failure.append(node("code", "failure-detail", outcome.failure_detail));
    section.append(failure);
  }
  return section;
}

function receivedDataDetail(check) {
  const section = detailSection("Received data");
  const outcome = check.latest_outcome;
  if (!outcome) {
    section.append(node("p", "", "Run this check to see the returned data."));
    return section;
  }
  if (outcome.health !== "healthy") {
    section.append(node("p", "", "No data is shown because the retrieval failed."));
    return section;
  }
  if (!check.displays_result_rows) {
    section.append(node("p", "", "Result display is disabled for this check."));
    return section;
  }
  const rows = outcome.result_rows || [];
  if (!rows.length) {
    section.append(node("p", "", "The query successfully returned zero rows."));
    return section;
  }

  const columns = Object.keys(rows[0]);
  const table = node("table", "received-table");
  const head = node("thead");
  const headingRow = node("tr");
  for (const column of columns) headingRow.append(node("th", "", column));
  head.append(headingRow);
  const tableBody = node("tbody");
  for (const row of rows) {
    const tableRow = node("tr");
    for (const column of columns) {
      const value = row[column];
      const display = value === null ? "null" : typeof value === "object" ? JSON.stringify(value) : String(value);
      tableRow.append(node("td", "", display));
    }
    tableBody.append(tableRow);
  }
  table.append(head, tableBody);
  const wrapper = node("div", "received-data-scroll");
  wrapper.append(table);
  section.append(node("p", "result-count", `${rows.length} rows returned`), wrapper);
  return section;
}

function buildRows(check, expandedIds) {
  const row = node("tr", "check-row");
  row.dataset.checkId = check.check_id;

  const nameCell = node("td");
  const toggle = node("button", "check-link");
  toggle.type = "button";
  toggle.dataset.focusKey = `detail-${check.check_id}`;
  toggle.setAttribute("aria-expanded", String(expandedIds.has(check.check_id)));
  toggle.setAttribute("aria-controls", `detail-${check.check_id}`);
  toggle.append(node("strong", "", check.display_name), node("span", "", check.description));
  nameCell.append(toggle);

  const sourceCell = node("td");
  sourceCell.append(node("strong", "", check.physical_source), node("span", "method", check.access_method === "python_sdk" ? "Python SDK" : "ROAPI HTTP"));

  const stateCell = node("td");
  const stack = node("div", "state-stack");
  const health = check.latest_outcome?.health;
  const badge = node("span", `health ${health || "never"}`, health ? label(health) : "Never checked");
  stack.append(badge);
  if (check.job.status !== "idle") stack.append(node("span", "job-state", label(check.job.status)));
  stateCell.append(stack);

  const latency = node("td", "latency", health === "healthy" ? `${check.latest_outcome.user_query_latency_ms.toFixed(1)} ms` : "—");
  const checked = node("td", "", relativeTime(check.latest_outcome?.checked_at));
  checked.title = check.latest_outcome?.checked_at || "";
  const next = node("td", "", check.schedule.enabled ? relativeTime(check.schedule.next_run_at) : "Disabled");
  next.title = check.schedule.next_run_at;

  const scheduleCell = node("td", "schedule-controls");
  const select = node("select");
  select.dataset.focusKey = `interval-${check.check_id}`;
  select.setAttribute("aria-label", `Interval for ${check.display_name}`);
  const availableIntervals = INTERVALS.includes(check.schedule.interval_minutes)
    ? INTERVALS
    : [...INTERVALS, check.schedule.interval_minutes].sort((left, right) => left - right);
  for (const minutes of availableIntervals) {
    const option = node("option", "", minutes < 60 ? `${minutes}m` : `${minutes / 60}h`);
    option.value = String(minutes);
    option.selected = minutes === check.schedule.interval_minutes;
    select.append(option);
  }
  select.addEventListener("change", () => updateSchedule(check.check_id, { interval_minutes: Number(select.value) }));
  const enabledLabel = node("label", "enabled-control");
  const enabled = node("input");
  enabled.type = "checkbox";
  enabled.checked = check.schedule.enabled;
  enabled.dataset.focusKey = `enabled-${check.check_id}`;
  enabled.addEventListener("change", () => updateSchedule(check.check_id, { enabled: enabled.checked }));
  enabledLabel.append(enabled, document.createTextNode("Enabled"));
  scheduleCell.append(select, enabledLabel);

  const actionCell = node("td");
  const run = node("button", "run-button", check.job.status === "idle" ? "Check now" : label(check.job.status));
  run.type = "button";
  run.disabled = check.job.status !== "idle";
  run.dataset.focusKey = `run-${check.check_id}`;
  run.addEventListener("click", () => runCheck(check.check_id));
  actionCell.append(run);
  row.append(nameCell, sourceCell, stateCell, latency, checked, next, scheduleCell, actionCell);

  const detailRow = node("tr", "detail-row");
  detailRow.id = `detail-${check.check_id}`;
  detailRow.dataset.detailId = check.check_id;
  detailRow.hidden = !expandedIds.has(check.check_id);
  const detailCell = node("td");
  detailCell.colSpan = 8;
  const detailGrid = node("div", "expanded-detail");
  detailGrid.append(
    retrievalDetail(check),
    sourceDetail(check),
    queryCodeDetail(check),
    outcomeDetail(check),
    receivedDataDetail(check),
  );
  detailCell.append(detailGrid);
  detailRow.append(detailCell);

  toggle.addEventListener("click", () => {
    detailRow.hidden = !detailRow.hidden;
    toggle.setAttribute("aria-expanded", String(!detailRow.hidden));
  });
  return [row, detailRow];
}

function render(checks) {
  const expandedIds = new Set([...document.querySelectorAll("[data-detail-id]:not([hidden])")].map((row) => row.dataset.detailId));
  const focusKey = document.activeElement?.dataset?.focusKey;
  body.replaceChildren();
  for (const check of checks) body.append(...buildRows(check, expandedIds));
  document.querySelector("#healthy-count").textContent = String(checks.filter((check) => check.latest_outcome?.health === "healthy").length);
  document.querySelector("#unhealthy-count").textContent = String(checks.filter((check) => check.latest_outcome?.health === "unhealthy").length);
  document.querySelector("#unchecked-count").textContent = String(checks.filter((check) => !check.latest_outcome).length);
  loading.hidden = checks.length > 0;
  if (focusKey) document.querySelector(`[data-focus-key="${CSS.escape(focusKey)}"]`)?.focus();
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`Request failed with HTTP ${response.status}`);
  return response.json();
}

async function loadChecks() {
  if (requestInFlight) return;
  requestInFlight = true;
  try {
    render(await api("/api/checks"));
    banner.hidden = true;
  } catch (_error) {
    banner.textContent = "Dashboard data is temporarily unavailable.";
    banner.hidden = false;
  } finally {
    requestInFlight = false;
  }
}

async function runCheck(checkId) {
  try {
    await api(`/api/checks/${encodeURIComponent(checkId)}/run`, { method: "POST" });
    await loadChecks();
  } catch (_error) {
    banner.textContent = "The check could not be queued.";
    banner.hidden = false;
  }
}

async function updateSchedule(checkId, patch) {
  try {
    await api(`/api/checks/${encodeURIComponent(checkId)}/schedule`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    });
    await loadChecks();
  } catch (_error) {
    banner.textContent = "The schedule could not be updated.";
    banner.hidden = false;
  }
}

loadChecks();
window.setInterval(loadChecks, 2000);
