"use strict";

/* Job Vacancy Bot — Carbon console behaviour
   Talks to the Flask API (GET /api/status, POST /api/run) and renders the
   run state. No frameworks, no build step. */

const $ = (id) => document.getElementById(id);
const POLL_MS = 900;
const STATUS_LABEL = {
  idle: "Idle",
  running: "Running",
  finished: "Completed",
  failed: "Failed",
};

let pollTimer = null;
let renderedRunId = null;
let renderedLogs = 0;
let networkFailures = 0;
let lastStatus = "idle";

const form = $("run-form");
const startBtn = $("start-btn");
const formError = $("form-error");

/* ------------------------------------------------------------------ helpers */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function icon(name, className = "cds-icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${name}`);
  svg.append(use);
  return svg;
}

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortDate(value) {
  if (!value) return "";
  const text = String(value);
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : text;
}

function fileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function isHttp(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

function setStatus(status) {
  const pill = $("status-pill");
  pill.className = `cds-tag is-${status}`;
  pill.textContent = STATUS_LABEL[status] || status;
  document.title =
    status === "running"
      ? "Running · Vacancy collection"
      : "Vacancy collection · Job Vacancy Bot";
}

function setBusy(busy) {
  startBtn.disabled = busy;
  startBtn.classList.toggle("is-busy", busy);
  startBtn.querySelector(".cds-btn__label").textContent = busy ? "Running…" : "Start run";
}

/* ------------------------------------------------------------------- theme */
const themeToggle = $("theme-toggle");

function applyTheme(theme, persist = true) {
  document.documentElement.dataset.theme = theme;
  $("theme-icon").setAttribute("href", theme === "dark" ? "#i-light" : "#i-moon");
  themeToggle.setAttribute(
    "aria-label",
    theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
  );
  themeToggle.title = theme === "dark" ? "Light theme" : "Dark theme";
  if (persist) {
    try {
      localStorage.setItem("rpa-theme", theme);
    } catch (error) {
      /* storage blocked: theme still applies for this page */
    }
  }
}

themeToggle.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
});

/* ------------------------------------------------------------------- clock */
function tickClock() {
  const now = new Date();
  const clock = $("clock");
  clock.textContent = now.toLocaleTimeString([], { hour12: false });
  clock.title = now.toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/* ------------------------------------------------------------------ toasts */
function toast(message, tone = "success") {
  const root = $("toasts");
  const node = el("div", `cds-toast is-${tone}`);
  node.append(icon(tone === "error" || tone === "warn" ? "i-warning--filled" : "i-checkmark"));
  node.append(el("span", null, message));
  root.append(node);
  while (root.children.length > 3) root.removeChild(root.firstChild);

  window.setTimeout(() => {
    node.classList.add("is-leaving");
    window.setTimeout(() => node.remove(), 220);
  }, 5200);
}

/* --------------------------------------------------------------- rendering */
function renderProgress(data) {
  const bar = $("progress-bar");
  const progress = $("progress");
  const label = $("progress-label");
  const percentLabel = $("progress-percent");
  const running = data.status === "running";

  progress.classList.toggle("is-indeterminate", running && !data.total);

  let percent = 0;
  if (data.status === "finished") {
    percent = 100;
  } else if (data.total > 0) {
    percent = Math.min(100, Math.round((data.completed / data.total) * 100));
  }
  bar.style.width = `${percent}%`;
  progress.setAttribute("aria-valuenow", String(percent));
  percentLabel.textContent = data.status === "idle" ? "0%" : `${percent}%`;

  if (data.status === "idle") {
    label.textContent = "Ready — configure a run and press Start.";
    return;
  }

  if (data.status === "running") {
    if (data.phase === "discovering") {
      label.textContent = "Fetching live listings from the selected sources…";
    } else if (data.total) {
      clearNode(label);
      label.append("Collecting vacancy ");
      label.append(el("strong", null, `${data.completed} of ${data.total}`));
      if (data.current) label.append(` — ${data.current}`);
    } else {
      label.textContent = "Starting the robot…";
    }
    return;
  }

  if (data.status === "finished" && data.result) {
    const result = data.result;
    label.textContent = `Finished in ${result.duration_seconds}s — ${result.successful} new row${
      result.successful === 1 ? "" : "s"
    } written, ${result.total_rows} in the report.`;
    return;
  }

  if (data.status === "failed") {
    label.textContent = data.error || "The run failed.";
  }
}

function renderMeta(data) {
  const meta = $("run-meta");
  const panelMeta = $("run-meta-run");
  if (!data.id) {
    meta.textContent = "No run yet";
    panelMeta.textContent = "idle";
    return;
  }
  const state = data.status === "running" ? "started" : "finished";
  meta.textContent = `Run ${data.id} · ${state} ${formatTime(data.started_at)}`;
  panelMeta.textContent = data.id;
}

function renderStats(result) {
  const stats = $("stats");
  clearNode(stats);
  if (!result) return;

  const cards = [
    { label: "Discovered", value: result.discovered },
    { label: "Captured", value: result.successful, tone: "is-ok" },
    { label: "Duplicates", value: result.skipped },
    {
      label: "Outside filter",
      value: result.filtered_location,
      tone: result.filtered_location ? "is-warn" : "",
    },
    {
      label: "Keyword drops",
      value: result.filtered,
      tone: result.filtered ? "is-warn" : "",
    },
    { label: "Failed", value: result.failed, tone: result.failed ? "is-error" : "" },
    { label: "Total rows", value: result.total_rows },
    { label: "Duration", value: `${result.duration_seconds}s` },
  ];

  for (const card of cards) {
    const node = el("div", `cds-metric ${card.tone || ""}`.trim());
    node.append(el("b", null, String(card.value)));
    node.append(el("span", null, card.label));
    stats.append(node);
  }
}

function renderFlow(data) {
  const steps = Array.from(document.querySelectorAll(".cds-flow__step"));
  const lines = Array.from(document.querySelectorAll(".cds-flow__line"));
  if (!steps.length) return;

  let active = -1;
  let failed = false;

  if (!data || data.status === "idle") {
    active = -1;
  } else if (data.status === "finished") {
    active = steps.length;
  } else if (data.status === "failed") {
    failed = true;
    active = data.total ? 2 : 1;
  } else if (data.phase === "processing") {
    active = 2;
  } else if (data.phase === "discovering") {
    active = 1;
  } else if (data.status === "running") {
    active = 0;
  }

  steps.forEach((step, index) => {
    step.classList.toggle("is-done", active > index);
    step.classList.toggle("is-active", active === index && !failed);
    step.classList.toggle("is-error", failed && active === index);
  });
  lines.forEach((line, index) => {
    line.classList.toggle("is-done", !failed && active > index);
  });
}

function levelKey(level) {
  const map = { WARNING: "WARN", ERROR: "ERR", CRITICAL: "CRIT", DEBUG: "DBG" };
  return map[level] || level || "INFO";
}

function renderLogs(logs) {
  const box = $("log");
  const entries = logs || [];

  if (entries.length < renderedLogs) {
    // server trimmed the ring buffer — restart from the beginning
    clearNode(box);
    renderedLogs = 0;
  }
  if (!entries.length) return;

  if (renderedLogs === 0) clearNode(box);

  for (let i = renderedLogs; i < entries.length; i += 1) {
    const entry = entries[i];
    const key = levelKey(entry.level);
    const line = el(
      "div",
      `cds-log-line${key === "WARN" ? " is-warn" : ""}${key === "ERR" || key === "CRIT" ? " is-error" : ""}`,
    );
    line.append(el("span", "cds-log-num", String(i + 1).padStart(3, "0")));
    line.append(el("span", "cds-log-time", entry.time || ""));
    line.append(el("span", `cds-log-level ${key}`, key));
    line.append(el("span", "cds-log-msg", entry.message || ""));
    box.append(line);
  }

  renderedLogs = entries.length;
  $("log-count").textContent = `${entries.length} line${entries.length === 1 ? "" : "s"}`;
  box.scrollTop = box.scrollHeight;
}

function sourceTag(name) {
  const clean = String(name || "unknown");
  const tag = el("span", "cds-source");
  tag.append(el("i", "cds-source__mark", clean.charAt(0).toUpperCase()));
  tag.append(el("span", null, clean));
  return tag;
}

function renderResult(result) {
  const card = $("results-card");
  if (!result) {
    card.hidden = true;
    return;
  }
  card.hidden = false;

  $("results-meta").textContent =
    `${result.total_rows} rows · ${result.portal_label} · ${result.duration_seconds}s`;

  const download = $("download");
  if (result.download_url) {
    download.href = result.download_url;
    download.title = result.output || "Excel report";
    download.hidden = false;
  } else {
    download.hidden = true;
  }

  const chips = $("source-chips");
  clearNode(chips);

  for (const [name, count] of Object.entries(result.sources || {})) {
    const chip = el("span", "cds-chip");
    chip.append(el("i", "cds-chip__dot"));
    chip.append(el("b", null, name));
    chip.append(el("span", null, String(count)));
    chips.append(chip);
  }
  if (result.countries && result.countries.length) {
    const chip = el("span", "cds-chip");
    chip.append(icon("i-globe"));
    chip.append("Country");
    chip.append(el("b", null, result.countries.join(", ")));
    chips.append(chip);
  }
  if (result.keywords && result.keywords.length) {
    const chip = el("span", "cds-chip");
    chip.append(icon("i-filter"));
    chip.append("Keywords");
    chip.append(el("b", null, result.keywords.join(", ")));
    chips.append(chip);
  }

  const body = $("jobs-body");
  clearNode(body);

  if (!result.jobs.length) {
    const row = el("tr");
    const cell = el("td");
    cell.colSpan = 7;
    const empty = el("div", "cds-empty");
    empty.append(icon("i-table"));
    empty.append(el("b", null, "No vacancies matched this run"));
    empty.append(el("span", null, "Loosen the country or keyword filters and try again."));
    cell.append(empty);
    row.append(cell);
    body.append(row);
  } else {
    for (const job of result.jobs) {
      const row = el("tr");

      const vacancy = el("td", "cds-cell-vacancy");
      vacancy.append(el("span", "cds-job-title", job.title || "—"));
      vacancy.append(el("span", "cds-job-company", job.company || "—"));
      row.append(vacancy);

      row.append(el("td", "cds-cell-muted", job.location || "—"));

      const arrangement = [job.work_mode, job.employment_type]
        .filter((value) => value && value !== "Unspecified")
        .join(" · ");
      row.append(el("td", "cds-cell-muted", arrangement || "—"));

      row.append(el("td", "cds-cell-muted", job.salary || "—"));
      row.append(el("td", "cds-cell-date", shortDate(job.posted_date) || "—"));

      const source = el("td");
      source.append(sourceTag(job.portal));
      row.append(source);

      const applyCell = el("td");
      const href = job.apply_url || "";
      if (isHttp(href)) {
        const link = el("a", "cds-apply");
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.append(el("span", null, "Apply"));
        link.append(icon("i-launch"));
        applyCell.append(link);
      } else {
        applyCell.append(el("span", "cds-cell-muted", "—"));
      }
      row.append(applyCell);

      body.append(row);
    }
  }

  const note = $("preview-note");
  if (result.preview_truncated) {
    note.hidden = false;
    note.textContent = `Showing the first ${result.jobs.length} of ${result.total_rows} rows — the full list is in the Excel report.`;
  } else {
    note.hidden = true;
  }
}

function renderReports(reports) {
  const body = $("reports-body");
  clearNode(body);

  if (!reports || !reports.length) {
    const row = el("tr");
    const cell = el("td");
    cell.colSpan = 4;
    const empty = el("div", "cds-empty");
    empty.append(icon("i-document"));
    empty.append(el("b", null, "No reports yet"));
    empty.append(el("span", null, "The first run will write its workbook here."));
    cell.append(empty);
    row.append(cell);
    body.append(row);
    return;
  }

  for (const report of reports) {
    const row = el("tr");

    const nameCell = el("td");
    const name = el("div", "cds-report-name");
    name.append(icon("i-document"));
    name.append(el("span", null, report.name));
    nameCell.append(name);
    row.append(nameCell);

    row.append(el("td", "cds-report-size", fileSize(report.size)));
    row.append(el("td", "cds-report-date", formatTime(report.modified)));

    const actionCell = el("td");
    const link = el("a", "cds-report-download");
    link.href = report.download_url;
    link.setAttribute("aria-label", `Download ${report.name}`);
    link.title = `Download ${report.name}`;
    link.append(icon("i-download"));
    actionCell.append(link);
    row.append(actionCell);

    body.append(row);
  }
}

function resetRunView() {
  renderedLogs = 0;
  clearNode($("log"));
  clearNode($("stats"));
  renderResult(null);
  $("log-count").textContent = "";
  const box = $("log");
  const empty = el("div", "cds-log__empty");
  empty.append(icon("i-terminal"));
  empty.append(el("span", null, "Log lines stream here once the robot starts."));
  box.append(empty);
}

/* ------------------------------------------------------------------ polling */
function applyStatus(data) {
  setStatus(data.status);

  if (renderedRunId !== data.id) {
    renderedRunId = data.id;
    resetRunView();
  }

  renderMeta(data);
  renderProgress(data);
  renderFlow(data);
  renderLogs(data.logs);
  if (data.result) {
    renderStats(data.result);
    renderResult(data.result);
  }
  renderReports(data.reports);

  setBusy(data.status === "running");
}

async function poll() {
  try {
    const response = await fetch("/api/status", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`status ${response.status}`);
    const data = await response.json();
    networkFailures = 0;

    const previous = lastStatus;
    lastStatus = data.status;
    applyStatus(data);

    if (data.status !== "running") {
      stopPolling();
      formError.textContent = "";
      if (data.status === "finished" && previous === "running" && data.result) {
        toast(
          `Run complete — ${data.result.successful} new row${
            data.result.successful === 1 ? "" : "s"
          }, report saved.`,
          "success",
        );
      } else if (data.status === "failed" && previous === "running") {
        toast(data.error || "The run failed.", "error");
      }
    }
  } catch (error) {
    networkFailures += 1;
    if (networkFailures >= 4) {
      stopPolling();
      formError.textContent = "Lost contact with the bot server. Check the terminal window.";
      toast("Lost contact with the bot server.", "error");
      setBusy(false);
    }
  }
}

function startPolling() {
  stopPolling();
  poll();
  pollTimer = window.setInterval(poll, POLL_MS);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

/* ------------------------------------------------------------------- form */
function formPayload() {
  return {
    portal: $("portal").value,
    limit: Number($("limit").value),
    countries: $("countries").value,
    keywords: $("keywords").value,
    match: $("match").value,
    fetch_details: $("fetch_details").checked,
    append: $("append").checked,
    filename: $("filename").value,
    delay: $("delay").value,
  };
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";

  const limit = Number($("limit").value);
  if (!Number.isFinite(limit) || limit < 1 || limit > 500) {
    formError.textContent = "Maximum vacancies must be between 1 and 500.";
    toast("Maximum vacancies must be between 1 and 500.", "warn");
    return;
  }

  const delayRaw = $("delay").value;
  if (delayRaw !== "" && (Number.isNaN(Number(delayRaw)) || Number(delayRaw) < 0 || Number(delayRaw) > 30)) {
    formError.textContent = "Request delay must be between 0 and 30 seconds.";
    toast("Request delay must be between 0 and 30 seconds.", "warn");
    return;
  }

  setBusy(true);
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(formPayload()),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = data.error || `Could not start the run (${response.status}).`;
      formError.textContent = message;
      toast(message, "error");
      setBusy(false);
      return;
    }

    renderedRunId = data.id;
    lastStatus = "running";
    resetRunView();
    setStatus("running");
    renderMeta(data);
    renderProgress(data);
    startPolling();

    if (window.innerWidth < 1056) {
      $("run").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    formError.textContent = "Could not reach the bot server.";
    toast("Could not reach the bot server.", "error");
    setBusy(false);
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    form.requestSubmit();
  }
});

if (/Mac|iPhone|iPad/.test(navigator.platform || "")) {
  const hint = document.querySelector(".cds-btn__kbd");
  if (hint) hint.textContent = "⌘ ↵";
}

$("append").addEventListener("change", (event) => {
  const filename = $("filename");
  if (event.target.checked && !filename.value.trim()) {
    filename.value = "web_jobs.xlsx";
  }
});

/* -------------------------------------------------------------- navigation */
function setActiveSection(sectionId) {
  for (const link of document.querySelectorAll(".cds-sidenav__item[data-section]")) {
    const active = link.dataset.section === sectionId;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

function updateNav() {
  if (window.scrollY < 90) {
    setActiveSection("top");
    return;
  }
  const ids = ["config", "results-card", "report-library"].filter((id) => {
    const node = document.getElementById(id);
    return node && !node.hidden;
  });
  if (!ids.length) {
    setActiveSection("top");
    return;
  }

  let active = ids[0];
  const threshold = Math.min(200, window.innerHeight * 0.28);
  for (const id of ids) {
    if (document.getElementById(id).getBoundingClientRect().top <= threshold) active = id;
  }

  const atBottom =
    window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 8;
  if (atBottom) active = ids[ids.length - 1];
  setActiveSection(active);
}

for (const link of document.querySelectorAll(".cds-sidenav__item[data-section]")) {
  link.addEventListener("click", () => setActiveSection(link.dataset.section));
}

let navTick = false;
window.addEventListener(
  "scroll",
  () => {
    if (navTick) return;
    navTick = true;
    window.requestAnimationFrame(() => {
      navTick = false;
      updateNav();
    });
  },
  { passive: true },
);

/* -------------------------------------------------------------------- boot */
applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light", false);
tickClock();
window.setInterval(tickClock, 1000);
updateNav();
startPolling();
