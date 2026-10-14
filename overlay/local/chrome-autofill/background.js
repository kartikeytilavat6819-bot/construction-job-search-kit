// career-ops Autofill: service worker.
// Keeps track of which tabs are "armed", injects content.js into every frame of an armed tab
// (again after each navigation, so multi-page forms keep filling), fetches the tailored PDFs
// and your answers from docs_server.py, and relays each frame's report to the top frame's panel.
// It also reloads itself when its files change on disk, so it never needs reinstalling.

const SERVER = "http://127.0.0.1:3001"; // docs_server.py
const reports = new Map(); // tabId -> Map(frameId -> {filled, needs})
const fileCache = new Map(); // "n:kind" -> {name, type, b64}

// Armed tabs live in storage.local (storage.session is wiped when the extension reloads itself).
const armedKey = (tabId) => `armed:${tabId}`;
async function getArmed(tabId) {
  return (await chrome.storage.local.get(armedKey(tabId)))[armedKey(tabId)] || null;
}

async function getProfile() {
  const { profileOverride } = await chrome.storage.local.get("profileOverride"); // used only by the test harness
  let p = profileOverride;
  if (!p) {
    try {
      p = await (await fetch(`${SERVER}/profile`, { cache: "no-store" })).json(); // fresh: edits apply at once
    } catch {
      p = await (await fetch(chrome.runtime.getURL("profile.json"))).json(); // helper down: bundled copy
    }
  }
  if (p.city && p.state && p.location == null) p.location = `${p.city}, ${p.state}`;
  return p;
}

async function inject(tabId, frameIds) {
  try {
    await chrome.scripting.executeScript({
      target: frameIds ? { tabId, frameIds } : { tabId, allFrames: true },
      files: ["content.js"],
    });
  } catch {
    // chrome:// pages, PDF viewers and frames we cannot reach: nothing to fill there
  }
}

function toB64(buf) {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

// The name the employer sees on the upload: "First_Last_Resume.pdf" from profile.json, else "Resume.pdf".
async function uploadName(kind) {
  let p = {};
  try { p = await getProfile(); } catch { /* helper down and no bundled profile.json */ }
  const who = [p.first_name, p.last_name].filter(Boolean).join(" ") || p.full_name || "";
  const base = who.normalize("NFKD").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const doc = kind === "cover" ? "Cover_Letter" : "Resume";
  return base ? `${base}_${doc}.pdf` : `${doc}.pdf`;
}

// kind: "resume" | "cover". Returns null when the report names no PDF for that application.
async function getFile(n, kind) {
  const cacheKey = `${n}:${kind}`;
  if (fileCache.has(cacheKey)) return fileCache.get(cacheKey);
  const res = await fetch(`${SERVER}/file?n=${encodeURIComponent(n)}&kind=${kind}`, { cache: "no-store" });
  if (!res.ok) return null;
  const file = {
    name: await uploadName(kind),
    type: "application/pdf",
    b64: toB64(await res.arrayBuffer()),
  };
  fileCache.set(cacheKey, file);
  return file;
}

// content.js and the popup are read from disk every time they load, so edits to them apply on
// the next page by themselves. Only this file and manifest.json need a reload; docs_server.py
// fingerprints those two, and the popup offers a one-click "Update ready" button when they change.
async function helperVersion() {
  try {
    return (await (await fetch(`${SERVER}/version`, { cache: "no-store" })).json()).version;
  } catch {
    return null; // helper not running
  }
}
async function updateReady() {
  const [now, { extVersion }] = await Promise.all([helperVersion(), chrome.storage.local.get("extVersion")]);
  return !!(now && extVersion && now !== extVersion);
}

async function handle(msg, sender) {
  const tabId = msg.tabId ?? sender.tab?.id;
  switch (msg.type) {
    case "updateReady":
      return updateReady();
    case "applyUpdate":
      chrome.runtime.reload(); // you clicked "Update ready"; armed tabs resume via onInstalled
      return true;
    case "jobs": {
      fileCache.clear(); // PDFs may have been regenerated since
      const res = await fetch(`${SERVER}/jobs`, { cache: "no-store" });
      if (!res.ok) throw new Error(`helper answered ${res.status}`);
      return res.json();
    }
    case "status":
      return getArmed(tabId);
    case "seen": { // the tracked posting this tab came from, if any
      const k = `seen:${tabId}`;
      return (await chrome.storage.session.get(k))[k] || null;
    }
    case "start":
      await chrome.storage.local.set({ [armedKey(tabId)]: msg.job });
      reports.delete(tabId);
      await inject(tabId);
      chrome.tabs.sendMessage(tabId, { type: "start" }).catch(() => {}); // frames that were stopped earlier
      return true;
    case "stop":
      await chrome.storage.local.remove(armedKey(tabId));
      reports.delete(tabId);
      chrome.tabs.sendMessage(tabId, { type: "stop" }).catch(() => {});
      return true;
    case "config": {
      const job = await getArmed(tabId);
      return job ? { job, profile: await getProfile() } : null;
    }
    case "answers": { // the report's drafted answers, cover letter text and the posting's top pay
      const job = await getArmed(tabId);
      if (!job?.n) return null;
      const res = await fetch(`${SERVER}/answers?n=${encodeURIComponent(job.n)}`, { cache: "no-store" }).catch(() => null);
      return res && res.ok ? res.json() : null;
    }
    case "file": {
      const job = await getArmed(tabId);
      return job?.n ? getFile(job.n, msg.kind) : null;
    }
    case "report": {
      if (sender.documentLifecycle && sender.documentLifecycle !== "active") return true; // a page you already left
      if (!reports.has(tabId)) reports.set(tabId, new Map());
      reports.get(tabId).set(sender.frameId, { filled: msg.filled, needs: msg.needs });
      const all = [...reports.get(tabId).values()];
      const needs = all.flatMap((r) => r.needs).sort((a, b) => b.required - a.required);
      const data = { job: await getArmed(tabId), filled: all.flatMap((r) => r.filled), needs: needs.slice(0, 40) };
      chrome.tabs.sendMessage(tabId, { type: "panel", data }, { frameId: 0 }).catch(() => {});
      return true;
    }
  }
  return null;
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  handle(msg, sender).then(
    (result) => reply({ ok: true, result }),
    (err) => reply({ ok: false, error: String(err?.message || err) }),
  );
  return true; // async reply
});

// ---------- which tracked job is this tab on? ----------
// When a tab opens one of your tracked postings, remember it, so the application pages that follow
// (different addresses, often a different site) still know which job they belong to.
let jobsCache = { at: 0, list: [] };
async function jobList() {
  if (Date.now() - jobsCache.at < 60000) return jobsCache.list;
  try {
    jobsCache = { at: Date.now(), list: await (await fetch(`${SERVER}/jobs`, { cache: "no-store" })).json() };
  } catch {
    /* helper down: keep what we had */
  }
  return jobsCache.list;
}
const idIn = (id, s) => new RegExp(`(^|[^a-z0-9])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z0-9]|$)`, "i").test(s);
function jobForUrl(url, list) {
  const bare = (u) => (u || "").split(/[?#]/)[0].replace(/\/+$/, "").toLowerCase();
  return list.find((j) => j.url && bare(url).startsWith(bare(j.url))) || list.find((j) => (j.ids || []).some((id) => idIn(id, url)));
}
chrome.webNavigation.onCommitted.addListener(async ({ tabId, frameId, url }) => {
  if (frameId !== 0 || !/^https?:/.test(url)) return;
  const j = jobForUrl(url, await jobList());
  if (j) chrome.storage.session.set({ [`seen:${tabId}`]: { n: j.n, url } });
});
chrome.tabs.onCreated.addListener(async (tab) => { // "Apply" that opens a new tab inherits the posting's job
  if (!tab.openerTabId) return;
  const k = `seen:${tab.openerTabId}`;
  const seen = (await chrome.storage.session.get(k))[k];
  if (seen) chrome.storage.session.set({ [`seen:${tab.id}`]: seen });
});

// Re-inject after every page load (including iframes that load later) while the tab is armed.
chrome.webNavigation.onCompleted.addListener(async ({ tabId, frameId }) => {
  if (await getArmed(tabId)) inject(tabId, [frameId]);
});

// A new top-level page means a fresh report.
chrome.webNavigation.onCommitted.addListener(({ tabId, frameId }) => {
  if (frameId === 0) reports.delete(tabId);
});

chrome.tabs.onRemoved.addListener((tabId) => {
  reports.delete(tabId);
  chrome.storage.local.remove(armedKey(tabId));
  chrome.storage.session.remove(`seen:${tabId}`);
});

// Tab ids do not survive a browser restart, so forget armed tabs then.
chrome.runtime.onStartup.addListener(async () => {
  const all = await chrome.storage.local.get(null);
  await chrome.storage.local.remove(Object.keys(all).filter((k) => k.startsWith("armed:")));
});

// Install and every reload: remember which version is running, and resume filling in armed tabs.
chrome.runtime.onInstalled.addListener(async () => {
  const v = await helperVersion();
  if (v) await chrome.storage.local.set({ extVersion: v });
  const all = await chrome.storage.local.get(null);
  for (const k of Object.keys(all)) {
    if (!k.startsWith("armed:")) continue;
    const tabId = Number(k.slice(6));
    chrome.tabs.get(tabId).then(() => inject(tabId), () => chrome.storage.local.remove(k));
  }
});
