"use strict";

const RUNNER_POLL_MS = 1000;
const FILE_POLL_MS = 60000;

// Sort state for the runners table. Default: by UUID ascending.
const runnerSort = { key: "uuid", dir: 1 };
let latestRunnerRows = [];

function formatDuration(totalSec) {
  if (totalSec === null || totalSec === undefined) return "–";
  const s = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function formatHeartbeat(ts) {
  if (!ts) return "–";
  const ageSec = Math.max(0, Date.now() / 1000 - ts);
  if (ageSec < 2) return "just now";
  if (ageSec < 60) return `${Math.floor(ageSec)}s ago`;
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

function shortUuid(u) {
  return u && u.length > 12 ? `${u.slice(0, 8)}…${u.slice(-4)}` : u;
}

async function refreshRunners() {
  try {
    const resp = await fetch("/runner-status");
    if (!resp.ok) throw new Error(`status ${resp.status}`);
    const rows = await resp.json();
    latestRunnerRows = Array.isArray(rows) ? rows : [];
    renderRunners(latestRunnerRows);
    document.getElementById("last-updated").textContent =
      `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    document.getElementById("last-updated").textContent =
      `Fetch error: ${err.message}`;
  }
}

function compareRunners(a, b, key) {
  const va = a?.[key];
  const vb = b?.[key];
  // Null/undefined always sort last regardless of direction.
  const aNil = va === null || va === undefined;
  const bNil = vb === null || vb === undefined;
  if (aNil && bNil) return 0;
  if (aNil) return 1;
  if (bNil) return -1;
  if (typeof va === "number" && typeof vb === "number") return va - vb;
  return String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: "base" });
}

function renderRunners(rows) {
  const tbody = document.querySelector("#runners-table tbody");
  if (!rows || rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="muted">No runners registered.</td></tr>`;
    updateSortIndicators();
    return;
  }
  const sorted = [...rows].sort((a, b) => runnerSort.dir * compareRunners(a, b, runnerSort.key));
  tbody.innerHTML = sorted.map(r => {
    const turn = r.turn ?? "–";
    const time = formatDuration(r.timeElapsedSec);
    const badge = `<span class="badge ${r.state}">${r.state}</span>`;
    const addr = (r.url || "").replace(/^https?:\/\//, "");
    const gameId = r.gameId ?? "–";
    const u = r.uuid;
    const successes = r.successCount ?? 0;
    const failures = r.failureCount ?? 0;
    const actions = `
      <button class="btn btn-start btn-sm"   data-action="start"   data-uuid="${u}">Start</button>
      <button class="btn btn-stop  btn-sm"   data-action="stop"    data-uuid="${u}">Stop</button>
      <button class="btn btn-install btn-sm" data-action="install" data-uuid="${u}">Install Modpack</button>
    `;
    return `<tr>
      <td class="uuid" title="${u}">${shortUuid(u)}</td>
      <td class="addr">${addr}</td>
      <td>${r.modpack ?? "–"}</td>
      <td>${badge}</td>
      <td>${turn}</td>
      <td>${time}</td>
      <td class="gameid" title="${gameId}">${gameId}</td>
      <td class="actions">${actions}</td>
      <td class="num">${successes}</td>
      <td class="num">${failures}</td>
    </tr>`;
  }).join("");
  updateSortIndicators();
}

function updateSortIndicators() {
  document.querySelectorAll("#runners-table th.sortable").forEach(th => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sortKey === runnerSort.key) {
      th.classList.add(runnerSort.dir === 1 ? "sort-asc" : "sort-desc");
    }
  });
}

async function refreshFiles() {
  try {
    const resp = await fetch("/file-status");
    if (!resp.ok) return;
    const data = await resp.json();
    renderFiles(data);
  } catch (_e) {
    // ignore

// --- Sort header click handlers ---------------------------------------

document.querySelectorAll("#runners-table th.sortable").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.sortKey;
    if (!key) return;
    if (runnerSort.key === key) {
      runnerSort.dir = -runnerSort.dir;
    } else {
      runnerSort.key = key;
      runnerSort.dir = 1;
    }
    renderRunners(latestRunnerRows);
  });
});
updateSortIndicators();
  }
}

function renderFiles(data) {
  const tbody = document.querySelector("#files-table tbody");
  const modpacks = new Set([
    ...Object.keys(data.complete || {}),
    ...Object.keys(data.failed || {}),
  ]);
  if (modpacks.size === 0) {
    tbody.innerHTML = `<tr><td colspan="3" class="muted">No data yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = Array.from(modpacks).sort().map(mp => `
    <tr>
      <td>${mp}</td>
      <td>${(data.complete || {})[mp] ?? 0}</td>
      <td>${(data.failed || {})[mp] ?? 0}</td>
    </tr>
  `).join("");
}

refreshRunners();
refreshFiles();
setInterval(refreshRunners, RUNNER_POLL_MS);
setInterval(refreshFiles, FILE_POLL_MS);

// --- Control buttons --------------------------------------------------

const statusEl = document.getElementById("control-status");
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const btnInstall = document.getElementById("btn-install");
const fileInput = document.getElementById("modpack-file");

function setBusy(busy, msg) {
  [btnStart, btnStop, btnInstall].forEach(b => b.disabled = busy);
  if (msg !== undefined) statusEl.textContent = msg;
}

function summarize(results) {
  if (!results || typeof results !== "object") return "done";
  const entries = Object.entries(results);
  if (entries.length === 0) return "no runners registered";
  const ok = entries.filter(([, v]) => v.status >= 200 && v.status < 300).length;
  const skipped = entries.filter(([, v]) => v.status === 304).length;
  const failed = entries.length - ok - skipped;
  const parts = [`${ok} ok`];
  if (skipped) parts.push(`${skipped} skipped`);
  if (failed) parts.push(`${failed} failed`);
  return parts.join(", ");
}

async function broadcast(path, init) {
  setBusy(true, `POST ${path}…`);
  try {
    const resp = await fetch(path, init ?? { method: "POST" });
    const body = await resp.json().catch(() => ({}));
    const results = body.results ?? body;
    statusEl.textContent = `${path}: ${summarize(results)}`;
  } catch (err) {
    statusEl.textContent = `${path}: ${err.message}`;
  } finally {
    setBusy(false);
    refreshRunners();
  }
}

btnStart.addEventListener("click", () => broadcast("/control/start-all"));
btnStop.addEventListener("click", () => broadcast("/control/stop-all"));
btnInstall.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", async () => {
  const f = fileInput.files && fileInput.files[0];
  if (!f) return;
  const form = new FormData();
  form.append("file", f, f.name);
  await broadcast("/control/install-modpack", { method: "POST", body: form });
  fileInput.value = "";
});

// --- Per-row action buttons (event delegation) ------------------------

const rowFileInput = document.getElementById("row-modpack-file");
let pendingInstallUuid = null;

async function perRunner(path, uuid, init) {
  setBusy(true, `POST ${path}…`);
  try {
    const resp = await fetch(path, init ?? { method: "POST" });
    const body = await resp.json().catch(() => ({}));
    const short = uuid.slice(0, 8);
    statusEl.textContent = `${path} [${short}]: ${resp.status} ${JSON.stringify(body)}`;
  } catch (err) {
    statusEl.textContent = `${path}: ${err.message}`;
  } finally {
    setBusy(false);
    refreshRunners();
  }
}

document.querySelector("#runners-table tbody").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-action]");
  if (!btn) return;
  const uuid = btn.dataset.uuid;
  const action = btn.dataset.action;
  if (action === "start") {
    perRunner(`/control/start/${uuid}`, uuid);
  } else if (action === "stop") {
    perRunner(`/control/stop/${uuid}`, uuid);
  } else if (action === "install") {
    pendingInstallUuid = uuid;
    rowFileInput.click();
  }
});

rowFileInput.addEventListener("change", async () => {
  const f = rowFileInput.files && rowFileInput.files[0];
  const uuid = pendingInstallUuid;
  pendingInstallUuid = null;
  rowFileInput.value = "";
  if (!f || !uuid) return;
  const form = new FormData();
  form.append("file", f, f.name);
  await perRunner(`/control/install-modpack/${uuid}`, uuid, { method: "POST", body: form });
});
