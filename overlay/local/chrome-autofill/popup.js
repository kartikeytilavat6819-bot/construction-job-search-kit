// Popup: works out which tracked job this page belongs to (job number in the address or on the page,
// the posting this tab came from, company and title), shows the files that will be attached, then arms
// the tab. The full list is only shown when it can't tell, or when you click "Not this job?".
const $ = (id) => document.getElementById(id);
const send = (msg) => chrome.runtime.sendMessage(msg).then((r) => {
  if (!r || !r.ok) throw new Error(r ? r.error : "no reply");
  return r.result;
});
const STOP = new Set(["the", "and", "of", "inc", "llc", "usa", "us", "group", "company", "corporation", "corp",
  "city", "international", "consulting", "construction", "building", "engineering", "engineers", "formerly",
  "commonwealth", "massachusetts", "co", "level", "entry", "graduate", "new", "grad"]);
const tokens = (s) => (s || "").toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length >= 3 && !STOP.has(t));
const idIn = (id, s) => new RegExp(`(^|[^a-z0-9])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z0-9]|$)`, "i").test(s || "");
const bare = (u) => (u || "").split(/[?#]/)[0].replace(/\/+$/, "").toLowerCase();

let tab, jobs = [];

// What the page shows: every frame's address, the title and headings, and the start of the text.
async function pageSignals() {
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => ({
        url: location.href,
        title: document.title,
        head: [...document.querySelectorAll("h1,h2,[data-automation-id=jobPostingHeader]")].slice(0, 4).map((e) => e.innerText).join(" | ").slice(0, 400),
        text: (document.body ? document.body.innerText : "").slice(0, 6000),
      }),
    });
    const f = res.map((r) => r.result).filter(Boolean);
    return { urls: f.map((x) => x.url), head: f.map((x) => x.title + " | " + x.head).join(" | "), text: f.map((x) => x.text).join("\n") };
  } catch {
    return { urls: [tab.url], head: tab.title || "", text: "" }; // chrome:// pages, the PDF viewer...
  }
}

// -> {s: score, why: reason}
function score(j, sig, seen) {
  let s = 0;
  const why = [];
  if (seen && seen.n === j.n) { s += 80; why.push("you opened its posting in this tab"); }
  if (j.url && sig.urls.some((u) => bare(u).startsWith(bare(j.url)))) { s += 100; why.push("this is its posting"); }
  for (const id of j.ids || []) {
    if (sig.urls.some((u) => idIn(id, u))) { s += 100; why.push(`job number ${id.toUpperCase()} in the address`); break; }
    if (id.length >= 5 && idIn(id, sig.text)) { s += 60; why.push(`job number ${id.toUpperCase()} on the page`); break; }
  }
  const where = (sig.urls.map((u) => { try { return new URL(u).hostname; } catch { return ""; } }).join(" ") + " " + sig.head).toLowerCase();
  const company = tokens(j.company.replace(/\(.*?\)/g, ""));
  const coHits = company.filter((t) => where.replace(/[^a-z0-9]/g, "").includes(t)).length;
  const coText = company.filter((t) => sig.text.toLowerCase().includes(t)).length;
  s += Math.min(coHits * 12, 30) + Math.min(coText * 4, 12);
  const role = tokens(j.role);
  const roleHits = role.filter((t) => where.includes(t)).length;
  if (role.length) s += Math.round((roleHits / role.length) * 30);
  if (!why.length && (coHits || roleHits)) why.push("company and job title on the page");
  return { s, why: why.join(", ") };
}

function selectedJob() {
  const j = jobs.find((x) => x.n === $("job").value);
  return { n: j ? j.n : null, company: j ? j.company : "", role: j ? j.role : "", speed: Number($("speed").value) };
}

function showDocs() {
  const j = jobs.find((x) => x.n === $("job").value);
  const box = $("docs");
  box.replaceChildren();
  if (!j) { box.textContent = "Profile only: no resume or cover letter will be attached."; return; }
  for (const [name, file] of [["Resume", j.resume], ["Cover letter", j.cover]]) {
    const d = document.createElement("div");
    d.textContent = file ? `✅ ${name}: ${file}` : `❌ ${name}: none in the report (upload it yourself)`;
    box.appendChild(d);
  }
  const d = document.createElement("div");
  d.textContent = j.drafts
    ? `✅ ${j.drafts} drafted answers from the report (typed into matching question boxes, purple, for you to edit)`
    : "– No drafted answers in the report: essay questions are left for you";
  box.appendChild(d);
}

function showDetected(j, why, sure) {
  const box = $("detected");
  box.hidden = false;
  box.replaceChildren();
  const t = document.createElement("div");
  t.className = "dtitle";
  t.textContent = `${sure ? "This page" : "Best guess"}: #${j.n} ${j.company}`;
  const r = document.createElement("div");
  r.textContent = j.role;
  const w = document.createElement("div");
  w.className = "muted";
  w.textContent = sure ? `Matched: ${why}.` : `Not certain (${why || "weak match"}). Check it, or pick below.`;
  box.append(t, r, w);
}

async function showState() {
  const armed = await send({ type: "status", tabId: tab.id }).catch(() => null);
  $("state").textContent = armed
    ? `Autofill is ON in this tab${armed.n ? ` for #${armed.n} ${armed.company}` : ""}. It keeps filling each new page until you click Stop.`
    : "Autofill is off in this tab.";
}

async function init() {
  const forced = new URLSearchParams(location.search).get("tab"); // test harness only: popup.html?tab=<id>
  [tab] = forced ? [await chrome.tabs.get(Number(forced))] : await chrome.tabs.query({ active: true, currentWindow: true });
  const { speed = 35 } = await chrome.storage.local.get("speed");
  $("speed").value = speed;
  $("speedVal").textContent = `${speed} ms per key`;

  const sel = $("job");
  sel.add(new Option("Profile only (no resume / cover letter)", ""));
  try {
    jobs = await send({ type: "jobs" });
  } catch (e) {
    $("conn").hidden = false;
    $("conn").textContent = "Can't reach the autofill helper at 127.0.0.1:3001 (" + e.message + "). Run “Start autofill helper.cmd” in career-ops\\local\\chrome-autofill. You can still fill your profile details.";
  }
  const [sig, seen] = await Promise.all([pageSignals(), send({ type: "seen", tabId: tab.id }).catch(() => null)]);
  const ranked = jobs.map((j) => ({ j, ...score(j, sig, seen) })).sort((a, b) => b.s - a.s || Number(b.j.n) - Number(a.j.n));
  for (const { j } of ranked) sel.add(new Option(`#${j.n} ${j.company}: ${j.role} [${j.status}]`.slice(0, 110), j.n));

  const { [`pick:${tab.id}`]: picked } = await chrome.storage.session.get(`pick:${tab.id}`);
  const [best, next] = ranked;
  const sure = best && best.s >= 60 && (!next || best.s - next.s >= 20);
  const guess = best && best.s >= 25 && (!next || best.s - next.s >= 10);
  if (picked != null) { // you chose it yourself earlier in this tab
    sel.value = picked;
    const j = jobs.find((x) => x.n === picked);
    if (j) showDetected(j, "your choice", true);
    else $("pickBox").hidden = false;
  } else if (sure || guess) {
    sel.value = best.j.n;
    showDetected(best.j, best.why, sure);
    if (!sure) $("pickBox").hidden = false;
  } else {
    $("pickBox").hidden = false;
    if (jobs.length) {
      $("conn").hidden = false;
      $("conn").textContent = "This page doesn't match any job in your tracker. Pick it below so the right resume is attached, or fill with your profile only.";
    }
  }
  showDocs();
  await showState();
  if (await send({ type: "updateReady" }).catch(() => false)) $("update").hidden = false;
}

$("change").addEventListener("click", (e) => { e.preventDefault(); $("pickBox").hidden = false; $("job").focus(); });
$("update").addEventListener("click", () => send({ type: "applyUpdate" }).catch(() => {}).finally(() => window.close()));
$("job").addEventListener("change", () => {
  chrome.storage.session.set({ [`pick:${tab.id}`]: $("job").value });
  const j = jobs.find((x) => x.n === $("job").value);
  if (j) showDetected(j, "your choice", true); else $("detected").hidden = true;
  showDocs();
});
$("speed").addEventListener("input", () => {
  $("speedVal").textContent = `${$("speed").value} ms per key`;
  chrome.storage.local.set({ speed: Number($("speed").value) });
});
$("start").addEventListener("click", async () => {
  await send({ type: "start", tabId: tab.id, job: selectedJob() });
  window.close(); // get out of the way so you can watch the page
});
$("stop").addEventListener("click", async () => {
  await send({ type: "stop", tabId: tab.id });
  showState();
});

init();
