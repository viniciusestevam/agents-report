/* Agents Report UI. Vanilla JS, no build. Every value shown carries its basis:
   measured (from logs), estimated (computed), or unavailable (shown as a dash, never 0). */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const main = $("#main");
const tip = $("#tip");
const state = { days: localGet("days", ""), cache: {} };

function localGet(k, d) { try { return localStorage.getItem("obs:" + k) ?? d; } catch { return d; } }
function localSet(k, v) { try { localStorage.setItem("obs:" + k, v); } catch { /* private mode */ } }

/* Theme: system → light → dark. The CSS keys off data-theme; no attribute = follow the OS. */
const THEMES = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };
const svg = (d) => `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">${d}</svg>`;
const THEME_ICONS = {
  system: svg('<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>'),
  light: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  dark: svg('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>'),
};
function applyTheme(t) {
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = t;
  const b = document.getElementById("theme");
  if (b) { b.innerHTML = THEME_ICONS[t]; b.title = THEMES[t]; b.setAttribute("aria-label", THEMES[t] + ". Click to change."); }
}
let theme = localGet("theme", "system");
if (!THEMES[theme]) theme = "system";
applyTheme(theme);
document.getElementById("theme").addEventListener("click", () => {
  theme = { system: "light", light: "dark", dark: "system" }[theme];
  localSet("theme", theme);
  applyTheme(theme);
});

/* ---------- formatting ---------- */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const DASH = '<span class="dash">—</span>';
const usd = (x, d) => x == null ? DASH : "$" + Number(x).toLocaleString("en-US", { minimumFractionDigits: d ?? (Math.abs(x) < 10 ? 2 : Math.abs(x) < 1000 ? 2 : 0), maximumFractionDigits: d ?? 2 });
const int = (x) => x == null ? DASH : Math.round(x).toLocaleString("en-US");
const pct = (x, d = 0) => x == null ? DASH : (x * 100).toFixed(d) + "%";
function tok(x) {
  if (x == null) return DASH;
  if (x >= 1e9) return (x / 1e9).toFixed(2) + "B";
  if (x >= 1e6) return (x / 1e6).toFixed(x >= 1e8 ? 0 : 1) + "M";
  if (x >= 1e4) return Math.round(x / 1e3) + "k";
  if (x >= 1e3) return (x / 1e3).toFixed(1) + "k";
  return String(Math.round(x));
}
function dur(ms) {
  if (ms == null) return DASH;
  const s = ms / 1000;
  if (s < 1) return Math.round(ms) + " ms";
  if (s < 60) return s.toFixed(s < 10 ? 1 : 0) + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  return (s / 3600).toFixed(1) + " h";
}
const dt = (t) => t ? new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : DASH;
const day = (t) => t ? new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : DASH;
const clock = (t) => t ? new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";
const promptTok = (u) => u.input + u.cache_read + u.cache_write_5m + u.cache_write_1h;
const B = { m: '<span class="basis m" title="Read from the agent\'s own logs">measured</span>', e: '<span class="basis e" title="Computed: tokens × price, or a character-based estimate">estimated</span>', u: '<span class="basis u" title="Not recorded or no known price">unavailable</span>' };
/* Agents: name, tint and an original glyph (not the vendors' logos). Glyphs use currentColor on the tint. */
const OTHER_AGENT = { color: "var(--neutral-2)", glyph: '<circle cx="12" cy="12" r="7"/>' };  // agents added later via an adapter
const AGENTS = {
  "claude-code": { name: "Claude Code", color: "var(--ag-claude)", glyph: '<path d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6 5.6 18.4"/>' },
  codex: { name: "Codex", color: "var(--ag-codex)", glyph: '<path d="m6 8 4 4-4 4M12 17h6"/>' },
  hermes: { name: "Hermes", color: "var(--ag-hermes)", glyph: '<path d="M12 20V9M12 9c-2.5-4-6-5-9-4 1 3 4 5 9 4zM12 9c2.5-4 6-5 9-4-1 3-4 5-9 4z"/>' },
  pi: { name: "Pi", color: "var(--ag-pi)", glyph: '<path d="M4 7h16M9 7v12M15 7v9.5c0 1.4.9 2.5 2.5 2.5"/>' },
  opencode: { name: "OpenCode", color: "var(--ag-opencode)", glyph: '<path d="M8 4H6.5A1.5 1.5 0 0 0 5 5.5V10l-2 2 2 2v4.5A1.5 1.5 0 0 0 6.5 20H8M16 4h1.5A1.5 1.5 0 0 1 19 5.5V10l2 2-2 2v4.5a1.5 1.5 0 0 1-1.5 1.5H16"/>' },
};
const agentName = (a) => (AGENTS[a] || {}).name || a;
const agentColor = (a) => (AGENTS[a] || {}).color || "var(--neutral-2)";
function agentIcon(a, size = 18) {
  const g = (AGENTS[a] || OTHER_AGENT).glyph;
  return `<span class="agi" style="--ag:${agentColor(a)};width:${size}px;height:${size}px" title="${esc(agentName(a))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${g}</svg></span>`;
}
/* Models: short names ("Opus 5.5") with the full id in the tooltip. */
function modelName(m) {
  const x = /^claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d{1,2}))?(?!\d)/.exec(m || "");
  return x ? `${x[1][0].toUpperCase() + x[1].slice(1)} ${x[2]}${x[3] ? "." + x[3] : ""}` : (m || "unknown");
}
const mdl = (m, extra = "") => `<span class="mdl" title="${esc(m)}${extra}">${esc(modelName(m))}</span>`;
function modelChips(models, max = 2) {  // {model: requests}, busiest first
  const e = Object.entries(models || {}).sort((a, b) => b[1] - a[1]);
  if (!e.length) return "";
  const more = e.length > max ? `<span class="mdl more" title="${esc(e.slice(max).map(([m, n]) => `${m} · ${n} requests`).join("\n"))}">+${e.length - max}</span>` : "";
  return `<span class="mdls">${e.slice(0, max).map(([m, n]) => mdl(m, ` · ${n} requests`)).join("")}${more}</span>`;
}
const modelText = (models) => Object.entries(models || {}).sort((a, b) => b[1] - a[1]).map(([m]) => modelName(m)).join(", ");
const agentLabel = (a) => `<span class="agl">${agentIcon(a)}${esc(agentName(a))}</span>`;
const sessHref = (key, q = "") => "#/session/" + encodeURIComponent(key) + (q ? "?" + q : "");

/* Presence: the background server stops itself ~20 s after the last dashboard tab closes. */
const TAB = Math.random().toString(36).slice(2, 12);

function checkIn() {
  fetch(`/api/presence?tab=${TAB}&state=open`, { cache: "no-store" })
    .then((r) => { if (r.ok) serverGone(false); })
    .catch(() => serverGone(true));
}
function serverGone(gone) {
  let b = document.getElementById("gone");
  if (!gone) { if (b) b.remove(); return; }
  if (b) return;
  b = document.createElement("div");
  b.id = "gone";
  b.className = "gone";
  b.setAttribute("role", "status");
  b.innerHTML = 'The dashboard server has stopped. Start it again with <code>python3 scripts/agents_report.py dashboard</code>, or ask your agent to open the dashboard.';
  document.body.append(b);
}
checkIn();
setInterval(checkIn, 15000);
addEventListener("pagehide", () => navigator.sendBeacon(`/api/presence?tab=${TAB}&state=closed`));
addEventListener("pageshow", (e) => { if (e.persisted) checkIn(); });  // back from the back/forward cache
document.addEventListener("visibilitychange", () => { if (!document.hidden) checkIn(); });

async function api(path) {
  const r = await fetch("/api/" + path);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

/* ---------- charts (own SVG, flat, one hue) ---------- */
function niceTicks(max, n = 4) {
  if (!(max > 0)) return [0, 1];
  const raw = max / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const top = Math.ceil(max / step) * step + (Math.ceil(max / step) * step === max ? step : 0);
  const out = [];
  for (let v = 0; v <= top + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function bindTips(root) {
  root.addEventListener("mousemove", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) { tip.hidden = true; return; }
    tip.innerHTML = t.getAttribute("data-tip");
    tip.hidden = false;
    const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px";
    tip.style.top = (e.clientY + 14) + "px";
  });
  root.addEventListener("mouseleave", () => { tip.hidden = true; });
}
/* stacked columns. series: [{key, color, label}], rows: [{label, parts:{key:v}, tip, mark}] */
function columns(el, rows, series, { height = 180, fmt = tok, xEvery, onClick, marks = [] } = {}) {
  const W = Math.max(el.clientWidth || 600, 280), H = height, L = 44, R = 4, T = marks.length ? 16 : 6, Bm = 20;
  const pw = W - L - R, ph = H - T - Bm;
  const totals = rows.map((r) => series.reduce((a, s) => a + (r.parts[s.key] || 0), 0));
  const ticks = niceTicks(Math.max(...totals, 0));
  const top = ticks[ticks.length - 1] || 1;
  const n = rows.length || 1, slot = pw / n, bw = Math.max(1, Math.min(28, slot * (n > 60 ? 0.86 : 0.7)));
  const y = (v) => T + ph - (v / top) * ph;
  let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">`;
  ticks.forEach((t, i) => {
    s += `<line class="${i ? "grid-l" : "base-l"}" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>`;
    s += `<text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`;
  });
  const every = xEvery || Math.max(1, Math.ceil(n / 7));
  rows.forEach((r, i) => {
    const x = L + i * slot + (slot - bw) / 2;
    let acc = 0;
    series.forEach((se) => {
      const v = r.parts[se.key] || 0;
      if (v <= 0) return;
      const y0 = y(acc), y1 = y(acc + v);
      s += `<rect x="${x}" y="${y1}" width="${bw}" height="${Math.max(0.5, y0 - y1 - (acc ? 1 : 0))}" fill="${se.color}"/>`;
      acc += v;
    });
    s += `<rect x="${L + i * slot}" y="${T}" width="${slot}" height="${ph}" fill="transparent" data-i="${i}" data-tip="${esc(r.tip || "")}" ${onClick ? 'style="cursor:pointer"' : ""}/>`;
    if (i % every === 0 && r.label) {
      const anchor = i === 0 ? "start" : "middle";
      s += `<text x="${i === 0 ? L : x + bw / 2}" y="${H - 5}" text-anchor="${anchor}">${esc(r.label)}</text>`;
    }
  });
  marks.forEach((m) => {
    const x = L + m.i * slot;
    s += `<line x1="${x}" x2="${x}" y1="${T - 4}" y2="${T + ph}" stroke="var(--ink-2)" stroke-dasharray="3 3"/>`;
    s += `<text x="${x + 4}" y="${T - 5}" style="fill:var(--ink-2)">${esc(m.label)}</text>`;
  });
  s += "</svg>";
  el.innerHTML = s;
  el.classList.add("chart");
  bindTips(el);
  if (onClick) el.addEventListener("click", (e) => { const t = e.target.closest("[data-i]"); if (t) onClick(+t.dataset.i); });
}
function barList(rows, fmt = usd) {
  const max = Math.max(...rows.map((r) => r.value || 0), 0) || 1;
  return `<div class="barlist">${rows.map((r) => `<div class="bl-row"><span class="bl-name" title="${esc(r.label)}">${r.href ? `<a href="${r.href}">${esc(r.label)}</a>` : esc(r.label)}</span><span class="num">${fmt(r.value)}</span><span class="bl-bar"><i style="width:${(100 * (r.value || 0)) / max}%"></i></span></div>`).join("")}</div>`;
}

/* ---------- shell ---------- */
function setNav(name) {
  document.querySelectorAll("nav a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === name) || a.removeAttribute("aria-current"));
  document.querySelectorAll("nav a").forEach((a) => { if (a.dataset.nav === name) a.setAttribute("aria-current", "page"); });
  $("#side").classList.remove("open");
  $("#menu").setAttribute("aria-expanded", "false");
}
$("#menu").addEventListener("click", () => {
  const open = $("#side").classList.toggle("open");
  $("#menu").setAttribute("aria-expanded", String(open));
});
function periodSeg() {
  const opts = [["7", "7 days"], ["30", "30 days"], ["", "All time"]];
  return `<div class="seg" role="group" aria-label="Period">${opts.map(([v, l]) => `<button data-days="${v}" aria-pressed="${state.days === v}">${l}</button>`).join("")}</div>`;
}
function wirePeriod(rerender) {
  main.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => {
    state.days = b.dataset.days; localSet("days", state.days); rerender();
  }));
}
const daysQ = () => state.days ? "days=" + state.days : "";

/* ---------- overview ---------- */
async function viewOverview() {
  setNav("overview");
  const d = await api("overview?" + daysQ());
  const o = d.overview, recs = d.recommendations;
  renderSideAgents(d.agents);
  const rec = o.reconciliation;
  const best = recs.find((r) => r.savings_usd);
  const finding = o.sessions
    ? `Estimated <strong>${usd(o.cost_estimated)}</strong> across ${o.sessions} sessions and ${int(o.requests)} API requests.` +
      (rec.sessions ? ` Claude Code's own meter recorded ${usd(rec.measured)} for the ${rec.sessions} sessions that log it (estimate for those: ${usd(rec.estimated)}).` : "") +
      (best ? ` Biggest avoidable cost: <strong>${esc(best.title.toLowerCase())}</strong>, about ${usd(best.savings_usd)}.` : "")
    : "No sessions in this period.";
  main.innerHTML = `
    <div class="title-row"><div><h1>Overview</h1><p class="finding">${finding}</p></div>${periodSeg()}</div>
    <div class="kpis" style="--n:5">
      <div class="kpi"><div class="l">Spend ${B.e}</div><div class="v">${usd(o.cost_estimated)}</div><div class="s">${o.unpriced_requests ? int(o.unpriced_requests) + " requests unpriced" : "all requests priced"}</div></div>
      <div class="kpi"><div class="l">API requests ${B.m}</div><div class="v">${int(o.requests)}</div><div class="s">${o.sessions} sessions · ${o.subagents} subagents</div></div>
      <div class="kpi"><div class="l">Cache hit rate ${B.m}</div><div class="v">${pct(o.cache_hit_rate, 1)}</div><div class="s">of prompt tokens read from cache</div></div>
      <div class="kpi"><div class="l">Prompt tokens ${B.m}</div><div class="v">${tok(promptTok(o.usage))}</div><div class="s">${tok(o.usage.cache_write_5m + o.usage.cache_write_1h)} written to cache</div></div>
      <div class="kpi"><div class="l">Output tokens ${B.m}</div><div class="v">${tok(o.usage.output)}</div><div class="s">${o.usage.reasoning ? tok(o.usage.reasoning) + " reasoning" : "reasoning not split out"}</div></div>
    </div>
    <section class="card act-card" id="activity"></section>
    <div class="grid">
      <section class="card c8"><div class="card-h"><h2>Spend per day</h2><span class="sub" id="daily-sub"></span></div><div id="daily"></div></section>
      <section class="card c4"><div class="card-h"><h2>What to change</h2><a class="sub" href="#/recommendations">All ${recs.length ? "" : ""}recommendations</a></div>
        ${recs.length ? recs.map((r) => `<div class="rec"><div class="rec-h"><a class="rec-title" href="#/recommendations/${r.id}">${esc(r.title)}</a></div>
          <div class="small muted" style="margin-top:4px"><span class="tag sev-${r.severity}">${r.severity}</span> ${r.savings_usd ? `≈ ${usd(r.savings_usd)} avoidable ${B.e}` : ""}</div></div>`).join("") : '<p class="muted">No issues found by the rules in this period.</p>'}
      </section>
    </div>
    <div class="grid">
      <section class="card c8"><div class="card-h"><h2>Most expensive sessions</h2><a class="sub" href="#/sessions">View all</a></div>
        <table class="fit"><thead><tr><th>Session</th><th class="hide-sm">Agent</th><th class="n hide-sm">Started</th><th class="n">Cost ${B.e}</th></tr></thead><tbody>
        ${o.top_sessions.map((s) => `<tr class="click" data-href="${sessHref(s.key)}"><td><a class="t1" href="${sessHref(s.key)}">${esc(s.title)}</a><div class="t2">${esc(s.project || "—")} ${modelChips(s.models)}</div></td><td class="hide-sm">${agentLabel(s.agent)}</td><td class="n hide-sm">${day(s.started)}</td><td class="n">${usd(s.cost)}</td></tr>`).join("")}
        </tbody></table></section>
      <section class="card c4"><div class="card-h"><h2>Spend by project</h2><span class="sub">${B.e}</span></div>
        ${barList(Object.entries(o.by_project).slice(0, 8).map(([k, v]) => ({ label: k, value: v.cost })))}</section>
    </div>
    <div class="grid">
      <section class="card c7"><div class="card-h"><h2>Tools</h2><span class="sub">${B.m} from tool calls in transcripts</span></div>
        <table><thead><tr><th>Tool</th><th class="n">Calls</th><th class="n">Errors</th><th class="n hide-sm">Output</th><th class="n">Avg time</th></tr></thead><tbody>
        ${Object.entries(o.tools).slice(0, 10).map(([n, t]) => `<tr><td class="mono" style="font-family:var(--sans);font-size:14px">${esc(n)}</td><td class="n">${int(t.calls)}</td><td class="n">${t.errors ? `<span class="${t.errors / t.calls > 0.15 ? "tag bad" : ""}">${int(t.errors)}</span>` : "0"}</td><td class="n hide-sm">${tok(t.output_chars / 4)} tok</td><td class="n">${t.timed ? dur(t.ms / t.timed) : DASH}</td></tr>`).join("")}
        </tbody></table></section>
      <section class="card c5"><div class="card-h"><h2>Agents</h2><a class="sub" href="#/sources">Data sources</a></div>
        <table><thead><tr><th>Agent</th><th class="n">Sessions</th><th class="n">Requests</th><th class="n">Cost</th></tr></thead><tbody>
        ${Object.entries(o.by_agent).map(([a, v]) => `<tr><td>${agentLabel(a)}${v.unpriced.length ? `<div class="t2">No price for ${esc(v.unpriced.join(", "))}</div>` : ""}</td><td class="n">${v.sessions}</td><td class="n">${int(v.requests)}</td><td class="n">${v.cost == null ? `${DASH} ${B.u}` : usd(v.cost)}</td></tr>`).join("")}
        ${d.agents.filter((a) => !a.present).map((a) => `<tr><td>${esc(a.agent)}<div class="t2">Not detected on this machine</div></td><td class="n">${DASH}</td><td class="n">${DASH}</td><td class="n">${DASH}</td></tr>`).join("")}
        </tbody></table></section>
    </div>
    ${Object.keys(o.by_model).length ? `<div class="grid"><section class="card c12"><div class="card-h"><h2>By model</h2><span class="sub">requests and tokens ${B.m} · cost ${B.e}</span></div>
      <table class="fit"><thead><tr><th>Model</th><th class="n hide-sm">Sessions</th><th class="n">Requests</th><th class="n hide-sm">Tokens</th><th class="n">Cost</th><th class="hide-sm" style="width:28%">Share of cost</th></tr></thead><tbody>
      ${(() => { const tot = Object.values(o.by_model).reduce((a, v) => a + (v.cost || 0), 0) || 1;
        return Object.entries(o.by_model).map(([m, v]) => `<tr><td>${mdl(m)}${modelName(m) !== m ? ` <span class="t2 mono">${esc(m)}</span>` : ""}</td><td class="n hide-sm">${int(v.sessions)}</td><td class="n">${int(v.requests)}</td><td class="n hide-sm">${tok(v.tokens)}</td>
          <td class="n">${v.cost == null ? `${DASH} ${B.u}` : usd(v.cost)}</td><td class="hide-sm">${v.cost ? `<div class="share"><i style="width:${(v.cost / tot * 100).toFixed(1)}%"></i></div>` : ""}</td></tr>`).join(""); })()}
      </tbody></table></section></div>` : ""}`;
  wirePeriod(viewOverview);
  wireRows();
  activityGraph($("#activity"), d.activity || {});
  const days = fillDays(o.daily);
  const el = $("#daily");
  if (days.length) spendChart(el, days, Object.keys(o.by_agent).filter((a) => o.by_agent[a].cost));
  else el.innerHTML = '<p class="empty">No requests in this period.</p>';
}

/* ---------- activity heatmap: last 53 weeks, one square per day, like GitHub ---------- */
const localKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function activityGraph(el, act) {
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const start = new Date(today); start.setDate(start.getDate() - 52 * 7 - today.getDay());  // a Sunday, 53 columns back
  const days = [];
  for (const d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) days.push({ date: new Date(d), key: localKey(d), v: act[localKey(d)] || null });
  const vals = days.map((x) => (x.v ? x.v.requests : 0));
  const nz = vals.filter(Boolean).sort((a, b) => a - b);
  const q = [0.25, 0.5, 0.75].map((f) => nz[Math.floor(f * (nz.length - 1))] || 0);  // quartiles of active days
  const level = (v) => (!v ? 0 : v <= q[0] ? 1 : v <= q[1] ? 2 : v <= q[2] ? 3 : 4);
  // streaks and totals
  let longest = 0, run = 0;
  vals.forEach((v) => { run = v ? run + 1 : 0; longest = Math.max(longest, run); });
  let current = 0;
  for (let i = vals.length - 1; i >= 0 && vals[i]; i--) current++;
  const total = vals.reduce((a, b) => a + b, 0), active = nz.length;
  const busiest = days.reduce((m, x) => ((x.v ? x.v.requests : 0) > (m.v ? m.v.requests : 0) ? x : m), days[0]);
  const longDate = (d) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  const starts = [];  // first column of each month; drop a label that would crowd the next one
  days.forEach((x, i) => { if (x.date.getDay() === 0 && (!starts.length || starts[starts.length - 1].m !== x.date.getMonth())) starts.push({ col: Math.floor(i / 7), m: x.date.getMonth(), date: x.date }); });
  const months = starts.filter((st, j) => (starts[j + 1] ? starts[j + 1].col - st.col >= 3 : st.col <= 50))
    .map((st) => `<span class="act-m" style="grid-column:${st.col + 2} / span 3">${st.date.toLocaleDateString(undefined, { month: "short" })}</span>`).join("");
  const wd = [1, 3, 5].map((dow) => `<span class="act-wd" style="grid-row:${dow + 2}">${new Date(2026, 0, 4 + dow).toLocaleDateString(undefined, { weekday: "short" })}</span>`).join("");
  const cells = days.map((x, i) => {
    const v = x.v;
    const tipText = v && v.requests ? `<b>${int(v.requests)} requests</b> · ${longDate(x.date)}<br>${v.sessions} sessions started · ${tok(v.tokens)} tokens · ${usd(v.cost)} est.${v.models && Object.keys(v.models).length ? "<br>" + esc(modelText(v.models)) : ""}` : `No activity · ${longDate(x.date)}`;
    return `<i class="l${level(vals[i])}" style="grid-column:${Math.floor(i / 7) + 2};grid-row:${x.date.getDay() + 2}" data-tip="${esc(tipText)}"></i>`;
  }).join("");
  el.innerHTML = `<div class="card-h"><h2>Activity</h2><span class="sub">${int(total)} API requests on ${active} days in the last year ${B.m}</span></div>
    <div class="act-scroll"><div class="act-grid" role="img" aria-label="API requests per day over the last year">${months}${wd}${cells}</div></div>
    <div class="act-foot"><span class="sub">Longest streak <b>${longest} ${longest === 1 ? "day" : "days"}</b> · current streak <b>${current} ${current === 1 ? "day" : "days"}</b>${busiest.v ? ` · busiest day <b>${busiest.date.toLocaleDateString(undefined, { month: "short", day: "numeric" })}</b> (${int(busiest.v.requests)} requests)` : ""}</span>
      <span class="act-legend">Less ${[0, 1, 2, 3, 4].map((l) => `<i class="l${l}"></i>`).join("")} More</span></div>`;
  bindTips(el);
  const sc = $(".act-scroll", el);
  sc.scrollLeft = sc.scrollWidth;  // on narrow screens, start at today
}

/* ---------- spend per day: stacked by agent, rounded bars, average line, hover focus ---------- */
function spendChart(el, days, agents) {
  const W = Math.max(el.clientWidth || 600, 280), H = 330, L = 46, R = 8, T = 14, Bm = 24;
  const pw = W - L - R, ph = H - T - Bm, n = days.length;
  const tot = days.map(([, v]) => v.cost || 0);
  const total = tot.reduce((a, b) => a + b, 0), avg = total / n;
  const ticks = niceTicks(Math.max(...tot, 0.01), 4), top = ticks[ticks.length - 1];
  const y = (v) => T + ph - (v / top) * ph;
  const slot = pw / n, bw = Math.max(2, Math.min(24, slot * 0.68)), r = Math.min(4, bw / 2);
  const roundTop = (x, y0, w, h) => h <= r ? `M${x},${y0 + h}V${y0}H${x + w}V${y0 + h}Z`
    : `M${x},${y0 + h}V${y0 + r}Q${x},${y0} ${x + r},${y0}H${x + w - r}Q${x + w},${y0} ${x + w},${y0 + r}V${y0 + h}Z`;
  const shortDate = (d) => new Date(d + "T12:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
  let svgS = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Estimated spend per day">`;
  ticks.forEach((t, i) => {
    svgS += `<line class="${i ? "grid-l" : "base-l"}" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text x="${L - 10}" y="${y(t) + 4}" text-anchor="end">$${t}</text>`;
  });
  const every = Math.max(1, Math.ceil(n / Math.max(3, Math.floor(pw / 70))));
  days.forEach(([d, v], i) => {
    const x = L + i * slot + (slot - bw) / 2;
    let acc = 0, bars = "";
    const parts = agents.map((a) => [a, v[a] || 0]).filter(([, c]) => c > 0);
    parts.forEach(([a, c], j) => {
      const y1 = y(acc + c), h = Math.max(1, y(acc) - y1 - (acc ? 1.5 : 0));
      bars += j === parts.length - 1 ? `<path d="${roundTop(x, y1, bw, h)}" style="fill:${agentColor(a)}"/>` : `<rect x="${x}" y="${y1}" width="${bw}" height="${h}" style="fill:${agentColor(a)}"/>`;
      acc += c;
    });
    const byM = Object.entries(v).filter(([k, c]) => k.startsWith("m:") && c > 0).sort((a, b) => b[1] - a[1]);
    const tipText = `<b>${usd(tot[i])}</b> · ${shortDate(d)}${parts.length > 1 ? "<br>" + parts.map(([a, c]) => `${agentName(a)} ${usd(c)}`).join(" · ") : ""}${byM.length ? "<br>" + byM.map(([k, c]) => `${esc(modelName(k.slice(2)))} ${usd(c)}`).join(" · ") : ""}<br>${tok(v.tokens)} tokens`;
    svgS += `<g class="d">${bars}<rect class="hit" x="${L + i * slot}" y="${T}" width="${slot}" height="${ph}" data-tip="${esc(tipText)}"/></g>`;
    if (i % every === 0) svgS += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(shortDate(d))}</text>`;
  });
  if (total) svgS += `<line class="avg" x1="${L}" x2="${W - R}" y1="${y(avg)}" y2="${y(avg)}"><title>Average ${usd(avg)} per day</title></line>`;
  el.innerHTML = svgS + "</svg>";
  el.className = "chart spend";
  bindTips(el);
  const peak = tot.indexOf(Math.max(...tot));
  $("#daily-sub").innerHTML = `${usd(total)} ${B.e} · peak ${usd(tot[peak])} on ${esc(shortDate(days[peak][0]))} · <span class="avg-key"></span>avg ${usd(avg)}/day${agents.length > 1 ? " · " + agents.map(agentLabel).join(" ") : ""}`;
}
/* every calendar day from the first to the last, so time reads on a time axis */
function fillDays(daily) {
  const keys = Object.keys(daily).sort();
  if (!keys.length) return [];
  const out = [], end = new Date(keys[keys.length - 1] + "T12:00");
  for (let d = new Date(keys[0] + "T12:00"); d <= end; d.setDate(d.getDate() + 1)) {
    const k = d.toISOString().slice(0, 10);
    out.push([k, daily[k] || {}]);
  }
  return out;
}
function wireRows() {
  main.querySelectorAll("tr[data-href]").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("a")) location.hash = tr.dataset.href; }));
}
function renderSideAgents(agents) {
  $("#agents-mini").innerHTML = agents.map((a) => `<div class="agent-row"><span class="agl">${agentIcon(a.agent, 16)}<span>${esc(agentName(a.agent))}</span><span class="dot ${a.present ? "on" : ""}" title="${a.present ? "logs found" : "not found"}"></span></span><span class="num">${a.present ? a.files + (a.files === 1 ? " log" : " logs") : "not found"}</span></div>`).join("");
}

/* ---------- sessions ---------- */
/* ---------- sessions timeline: lanes per project, bars per session; zoom, pan, keyboard, click ---------- */
const H = 3600, D = 86400;
const TICK_STEPS = [[900, "h"], [1800, "h"], [H, "h"], [3 * H, "h"], [6 * H, "h"], [12 * H, "h"], [D, "d"], [2 * D, "d"], [7 * D, "d"], [14 * D, "d"], [30 * D, "d"]];
function timeTicks(t0, t1, n) {
  const [step, unit] = TICK_STEPS.find(([st]) => (t1 - t0) / st <= n) || TICK_STEPS[TICK_STEPS.length - 1];
  const off = new Date().getTimezoneOffset() * 60;  // align day ticks to local midnight
  const out = [];
  for (let t = Math.ceil((t0 - off) / step) * step + off; t <= t1; t += step) out.push(t);
  const fmt = unit === "h" ? (t) => new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return { ticks: out, fmt, dayMarks: unit === "h" };
}
function sessionTimeline(el, sessions) {
  const now = Date.now() / 1000;
  const items = sessions.filter((s) => s.started).map((s) => ({ s, a: s.started, b: Math.max(s.ended || s.started, s.started + 1), cost: s.tree_cost ?? s.cost.estimated }));
  if (!items.length) { el.remove(); return; }
  const lo = Math.min(...items.map((i) => i.a)), hi = Math.max(...items.map((i) => i.b));
  const pad = Math.max((hi - lo) * 0.03, 600);
  const full = [lo - pad, Math.max(hi + pad, Math.min(now, hi + 6 * H))];
  let [v0, v1] = state.days ? [Math.max(now - state.days * D, full[0]), full[1]] : full;
  let sort = localGet("tl-sort", "recent"), focus = -1, hoverLane = null;
  const SUB = 18, LP = 7, MINL = 40, AX = 26, MM = 46;
  const LABEL = () => (innerWidth < 760 ? 112 : 200);
  // lanes: one per project; label carries its totals
  const lanes = [...items.reduce((m, it) => {
    const k = it.s.project || "No project";
    if (!m.has(k)) m.set(k, { name: k, its: [], cost: 0, priced: false, last: 0, agents: new Set() });
    const l = m.get(k);
    l.its.push(it); l.last = Math.max(l.last, it.b); l.agents.add(it.s.agent);
    if (it.cost != null) { l.cost += it.cost; l.priced = true; }
    return m;
  }, new Map()).values()];
  const present = [...new Set(items.map((i) => i.s.agent))];
  el.innerHTML = `<div class="card-h"><h2>Timeline</h2><div class="tl-legend">${present.map(agentLabel).join("")}</div>
      <div class="tl-ctl"><span class="seg" role="group" aria-label="Sort lanes"><button data-sort="recent">Recent</button><button data-sort="cost">Cost</button></span>
      <span class="sub" id="tlr"></span><button class="btn sm" data-z="out" aria-label="Zoom out">−</button><button class="btn sm" data-z="in" aria-label="Zoom in">+</button><button class="btn sm" data-z="fit">Fit</button></div></div>
    <div class="tl-wrap"><div class="tl-labels"></div><div class="tl-plot" tabindex="0" role="application" aria-label="Sessions timeline. Arrow keys pan, plus and minus zoom, j and k step through sessions, Enter opens the focused one."><svg></svg></div></div>
    <div class="tl-mm"><div class="tl-mm-l small muted">Spend per day</div><div class="tl-mm-p"><svg></svg></div></div>
    <p class="small muted tl-help">Drag to pan · ctrl + scroll to zoom · drag the window in the strip below to move or resize it · click a project name to filter · click a bar to open the session</p>`;
  const plot = $(".tl-plot", el), svgEl = $("svg", plot), labels = $(".tl-labels", el), mmBox = $(".tl-mm-p", el), mmSvg = $("svg", mmBox);
  let order = [];
  const draw = () => {
    const W = plot.clientWidth, L = LABEL();
    labels.style.width = L + "px";
    $(".tl-mm-l", el).style.width = L + "px";
    const x = (t) => (t - v0) / (v1 - v0) * W;
    // pack overlapping bars into sub-rows, in pixels at the current zoom (min bar width 6 px)
    lanes.sort(sort === "cost" ? (p, q) => q.cost - p.cost || q.last - p.last : (p, q) => q.last - p.last);
    let y = AX;
    lanes.forEach((l) => {
      const ends = [];
      l.its.sort((p, q) => p.a - q.a).forEach((it) => {
        it.xa = x(it.a); it.xb = Math.max(x(it.b), it.xa + 6);
        let r = ends.findIndex((e) => e + 3 <= it.xa);
        if (r < 0 && ends.length >= 3) r = ends.indexOf(Math.min(...ends));  // at most 3 rows a lane; past that, bars overlap
        if (r < 0) { r = ends.length; ends.push(0); }
        ends[r] = Math.max(ends[r], it.xb); it.r = r;
      });
      l.n = Math.max(ends.length, 1); l.y = y; l.h = Math.max(MINL, l.n * SUB + 2 * LP);
      l.its.forEach((it) => { it.y = l.y + (l.h - l.n * SUB) / 2 + it.r * SUB + 2; });
      y += l.h;
    });
    const Hh = y;
    order = lanes.flatMap((l) => l.its);
    const { ticks, fmt, dayMarks } = timeTicks(v0, v1, Math.max(3, Math.floor(W / 95)));
    const grid = ticks.map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${AX - 6}" y2="${Hh}" class="g${dayMarks && new Date(t * 1000).getHours() === 0 ? " day" : ""}"/><text x="${x(t) + 4}" y="15" class="tk">${esc(fmt(t))}</text>`).join("");
    const bgs = lanes.map((l, i) => `<rect class="lane-bg${l.name === hoverLane ? " hl" : ""}${i % 2 ? " odd" : ""}" x="0" y="${l.y}" width="${W}" height="${l.h}" data-lane="${esc(l.name)}"/>`).join("");
    const bars = order.map((it, k) => {
      if (it.xb < -2 || it.xa > W + 2) return "";
      const s = it.s, w = it.xb - it.xa, h = SUB - 4;
      const tipText = `${agentName(s.agent)} · ${esc(s.title)}<br>${esc(modelText(s.models) || "no model calls")}<br>${dt(s.started)} – ${clock(s.ended)} · ${dur((it.b - it.a) * 1000)}<br>${int(s.n_requests)} requests · ${s.n_tool_calls} tool calls${s.n_subagents ? " · " + s.n_subagents + " subagents" : ""} · ${it.cost == null ? "unpriced" : usd(it.cost)}`;
      const chars = Math.floor((Math.min(w, W - Math.max(it.xa, 0)) - 12) / 6.4);
      const txt = chars >= 4 ? `<text x="${Math.max(it.xa, 0) + 6}" y="${it.y + h / 2 + 4}" class="bt">${esc(s.title.length > chars ? s.title.slice(0, chars - 1) + "…" : s.title)}</text>` : "";
      return `<g class="bar${k === focus ? " focus" : ""}" data-k="${k}" data-tip="${esc(tipText)}"><rect x="${it.xa}" y="${it.y}" width="${w}" height="${h}" rx="4" style="fill:${agentColor(s.agent)}"/>${txt}</g>`;
    }).join("");
    const nowL = now >= v0 && now <= v1 ? `<line x1="${x(now)}" x2="${x(now)}" y1="${AX - 6}" y2="${Hh}" class="now"/>` : "";
    svgEl.setAttribute("viewBox", `0 0 ${W} ${Hh}`);
    svgEl.setAttribute("width", W);
    svgEl.setAttribute("height", Hh);
    svgEl.innerHTML = bgs + grid + nowL + bars;
    labels.style.height = Hh + "px";
    labels.innerHTML = lanes.map((l) => `<a class="lane-l${l.name === hoverLane ? " hl" : ""}" style="top:${l.y}px;height:${l.h}px" href="#/sessions?project=${encodeURIComponent(l.name)}" data-lane="${esc(l.name)}" title="Show only ${esc(l.name)}">
        <b>${esc(l.name)}</b><span>${[...l.agents].map((a) => agentIcon(a, 14)).join("")} ${l.its.length} · ${l.priced ? usd(l.cost) : "unpriced"}</span></a>`).join("");
    $("#tlr", el).textContent = `${day(v0)} – ${day(v1)}`;
    el.querySelectorAll("[data-sort]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.sort === sort));
    drawMini();
  };
  // minimap: spend per day over the whole range, with the visible window as a draggable brush
  const days = new Map();
  items.forEach((it) => { const k = Math.floor(it.a / D) * D; days.set(k, (days.get(k) || 0) + (it.cost || 0)); });
  const mx = (t) => (t - full[0]) / (full[1] - full[0]) * mmBox.clientWidth;
  const drawMini = () => {
    const W = mmBox.clientWidth, top = Math.max(...days.values(), 1e-9), bw = Math.max(2, mx(full[0] + D) - mx(full[0]) - 1);
    const cols = [...days].map(([t, c]) => { const hh = Math.max(c > 0 ? 2 : 0, (c / top) * (MM - 8)); return `<rect x="${mx(t)}" y="${MM - hh}" width="${bw}" height="${hh}" class="mm-d"/>`; }).join("");
    const a = Math.max(0, mx(v0)), b = Math.min(W, mx(v1));
    mmSvg.setAttribute("viewBox", `0 0 ${W} ${MM}`);
    mmSvg.setAttribute("width", W);
    mmSvg.setAttribute("height", MM);
    mmSvg.innerHTML = `${cols}<rect class="mm-dim" x="0" y="0" width="${a}" height="${MM}"/><rect class="mm-dim" x="${b}" y="0" width="${Math.max(0, W - b)}" height="${MM}"/>
      <rect class="mm-win" x="${a}" y="0.5" width="${Math.max(b - a, 4)}" height="${MM - 1}" rx="3" data-m="move"/>
      <rect class="mm-h" x="${a - 4}" y="0" width="8" height="${MM}" data-m="l"/><rect class="mm-h" x="${b - 4}" y="0" width="8" height="${MM}" data-m="r"/>`;
  };
  const clamp = () => {  // keep the view near the data, between 30 minutes and 2 years wide
    const span = Math.min(Math.max(v1 - v0, 1800), 730 * D);
    const mid = Math.min(Math.max((v0 + v1) / 2, full[0]), full[1]);
    v0 = mid - span / 2; v1 = mid + span / 2;
  };
  const zoom = (k, at = 0.5) => { const t = v0 + (v1 - v0) * at; v0 = t - (t - v0) * k; v1 = t + (v1 - t) * k; clamp(); draw(); };
  const pan = (frac) => { const d = (v1 - v0) * frac; v0 += d; v1 += d; clamp(); draw(); };
  el.querySelectorAll("[data-z]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.z === "fit") { [v0, v1] = full; draw(); } else zoom(b.dataset.z === "in" ? 0.6 : 1 / 0.6);
  }));
  el.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => { sort = b.dataset.sort; localSet("tl-sort", sort); draw(); if (state.rerenderTable) state.rerenderTable(); }));
  plot.addEventListener("wheel", (e) => {
    const r = plot.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoom(Math.exp(e.deltaY * 0.01), (e.clientX - r.left) / r.width); }
    else if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || e.shiftKey) { e.preventDefault(); pan((e.deltaX || e.deltaY) / r.width); }
  }, { passive: false });
  let drag = null;
  plot.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, v0, v1, moved: false, id: e.pointerId }; });
  plot.addEventListener("pointermove", (e) => {
    const lane = e.target.closest && e.target.closest("[data-lane]");
    const ln = lane ? lane.dataset.lane : (e.target.closest && e.target.closest(".bar") ? order[+e.target.closest(".bar").dataset.k].s.project || "No project" : null);
    if (ln !== hoverLane && !drag) { hoverLane = ln; el.querySelectorAll("[data-lane]").forEach((n) => n.classList.toggle("hl", n.dataset.lane === hoverLane)); }
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (Math.abs(dx) > 3 && !drag.moved) { drag.moved = true; plot.setPointerCapture(drag.id); }
    if (!drag.moved) return;
    const d = -dx / plot.clientWidth * (drag.v1 - drag.v0);
    v0 = drag.v0 + d; v1 = drag.v1 + d; clamp(); draw(); tip.hidden = true;
  });
  plot.addEventListener("pointerup", (e) => {
    const moved = drag && drag.moved;
    drag = null;
    if (moved) return;
    const bar = e.target.closest && e.target.closest(".bar");
    if (bar) location.hash = sessHref(order[+bar.dataset.k].s.key);
  });
  labels.addEventListener("pointerover", (e) => { const l = e.target.closest("[data-lane]"); hoverLane = l ? l.dataset.lane : null; el.querySelectorAll("[data-lane]").forEach((n) => n.classList.toggle("hl", n.dataset.lane === hoverLane)); });
  // minimap: drag the window to move it, its edges to resize, empty space to draw a new one; a click centres the view there
  let mm = null;
  mmBox.addEventListener("pointerdown", (e) => {
    const r = mmBox.getBoundingClientRect(), t = full[0] + (e.clientX - r.left) / r.width * (full[1] - full[0]);
    mm = { mode: (e.target.dataset && e.target.dataset.m) || "new", x: e.clientX, t, v0, v1, moved: false };
    mmBox.setPointerCapture(e.pointerId);
  });
  mmBox.addEventListener("pointermove", (e) => {
    if (!mm) return;
    const r = mmBox.getBoundingClientRect(), dt_ = (e.clientX - mm.x) / r.width * (full[1] - full[0]), t = mm.t + dt_;
    if (Math.abs(e.clientX - mm.x) > 3) mm.moved = true;
    if (!mm.moved) return;
    if (mm.mode === "move") { v0 = mm.v0 + dt_; v1 = mm.v1 + dt_; }
    else if (mm.mode === "l") v0 = Math.min(t, v1 - 1800);
    else if (mm.mode === "r") v1 = Math.max(t, v0 + 1800);
    else { v0 = Math.min(mm.t, t); v1 = Math.max(mm.t, t); }
    clamp(); draw(); tip.hidden = true;
  });
  mmBox.addEventListener("pointerup", () => {
    if (mm && !mm.moved && mm.mode === "new") { const sp = v1 - v0; v0 = mm.t - sp / 2; v1 = mm.t + sp / 2; clamp(); draw(); }
    mm = null;
  });
  plot.addEventListener("keydown", (e) => {
    const step = (dir) => { focus = Math.max(0, Math.min(order.length - 1, focus + dir)); const it = order[focus]; if (it.a < v0 || it.b > v1) { const sp = v1 - v0; v0 = it.a - sp * 0.3; v1 = v0 + sp; clamp(); } draw(); };
    const k = { ArrowLeft: () => pan(-0.15), ArrowRight: () => pan(0.15), "+": () => zoom(0.6), "=": () => zoom(0.6), "-": () => zoom(1 / 0.6), "0": () => { [v0, v1] = full; draw(); },
      Enter: () => focus >= 0 && (location.hash = sessHref(order[focus].s.key)), j: () => step(1), k: () => step(-1) }[e.key];
    if (k) { e.preventDefault(); k(); }
  });
  bindTips(plot);
  bindTips(mmBox);
  draw();
  new ResizeObserver(() => draw()).observe(plot);
}

/* Session rows, shared by the flat list and the per-project groups. */
function sessRow(s, cls = "") {
  return `<tr class="click${cls}" data-href="${sessHref(s.key)}">
    <td><a class="t1" href="${sessHref(s.key)}">${esc(s.title)}</a><div class="t2">${esc(s.project || "—")}${s.branch ? " · " + esc(s.branch) : ""}${s.n_subagents ? ` · ${s.n_subagents} subagents` : ""} · <span class="mono">${esc(s.id.slice(0, 8))}</span> ${modelChips(s.models)}</div></td>
    <td class="hide-sm nw">${agentLabel(s.agent)}</td><td class="n hide-sm">${dt(s.started)}</td><td class="n hide-sm">${int(s.n_requests)}</td>
    <td class="n hide-sm">${tok(s.peak_context)}</td><td class="n hide-sm">${pct(s.cache_hit_rate)}</td>
    <td class="n">${s.cost.estimated == null ? DASH : usd(s.tree_cost ?? s.cost.estimated)}${s.cost.measured != null ? `<div class="t2">${usd(s.cost.measured)} measured</div>` : ""}</td></tr>`;
}
const openProjects = new Set();
function sessTable(el, sessions, filtered) {
  let group = localGet("sess-group", "list");
  const head = '<thead><tr><th>Session</th><th class="hide-sm">Agent</th><th class="n hide-sm">Started</th><th class="n hide-sm">Requests</th><th class="n hide-sm">Peak context</th><th class="n hide-sm">Cache hit</th><th class="n">Cost</th></tr></thead>';
  const groups = () => {
    const m = new Map();
    sessions.forEach((s) => { const k = s.project || "No project"; if (!m.has(k)) m.set(k, []); m.get(k).push(s); });
    const total = sessions.reduce((a, s) => a + (s.tree_cost ?? s.cost.estimated ?? 0), 0) || 1;
    const by = localGet("tl-sort", "recent") === "cost"  // same order as the timeline's lanes
      ? (x) => -x[1].reduce((a, s) => a + (s.tree_cost ?? s.cost.estimated ?? 0), 0) : (x) => -Math.max(...x[1].map((s) => s.ended || s.started || 0));
    return [...m].sort((x, y) => by(x) - by(y)).map(([name, ss]) => {
      const priced = ss.filter((s) => s.cost.estimated != null);
      const cost = priced.reduce((a, s) => a + (s.tree_cost ?? s.cost.estimated), 0);
      const isOpen = openProjects.has(name) || filtered;
      return `<tr class="grp click" data-g="${esc(name)}" aria-expanded="${isOpen}">
        <td><div class="grp-name"><span class="grp-car">${svg('<path d="m9 6 6 6-6 6"/>')}</span><span class="t1">${esc(name)}</span></div>
          <div class="t2 grp-meta">${ss.length} session${ss.length > 1 ? "s" : ""} · last ${dt(Math.max(...ss.map((s) => s.ended || s.started || 0)))}<span class="share" title="${pct(cost / total, 1)} of the spend shown"><i style="width:${(100 * cost) / total}%"></i></span></div></td>
        <td class="hide-sm nw">${[...new Set(ss.map((s) => s.agent))].map((a) => agentIcon(a, 16)).join(" ")}</td>
        <td class="n hide-sm">${day(Math.min(...ss.map((s) => s.started || Infinity)))}</td>
        <td class="n hide-sm">${int(ss.reduce((a, s) => a + (s.n_requests || 0), 0))}</td>
        <td class="n hide-sm">${tok(Math.max(...ss.map((s) => s.peak_context || 0)) || null)}</td><td class="n hide-sm"></td>
        <td class="n">${priced.length ? usd(cost) : DASH}${priced.length < ss.length && priced.length ? `<div class="t2">${ss.length - priced.length} unpriced</div>` : ""}</td></tr>
        ${isOpen ? ss.map((s) => sessRow(s, " in-grp")).join("") : ""}`;
    }).join("");
  };
  const render = () => {
    el.innerHTML = `<div class="card-h"><h2>${group === "project" ? "Projects" : "All sessions"}</h2>
        <span class="seg" role="group" aria-label="Group sessions"><button data-g-mode="list" aria-pressed="${group === "list"}">List</button><button data-g-mode="project" aria-pressed="${group === "project"}">By project</button></span></div>
      <table class="fit">${head}<tbody>${group === "project" ? groups() : sessions.map((s) => sessRow(s)).join("")}</tbody></table>`;
    el.querySelectorAll("[data-g-mode]").forEach((b) => b.addEventListener("click", () => { group = b.dataset.gMode; localSet("sess-group", group); render(); }));
    el.querySelectorAll("tr.grp").forEach((tr) => tr.addEventListener("click", () => {
      const k = tr.dataset.g;
      if (openProjects.has(k)) openProjects.delete(k); else openProjects.add(k);
      render();
    }));
    wireRows();
  };
  state.rerenderTable = render;
  render();
}

async function viewSessions(params) {
  setNav("sessions");
  const q = params.get("q") || "", agent = params.get("agent") || "", project = params.get("project") || "";
  const d = await api(`sessions?${daysQ()}&q=${encodeURIComponent(q)}&agent=${encodeURIComponent(agent)}&project=${encodeURIComponent(project)}`);
  const all = state.cache.allSessions || (state.cache.allSessions = (await api("sessions")).sessions);
  const projects = [...new Set(all.map((s) => s.project).filter(Boolean))].sort();
  const total = d.sessions.reduce((a, s) => a + (s.tree_cost ?? s.cost.estimated ?? 0), 0);
  main.innerHTML = `
    <div class="title-row"><div><h1>Sessions</h1><p class="finding">${d.sessions.length} sessions${q || agent || project ? " match" : ""}, ${usd(total)} estimated.</p></div>${periodSeg()}</div>
    <form class="filters" id="f" role="search">
      <input type="search" name="q" placeholder="Search titles, prompts, paths, ids" value="${esc(q)}" aria-label="Search sessions">
      <select name="agent" aria-label="Agent"><option value="">All agents</option>${[...new Set(all.map((s) => s.agent))].sort().map((a) => `<option value="${a}" ${a === agent ? "selected" : ""}>${agentName(a)}</option>`).join("")}</select>
      <select name="project" aria-label="Project"><option value="">All projects</option>${projects.map((p) => `<option ${p === project ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
    </form>
    ${d.sessions.length ? '<section class="card tl-card" id="stl"></section>' : ""}
    <section class="card" id="stab">${d.sessions.length ? "" : '<p class="empty">No sessions match these filters.</p>'}</section>`;
  wirePeriod(() => viewSessions(params));
  if (d.sessions.length) { sessionTimeline($("#stl"), d.sessions); sessTable($("#stab"), d.sessions, !!(q || agent || project)); }
  const f = $("#f");
  let t;
  const go = () => { const p = new URLSearchParams(new FormData(f)); for (const [k, v] of [...p]) if (!v) p.delete(k); location.hash = "#/sessions" + (p.toString() ? "?" + p : ""); };
  f.addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(go, e.target.type === "search" ? 300 : 0); });
  f.addEventListener("submit", (e) => { e.preventDefault(); go(); });
  if (q) { const i = f.q; i.focus(); i.setSelectionRange(q.length, q.length); }
}

/* ---------- session detail ---------- */
const SERIES = [
  { key: "read", color: "var(--neutral-3)", label: "Read from cache" },
  { key: "write", color: "var(--accent)", label: "Written to cache" },
  { key: "input", color: "var(--neutral-1)", label: "Uncached input" },
];
async function viewSession(key, params) {
  setNav("sessions");
  const tab = params.get("tab") || "trace";
  let d = state.cache["s:" + key];
  if (!d) { d = await api("session?key=" + encodeURIComponent(key)); state.cache = { allSessions: state.cache.allSessions, ["s:" + key]: d }; }
  const s = d.summary, c = s.cost;
  const window = s.context_window || ((s.models && Object.keys(s.models).some((m) => m.startsWith("claude-") && !m.includes("haiku-4"))) ? 1000000 : null);
  const tabs = [["trace", "Trace"], ["timeline", "Timeline"], ["context", "Context"], ["cost", "Cost & latency"], ["tools", "Tools"]];
  if (d.children.length) tabs.push(["subagents", `Subagents (${d.children.length})`]);
  const back = d.parent ? `<a class="crumb" href="${sessHref(d.parent.key)}">← ${esc(d.parent.title)}</a>` : `<a class="crumb" href="#/sessions">← Sessions</a>`;
  main.innerHTML = `
    <div class="title-row"><div>${back}<h1>${esc(s.title)}</h1>
      <div class="meta-line"><span class="agl">${agentIcon(s.agent)}${agentName(s.agent)} ${esc(s.version || "")}</span><span>${esc(s.project || "—")}${s.branch ? " · " + esc(s.branch) : ""}</span><span>${dt(s.started)} – ${clock(s.ended)}</span><span>${modelChips(s.models, 3) || "no model calls"}</span>${s.subagent ? `<span>subagent: ${esc(s.subagent.type || "")} — ${esc(s.subagent.description || "")}</span>` : ""}</div></div>
      <a class="btn" href="${sessHref(key, "tab=context")}">Inspect context</a></div>
    <div class="kpis" style="--n:6">
      <div class="kpi"><div class="l">Cost${d.children.length ? " with subagents" : ""} ${c.estimated == null ? B.u : B.e}</div><div class="v">${usd(d.children.length ? d.tree_cost : c.estimated)}</div><div class="s">${[d.children.length ? usd(c.estimated) + " this thread" : "", c.measured != null ? usd(c.measured) + " measured" : "", c.unpriced_models.length ? "no price for " + esc(c.unpriced_models.join(", ")) : ""].filter(Boolean).join(" · ") || "no measured total in log"}</div></div>
      <div class="kpi"><div class="l">Requests ${B.m}</div><div class="v">${int(s.n_requests)}</div><div class="s">${s.n_user} prompts · ${s.n_compactions} compactions</div></div>
      <div class="kpi"><div class="l">Peak context ${B.m}</div><div class="v">${tok(s.peak_context)}</div><div class="s">${window && s.peak_context ? pct(s.peak_context / window) + " of " + tok(window) + " window" : "baseline " + tok(s.baseline_context)}</div></div>
      <div class="kpi"><div class="l">Cache hit ${B.m}</div><div class="v">${pct(s.cache_hit_rate, 1)}</div><div class="s">${s.signals.cache_rebuilds.length} cache rebuilds</div></div>
      <div class="kpi"><div class="l">Tool calls ${B.m}</div><div class="v">${int(s.n_tool_calls)}</div><div class="s">${s.n_tool_errors} errors</div></div>
      <div class="kpi"><div class="l">Active time ${s.active_ms ? B.m : B.u}</div><div class="v">${dur(s.active_ms)}</div><div class="s">${s.median_latency_s != null ? "median response gap " + s.median_latency_s + " s" : s.median_turn_ms ? "median turn " + dur(s.median_turn_ms) : "&nbsp;"}</div></div>
    </div>
    <section class="card" style="margin-bottom:20px"><div class="card-h"><h2>Context per request</h2>
      <div class="legend">${SERIES.map((x) => `<span><i style="background:${x.color}"></i>${x.label}</span>`).join("")}</div></div>
      <div id="strip"></div>
      <p class="small muted" style="margin:8px 0 0">Every column is one API call; its height is everything the model read. Tall accent columns are the cache being rebuilt. Click a column to inspect that request.</p></section>
    <div class="tabs" role="tablist">${tabs.map(([k, l]) => `<a role="tab" href="${sessHref(key, "tab=" + k)}" ${k === tab ? 'aria-current="page"' : ""}>${l}</a>`).join("")}</div>
    <div id="tab"></div>`;
  const marks = [];
  d.requests.forEach((r, i) => { if (r.after_compaction_reset) marks.push({ i, label: "compacted" }); });
  const strip = $("#strip");
  if (d.requests.length && d.requests.every((r) => r.aggregate)) {
    strip.closest("section").innerHTML = `<div class="card-h"><h2>Token totals per model</h2><span class="sub">${B.m} ${esc(agentName(s.agent))} logs totals, not each API call</span></div>
      <table class="fit"><thead><tr><th>Model</th><th>Task</th><th class="n">Calls</th><th class="n">Input</th><th class="n">Cache read</th><th class="n">Output</th><th class="n">Cost</th></tr></thead><tbody>
      ${d.requests.map((r) => `<tr><td>${esc(r.model || "—")}</td><td>${esc(r.effort || "main")}</td><td class="n">${int(r.aggregate)}</td><td class="n">${tok(r.usage.input)}</td><td class="n">${tok(r.usage.cache_read)}</td><td class="n">${tok(r.usage.output)}</td><td class="n">${r.cost == null ? DASH : usd(r.cost, 4)}</td></tr>`).join("")}
      </tbody></table>`;
  } else if (d.requests.length) {
    columns(strip, d.requests.map((r, i) => ({
      label: "#" + i,
      parts: { read: r.usage.cache_read, write: r.usage.cache_write_5m + r.usage.cache_write_1h, input: r.usage.input },
      tip: `Request #${i} · ${esc(clock(r.t))} · ${esc(modelName(r.model))}${r.effort ? " · " + esc(r.effort) + " effort" : ""}<br>${int(promptTok(r.usage))} prompt tokens: ${int(r.usage.cache_read)} read, ${int(r.usage.cache_write_5m + r.usage.cache_write_1h)} written, ${int(r.usage.input)} uncached<br>${int(r.usage.output)} output · ${r.cost == null ? "unpriced" : usd(r.cost, 4) + " estimated"}`,
    })), SERIES, { height: 170, marks, onClick: (i) => { location.hash = sessHref(key, "tab=context&req=" + i); } });
  } else strip.innerHTML = '<p class="empty">This session made no API requests.</p>';
  const el = $("#tab");
  if (tab === "timeline") return tabTimeline(el, d, params);
  if (tab === "trace") return tabTrace(el, key, d);
  if (tab === "context") return tabContext(el, key, d, params);
  if (tab === "cost") return tabCost(el, d);
  if (tab === "tools") return tabTools(el, d);
  if (tab === "subagents") return tabSubagents(el, d);
}

const KINDS = { user: "Prompt", assistant: "Reply", thinking: "Thinking", tool_call: "Tool", hook: "Hook", meta: "Injected", system: "System", compaction: "Compaction", compaction_summary: "Summary", error: "Error" };
const FILTERS = [["all", "All"], ["user", "Prompts"], ["assistant", "Replies"], ["tool_call", "Tools"], ["thinking", "Thinking"], ["context", "Injected & hooks"], ["error", "Errors"]];
function tabTimeline(el, d, params) {
  let filter = params.get("k") || "all", needle = "", limit = 300;
  const mixed = Object.keys(d.summary.models || {}).length > 1;  // tag model output only when the session switched models
  const reqModel = (i) => (d.requests[i] || {}).model;
  const matches = (e) => {
    if (filter === "context" && !["hook", "meta", "system", "compaction", "compaction_summary"].includes(e.kind)) return false;
    if (filter === "error" && !(e.kind === "error" || e.is_error)) return false;
    if (!["all", "context", "error"].includes(filter) && e.kind !== filter) return false;
    if (filter === "all" && e.kind === "thinking" && !e.chars) return false; // empty (hidden) thinking adds only noise
    if (needle && !((e.text || "") + (e.name || "") + (e.input || "") + (e.output || "")).toLowerCase().includes(needle)) return false;
    return true;
  };
  const render = () => {
    const evs = d.events.filter(matches);
    const t0 = d.summary.started;
    el.innerHTML = `<div class="tl-tools">${FILTERS.map(([k, l]) => `<button class="chip" data-k="${k}" aria-pressed="${k === filter}">${l}</button>`).join("")}
      <input type="search" class="chip" style="padding:3px 10px;min-width:200px" placeholder="Find in timeline" value="${esc(needle)}" aria-label="Find in timeline"></div>
      <div class="tl">${evs.slice(0, limit).map((e) => evRow(e, t0, mixed ? reqModel : null)).join("") || '<p class="empty">Nothing matches.</p>'}</div>
      ${evs.length > limit ? `<p><button class="btn" id="more">Show ${Math.min(300, evs.length - limit)} more of ${evs.length - limit}</button></p>` : ""}`;
    el.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => { filter = b.dataset.k; limit = 300; render(); }));
    const inp = el.querySelector("input[type=search]");
    inp.addEventListener("input", () => { needle = inp.value.toLowerCase(); clearTimeout(inp._t); inp._t = setTimeout(() => { render(); const i = el.querySelector("input[type=search]"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); });
    el.querySelectorAll(".ev [data-toggle]").forEach((x) => x.addEventListener("click", () => x.closest(".ev").classList.toggle("open")));
    const m = $("#more", el); if (m) m.addEventListener("click", () => { limit += 300; render(); });
  };
  render();
}
function evRow(e, t0, reqModel) {
  const rel = e.t && t0 ? Math.round(e.t - t0) : null;
  const time = rel == null ? "" : rel < 3600 ? `+${Math.floor(rel / 60)}:${String(rel % 60).padStart(2, "0")}` : clock(e.t);
  const m = reqModel && e.req != null ? reqModel(e.req) : null;
  const kind = `<b>${KINDS[e.kind] || esc(e.kind)}</b>${e.name && e.kind !== "tool_call" ? `<div class="small">${esc(e.name)}</div>` : ""}${m ? `<div>${mdl(m)}</div>` : ""}`;
  if (e.kind === "tool_call") {
    const sum = summarizeInput(e.name, e.input);
    return `<div class="ev tool_call"><div class="ev-time">${time}</div><div class="ev-kind">${kind}</div>
      <div class="ev-body"><span class="tool-sum" data-toggle><span class="nm">${esc(e.name)}</span> <span class="muted">${esc(sum)}</span></span>
      ${e.child_key ? `<div class="small"><a href="${sessHref(e.child_key)}">Open subagent session →</a></div>` : ""}
      <div class="io"><div class="lbl">Input · ${int(e.input_chars)} chars</div><pre>${esc(e.input)}</pre>
      ${e.output != null ? `<div class="lbl">Result · ${int(e.output_chars)} chars ≈ ${tok(e.output_chars / 4)} tokens ${B.e}</div><pre>${esc(e.output)}</pre>` : '<div class="lbl">No result recorded</div>'}</div></div>
      <div class="ev-side">${e.is_error ? '<span class="tag bad">error</span> ' : ""}${e.output_chars != null ? tok(e.output_chars / 4) + " tok" : ""}${e.dur_ms != null ? " · " + dur(e.dur_ms) : ""}</div></div>`;
  }
  const long = (e.text || "").length > 400 || (e.text || "").split("\n").length > 6;
  return `<div class="ev ${e.kind}"><div class="ev-time">${time}</div><div class="ev-kind">${kind}</div>
    <div class="ev-body"><div class="ev-text">${esc(e.text || (e.kind === "thinking" ? "[thinking not displayed in logs]" : ""))}</div>${long ? '<button class="linkish small" data-toggle>Show all</button>' : ""}</div>
    <div class="ev-side">${e.chars ? tok(e.chars / 4) + " tok" : ""}</div></div>`;
}
function summarizeInput(name, input) {
  try {
    const j = JSON.parse(input);
    if (typeof j === "string") return j.slice(0, 160);
    const v = j.command || j.file_path || j.pattern || j.url || j.query || j.description || j.prompt || j.cmd || j.path;
    if (v) return String(v).slice(0, 160);
    return Object.entries(j).slice(0, 2).map(([k, x]) => `${k}: ${typeof x === "string" ? x : JSON.stringify(x)}`).join(", ").slice(0, 160);
  } catch { return String(input || "").replace(/\s+/g, " ").slice(0, 160); }
}

/* ---------- trace: span tree (session → prompts → model calls, tools, subagents) on one clock ---------- */
const GAP = 20;  // s; in "active time" mode, idle stretches longer than this are cut to this
const ico = (g) => `<span class="tr-ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${g}</svg></span>`;
const TI = {
  llm: '<path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9-1.9 5.1-1.9-5.1-5.1-1.9 5.1-1.9z"/><path d="M18.5 16v4M16.5 18h4"/>',
  terminal: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="m7.5 9.5 3 2.5-3 2.5M13 15h4"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  edit: '<path d="M4 20h4L19 9a2.1 2.1 0 0 0-4-4L4 16z"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
  web: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.6 2.6 14.4 0 17M12 3.5c-2.6 2.6-2.6 14.4 0 17"/>',
  mcp: '<path d="M9 3v5M15 3v5M6.5 8h11v3a5.5 5.5 0 0 1-11 0zM12 16.5V21"/>',
  skill: '<path d="M5 4.5h9.5A4.5 4.5 0 0 1 19 9v11H9.5A4.5 4.5 0 0 1 5 15.5z"/><path d="M9 9h6"/>',
  todo: '<path d="M10 6h10M10 12h10M10 18h10M4 6l1.5 1.5L8 5M4 12l1.5 1.5L8 11M4.5 18h.01"/>',
  tool: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5h4"/>',
  turn: '<path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H10l-5 4z"/>',
};
function toolKind(n) {
  n = (n || "").toLowerCase();
  if (n.startsWith("mcp__")) return "mcp";
  if (/web|fetch|url|browser|http/.test(n)) return "web";
  if (/bash|exec|terminal|shell|command|process/.test(n)) return "terminal";
  if (/edit|write|patch|apply|notebook/.test(n)) return "edit";
  if (/grep|glob|search|find|^ls$|list_dir/.test(n)) return "search";
  if (/read|view|cat|open/.test(n)) return "file";
  if (/skill/.test(n)) return "skill";
  if (/todo|task/.test(n)) return "todo";
  return "tool";
}
const money = (x) => x == null ? "" : x > 0 && x < 0.1 ? "$" + x.toFixed(x < 0.01 ? 4 : 3) : usd(x);
const sumU = (u) => u ? u.input + u.output + u.cache_read + u.cache_write_5m + u.cache_write_1h : 0;
const mss = (s) => { s = Math.max(0, Math.round(s)); return s < 60 ? s + "s" : s < 3600 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
const hms = (t) => new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
/* Harness messages (e.g. <task-notification>) are shown by their <summary>, not their tags. */
const promptLabel = (t) => { const m = /<summary>([\s\S]*?)<\/summary>/.exec(t || ""); return m ? m[1].trim() : firstLine((t || "").replace(/<[^>]+>/g, " ")); };
const firstLine = (t) => (t || "").replace(/[#*`>_|]/g, "").split("\n").map((x) => x.trim()).find(Boolean) || "";

/* Spans of one session. A model call starts where the previous logged event ended (estimated). */
function traceSession(d, key, depth, cache) {
  const kids = Object.fromEntries((d.children || []).map((c) => [c.key, c]));
  const evs = d.events.filter((e) => e.t);
  const ends = [...evs.map((e) => e.t + (e.dur_ms || 0) / 1000), ...d.requests.filter((r) => r.t).map((r) => r.t_end || r.t)].sort((a, b) => a - b);
  const before = (t) => { let x = null; for (const v of ends) { if (v < t - 1e-3) x = v; else break; } return x; };
  const out = [];
  d.requests.forEach((r, i) => {
    if (!r.t || r.aggregate) return;
    const b = r.t_end || r.t, a = r.latency_s != null ? r.t - r.latency_s : (before(r.t) ?? r.t);
    const reply = evs.filter((e) => e.req === i && e.kind === "assistant").map((e) => e.text).join("\n\n");
    const calls = [...new Set(evs.filter((e) => e.req === i && e.kind === "tool_call").map((e) => e.name))];
    out.push({ id: key + "#r" + i, kind: "llm", a, b, depth, key, req: i, r, reply, calls, icon: TI.llm,
      label: firstLine(reply).slice(0, 100) || (calls.length ? "Calls " + calls.join(", ") : "Thinking"), sub: modelName(r.model), cost: r.cost, tokens: sumU(r.usage) });
  });
  evs.filter((e) => e.kind === "tool_call").forEach((e) => {
    const end = e.t + (e.dur_ms || 0) / 1000, base = { id: e.id || key + "#e" + e.i, a: e.t, depth, key, e };
    if (!e.child_key) {
      out.push({ ...base, kind: "tool", b: end, nodur: e.dur_ms == null, icon: TI[toolKind(e.name)], label: e.name, sub: summarizeInput(e.name, e.input), tokens: e.output_chars ? e.output_chars / 4 : 0, err: e.is_error ? 1 : 0 });
      return;
    }
    const c = kids[e.child_key];
    const s = { ...base, kind: "agent", b: Math.max(end, (c && c.ended) || 0), child: e.child_key, cs: c, lazy: true,
      label: (c && c.subagent && c.subagent.description) || summarizeInput(e.name, e.input) || "Subagent", sub: c ? modelText(c.models) || e.name : e.name,
      cost: c ? c.cost.estimated : null, tokens: c ? sumU(c.usage) : 0, err: c ? c.n_tool_errors : 0, agent: d.summary.agent };
    const cd = cache[e.child_key];
    if (cd) { s.kids = traceSession(cd, e.child_key, depth + 1, cache); s.kids.forEach((k) => { s.b = Math.max(s.b, k.b); }); }
    out.push(s);
  });
  return out.sort((x, y) => x.a - y.a || (x.kind === "llm" ? -1 : 1));
}
/* Root → prompts (when there is more than one) → spans. */
function traceTree(d, key, cache) {
  const items = traceSession(d, key, 2, cache);
  const prompts = d.events.filter((e) => e.t && e.kind === "user");
  let top = items;
  if (prompts.length > 1) {
    const turns = prompts.map((p, j) => { const sys = /^\s*<[a-z-]+>/.test(p.text || "");
      return { id: key + "#t" + j, kind: "turn", depth: 1, a: p.t, b: p.t, icon: sys ? TI.bell : TI.turn, label: promptLabel(p.text).slice(0, 140) || "Prompt", sub: sys ? "notification" : "", full: p.text, kids: [] }; });
    if (items.some((it) => it.b < prompts[0].t)) turns.unshift({ id: key + "#t-", kind: "turn", depth: 1, a: items[0].a, b: items[0].a, icon: TI.turn, label: "Before the first prompt", kids: [] });
    const off = turns.length - prompts.length;
    items.forEach((it) => {  // by end time: a call answering a prompt ends after it
      let k = -1;
      prompts.forEach((p, j) => { if (p.t <= it.b + 1e-3) k = j; });
      turns[Math.max(0, k + off)].kids.push(it);
    });
    top = turns.filter((t) => t.kids.length || t.full);
  } else items.forEach((it) => { it.depth = 1; (it.kids || []).forEach(function f(k) { k.depth--; (k.kids || []).forEach(f); }); });
  const s = d.summary;
  const root = { id: key + "#root", kind: "root", depth: 0, icon: null, agent: s.agent, label: s.subagent ? "Subagent" : agentName(s.agent), sub: modelText(s.models), kids: top };
  const fit = (x) => {  // containers span their children and sum their cost and tokens
    if (!x.kids || !x.kids.length) return;
    x.kids.forEach(fit);
    if (x.kind === "agent") return;  // its cost and tokens come from the subagent's own summary
    x.a = Math.min(...x.kids.map((k) => k.a), x.a ?? Infinity);
    x.b = Math.max(...x.kids.map((k) => k.b), x.b ?? -Infinity);
    x.cost = x.kids.some((k) => k.cost != null) ? x.kids.reduce((t, k) => t + (k.cost || 0), 0) : null;  // unpriced stays unknown, never $0
    x.tokens = x.kids.reduce((t, k) => t + (k.tokens || 0), 0);
  };
  fit(root);
  root.cost = s.cost.estimated == null && root.cost == null ? null : d.tree_cost ?? s.cost.estimated;
  return root;
}
/* Piecewise-linear clock. "active" keeps busy time and cuts idle gaps longer than GAP; "wall" is real time. */
function traceClock(root, mode, until) {
  const iv = [];
  (function walk(x) { if (x.kind !== "root" && x.kind !== "turn") iv.push([x.a, Math.max(x.a, x.b)]); (x.kids || []).forEach(walk); })(root);
  if (until) iv.push([until, until]);
  iv.sort((x, y) => x[0] - y[0]);
  if (!iv.length) return null;
  const t0 = iv[0][0];
  if (mode === "wall") {
    const t1 = Math.max(...iv.map((x) => x[1]));
    return { map: (t) => t - t0, inv: (c) => t0 + c, total: Math.max(t1 - t0, 1), gaps: [] };
  }
  const bl = [];
  for (const [a, b] of iv) {
    const l = bl[bl.length - 1];
    if (l && a <= l.b + GAP) l.b = Math.max(l.b, b);
    else bl.push({ a, b, c: l ? l.c + (l.b - l.a) + GAP : 0, gap: l ? a - l.b : 0 });
  }
  const find = (t) => { let k = 0; while (k + 1 < bl.length && bl[k + 1].a <= t) k++; return bl[k]; };
  const map = (t) => { const x = find(t); return t <= x.b ? x.c + Math.max(0, t - x.a) : x.c + (x.b - x.a) + Math.min(t - x.b, GAP); };
  const inv = (c) => { let x = bl[0]; for (const y of bl) if (y.c <= c) x = y; return c - x.c <= x.b - x.a ? x.a + (c - x.c) : x.b + (c - x.c - (x.b - x.a)); };
  const last = bl[bl.length - 1];
  return { map, inv, total: Math.max(last.c + (last.b - last.a), 1), gaps: bl.slice(1).map((x) => ({ at: x.c - GAP / 2, real: x.gap })) };
}

function tabTrace(el, key, d) {
  const cache = {}, open = new Set([key + "#root"]), loading = new Set();
  let mode = localGet("trace-mode", "active"), view = null, selId = null, needle = "", root, clock, rows = [], badges = {};
  const isLive = () => d.summary.ended && Date.now() / 1000 - d.summary.ended < 120;
  const KIND = { root: "Session", turn: "Prompt", llm: "Model call", tool: "Tool call", agent: "Subagent" };
  const pos = (p) => `calc(16px + (100% - 32px) * ${p / 100})`;
  const flat = (x) => [x, ...(x.kids || []).flatMap(flat)];

  const rebuild = () => {
    root = traceTree(d, key, cache);
    if (open.size === 1) root.kids.forEach((k) => { if (k.kind === "turn" && root.kids.length <= 8) open.add(k.id); });
    clock = traceClock(root, mode, isLive() ? Date.now() / 1000 : null);
    const leaves = flat(root).filter((s) => s.kind === "llm" || s.kind === "tool");
    const slow = leaves.filter((s) => !s.nodur).sort((x, y) => (y.b - y.a) - (x.b - x.a))[0];
    const pricey = leaves.filter((s) => s.cost).sort((x, y) => y.cost - x.cost)[0];
    badges = {};
    if (slow) badges[slow.id] = ["SLOWEST"];
    if (pricey) (badges[pricey.id] = badges[pricey.id] || []).push("PRICIEST");
  };
  rebuild();
  if (!clock) { el.innerHTML = '<p class="empty">Nothing to trace: this session logged no timed model or tool calls.</p>'; return; }

  // headline numbers include subagents (from their summaries, loaded or not); redrawn on every live refresh
  const kpi = (l, v, sub, basis = "") => `<div><div class="l">${l} ${basis}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
  const kpis = () => {
    const s = d.summary, ch = d.children || [];
    const tokens = sumU(s.usage) + ch.reduce((t, c) => t + sumU(c.usage), 0);
    const calls = s.n_requests + ch.reduce((t, c) => t + c.n_requests, 0);
    const tools = s.n_tool_calls + ch.reduce((t, c) => t + c.n_tool_calls, 0);
    const errs = s.n_tool_errors + ch.reduce((t, c) => t + c.n_tool_errors, 0);
    return `${kpi("Duration", `<span id="tr-dur"></span>`, `<span id="tr-dur-s"></span>`, B.e)}
      ${kpi("Cost", usd(root.cost), ch.length ? "with " + ch.length + " subagents" : "this session", root.cost == null ? B.u : B.e)}
      ${kpi("Tokens", tok(tokens), pct(s.cache_hit_rate) + " read from cache", B.m)}
      ${kpi("LLM calls", int(calls), s.median_latency_s != null ? "median " + s.median_latency_s + " s" : "&nbsp;", B.m)}
      ${kpi("Tool calls", int(tools), Object.keys(s.tools || {}).length + " distinct tools", B.m)}
      ${kpi("Errors", `<span class="${errs ? "bad" : ""}">${int(errs)}</span>`, errs ? "tool calls that failed" : "no failed tool calls", B.m)}`;
  };
  const s = d.summary;
  el.innerHTML = `<section class="card tr-card">
    <div class="tr-head">${ico(TI.llm)}<h2>Trace</h2><span class="tr-title">${esc(s.title)}</span>${isLive() ? '<span class="tr-live"><i></i>Live</span>' : ""}</div>
    <div class="tr-kpis"></div>
    <div class="tr-tools">
      <input type="search" class="chip tr-find" placeholder="Find a span" aria-label="Find a span">
      <span class="seg" role="group" aria-label="Time axis"><button data-mode="active" title="Idle gaps over ${GAP} s are cut out">Active time</button><button data-mode="wall">Wall clock</button></span>
      <button class="chip" data-x="open">Expand all</button><button class="chip" data-x="close">Collapse all</button>
      <button class="chip" data-x="reset" hidden>Reset zoom</button>
      <span class="legend tr-legend"><span><i class="k-llm"></i>Model call</span><span><i class="k-tool"></i>Tool</span><span><i class="k-agent"></i>Subagent</span><span><i class="k-err"></i>Error</span></span>
    </div>
    <div class="tr-wrap"><div class="tr-body" tabindex="0" role="tree" aria-label="Session trace. Up and down move, right expands, left collapses, Enter opens details."></div><aside class="tr-panel" hidden></aside></div>
    <p class="small muted tr-help">Hover to read the clock · drag across the bars to zoom · double-click a span to zoom to it · click for details · ↑ ↓ ← → keys work too</p></section>`;
  const body = $(".tr-body", el), panel = $(".tr-panel", el), find = $(".tr-find", el);

  const label = (x) => {
    if (x.kind === "turn" && !x.kids.length) return '<span class="muted">no model or tool calls</span>';
    const ds = x.nodur ? "" : dur((x.b - x.a) * 1000);
    const bits = [ds, money(x.cost)].filter(Boolean).join(" · ");
    const bd = [...(badges[x.id] || []).map((b) => `<em class="bd ${b === "SLOWEST" ? "slow" : "cost"}">${b}</em>`),
      x.err ? `<em class="bd err">${x.kind === "agent" ? x.err + (x.err > 1 ? " ERRORS" : " ERROR") : "ERROR"}</em>` : ""].join("");
    return bits + bd;
  };
  const matches = (x) => !needle || (x.label + " " + (x.sub || "") + " " + (x.e ? x.e.input || "" : "")).toLowerCase().includes(needle);
  const draw = () => {
    const [v0, v1] = view || [0, clock.total];
    const X = (t) => (clock.map(t) - v0) / (v1 - v0) * 100;
    // when searching, open every container that holds a match
    if (needle) (function walk(x) { let hit = matches(x); (x.kids || []).forEach((k) => { if (walk(k)) { hit = true; open.add(x.id); } }); return hit; })(root);
    rows = [];
    (function add(x) { rows.push(x); if (open.has(x.id)) (x.kids || []).forEach(add); })(root);
    const span = v1 - v0, step = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 21600].find((v) => span / v <= 6) || 43200;
    let ticks = "";
    for (let v = Math.ceil(v0 / step) * step; v <= v1; v += step) ticks += `<i class="tk" style="left:${pos((v - v0) / span * 100)}"><span>${mss(v)}</span></i>`;
    const gm = [];  // idle-gap marks; ones closer than 4% of the width merge into one so the axis stays readable
    clock.gaps.filter((g) => g.at > v0 && g.at < v1).forEach((g) => { const p = (g.at - v0) / span * 100, l = gm[gm.length - 1]; if (l && p - l.p < 4) { l.n++; l.real += g.real; } else gm.push({ p, n: 1, real: g.real }); });
    const gaps = gm.map((g) => `<i class="gp" style="left:${pos(g.p)}" data-tip="${g.n > 1 ? g.n + " idle gaps" : "Idle"} · ${esc(dur(g.real * 1000))} real time, each shown as ${GAP} s"></i>`).join("");
    const now = isLive() ? X(Date.now() / 1000) : null;
    const guides = (x) => Array.from({ length: x.depth }, (_, j) => `<i class="tr-g" style="left:calc(17px + ${j} * var(--ind))"></i>`).join("");
    body.innerHTML = `<div class="tr-grid" aria-hidden="true">${ticks.replace(/<span>.*?<\/span>/g, "")}${now != null && now <= 100 ? `<i class="now" style="left:${pos(now)}"></i>` : ""}<i class="cur" hidden></i><i class="shade" hidden></i></div>
      <div class="tr-row tr-axis"><div class="tr-name">SPAN</div><div class="tr-plot">${ticks}${gaps}<span class="cur-lab" hidden></span>${now != null && now <= 100 ? `<i class="now-dot" style="left:${pos(now)}"></i>` : ""}</div></div>`
      + rows.map((x, i) => {
        const a = Math.max(X(x.a), 0), b = Math.min(X(Math.max(x.b, x.a)), 100), vis = b >= 0 && a <= 100;
        const can = x.kids ? x.kids.length > 0 : x.lazy;
        const isOpen = open.has(x.id);
        const icon = x.kind === "root" || x.kind === "agent" ? `<span class="tr-ic ag">${agentIcon(x.agent, 18)}</span>` : ico(x.icon);
        const lab = label(x), place = b <= 68 ? "after" : a >= 30 ? "before" : "inside";  // keep the label on screen
        const kindCls = x.err && x.kind === "tool" ? "err" : x.kind;
        return `<div class="tr-row k-${x.kind}${x.id === selId ? " sel" : ""}${needle && !matches(x) ? " dim" : ""}" data-i="${i}" role="treeitem" aria-level="${x.depth + 1}" aria-selected="${x.id === selId}" ${can ? `aria-expanded="${isOpen}"` : ""}>
          <div class="tr-name" style="padding-left:calc(8px + ${x.depth} * var(--ind))">${guides(x)}${can ? `<button class="tr-car${isOpen ? " open" : ""}" data-car="${i}" tabindex="-1" aria-label="${isOpen ? "Collapse" : "Expand"}">${loading.has(x.id) ? "…" : svg('<path d="m9 6 6 6-6 6"/>')}</button>` : '<span class="tr-car"></span>'}
            ${icon}<span class="tr-l"><b>${esc(x.label)}</b>${x.sub ? ` <span class="sub">${esc(x.sub)}</span>` : ""}</span></div>
          <div class="tr-plot">${vis ? `<span class="tr-bar k-${kindCls}${x.nodur ? " nodur" : ""}" style="left:${pos(a)};width:calc((100% - 32px) * ${Math.max(b - a, 0) / 100})"></span>
            <span class="tr-lab ${place}" style="${place === "after" ? `left:calc(${pos(b)} + 8px)` : `right:calc(100% - ${place === "before" ? pos(a) : pos(b)} + 8px)`}">${lab}</span>` : ""}</div></div>`;
      }).join("");
    $(".tr-kpis", el).innerHTML = kpis();
    const [d0, d1] = view ? [clock.inv(v0), clock.inv(v1)] : [root.a, root.b];
    $("#tr-dur", el).textContent = dur((view ? v1 - v0 : clock.total) * 1000);
    $("#tr-dur-s", el).textContent = view ? "zoomed: " + hms(d0) + " – " + hms(d1) : mode === "active" ? `active · ${dur((root.b - root.a) * 1000)} wall clock` : `wall clock · ${hms(root.a)} – ${hms(root.b)}`;
    el.querySelector('[data-x="reset"]').hidden = !view;
    el.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
    showPanel();
  };

  const stat = (l, v) => v == null || v === "" ? "" : `<div><span>${l}</span><b>${v}</b></div>`;
  function showPanel() {
    const x = selId && flat(root).find((y) => y.id === selId);
    panel.hidden = !x;
    el.querySelector(".tr-wrap").classList.toggle("has-panel", !!x);
    if (!x) return;
    const t0 = root.a, e = x.e, u = x.r && x.r.usage;
    let more = "";
    if (x.kind === "llm") more = `<div class="tr-stats">${stat("Model", esc(modelName(x.r.model)))}${stat("Effort", esc(x.r.effort || ""))}${stat("Stop", esc(x.r.stop_reason || ""))}
        ${stat("Cache read", int(u.cache_read))}${stat("Cache written", int(u.cache_write_5m + u.cache_write_1h))}${stat("Uncached in", int(u.input))}${stat("Output", int(u.output))}
        ${stat("Cache hit", pct(u.cache_read / (promptTok(u) || 1)))}</div>
        ${u.cache_write_5m + u.cache_write_1h > 0.5 * promptTok(u) && promptTok(u) > 20000 ? '<p class="tr-note">Most of this prompt was written to cache, not read: the cache was rebuilt here.</p>' : ""}
        <a class="btn sm" href="${sessHref(x.key, "tab=context&req=" + x.req)}">Inspect the context of this call</a>
        ${x.calls.length ? `<div class="lbl">Called</div><p>${x.calls.map((c) => `<span class="mdl">${esc(c)}</span>`).join(" ")}</p>` : ""}
        ${x.reply ? `<div class="lbl">Reply</div><pre>${esc(x.reply)}</pre>` : ""}`;
    else if (x.kind === "tool") more = `<div class="tr-stats">${stat("Status", e.is_error ? '<span class="bad">error</span>' : "ok")}${stat("Result", e.output_chars != null ? `${int(e.output_chars)} chars ≈ ${tok(e.output_chars / 4)} tok` : "")}</div>
        <p class="tr-note">The result enters the context of every later call until the next compaction.</p>
        <div class="lbl">Input</div><pre>${esc(e.input)}</pre>${e.output != null ? `<div class="lbl">Result</div><pre>${esc(e.output)}</pre>` : ""}`;
    else if (x.kind === "agent") { const c = x.cs || {}; more = `<div class="tr-stats">${stat("Type", esc((c.subagent || {}).type || ""))}${stat("Models", esc(x.sub))}${stat("LLM calls", int(c.n_requests))}${stat("Tool calls", int(c.n_tool_calls))}${stat("Errors", int(c.n_tool_errors))}${stat("Cache hit", pct(c.cache_hit_rate))}</div>
        <a class="btn sm" href="${sessHref(x.child)}">Open subagent session</a><div class="lbl">Task</div><pre>${esc(e.input)}</pre>${e.output != null ? `<div class="lbl">Returned</div><pre>${esc(e.output)}</pre>` : ""}`; }
    else if (x.kind === "turn") more = `<div class="tr-stats">${stat("Model calls", d.requests.length && d.requests.every((r) => r.aggregate) ? "not logged per call" : x.kids.filter((k) => k.kind === "llm").length)}${stat("Tool calls", x.kids.filter((k) => k.kind === "tool").length)}${stat("Subagents", x.kids.filter((k) => k.kind === "agent").length)}</div><div class="lbl">Prompt</div><pre>${esc(x.full || x.label)}</pre>`;
    else more = `<div class="tr-stats">${stat("Prompts", s.n_user)}${stat("Peak context", tok(s.peak_context))}${stat("Compactions", s.n_compactions)}</div>`;
    panel.innerHTML = `<div class="tr-p-h">${x.kind === "root" || x.kind === "agent" ? agentIcon(x.agent, 18) : ico(x.icon)}<div><div class="small muted">${KIND[x.kind]}</div><b>${esc(x.label)}</b></div><button class="btn sm" data-close aria-label="Close details">✕</button></div>
      <div class="tr-stats">${stat("Start", `+${mss(clock.map(x.a))} · ${hms(x.a)}`)}${stat("Duration", x.nodur ? "not logged" : dur((x.b - x.a) * 1000))}${stat("Cost", x.cost == null ? "" : money(x.cost) + " " + B.e)}${stat("Tokens", x.tokens ? tok(x.tokens) : "")}${stat("Share of cost", x.cost && root.cost ? pct(x.cost / root.cost, 1) : "")}</div>
      ${more}<button class="btn sm" data-zoom>Zoom to this span</button>`;
  }

  const load = async (x) => {
    if (!x.lazy || cache[x.child]) return;
    loading.add(x.id); draw();
    try { cache[x.child] = await api("session?key=" + encodeURIComponent(x.child)); } catch { cache[x.child] = { events: [], requests: [], children: [], summary: x.cs || {} }; }
    loading.delete(x.id);
    rebuild();
  };
  const toggle = async (x, want) => {
    const to = want ?? !open.has(x.id);
    if (to) { open.add(x.id); await load(x); } else open.delete(x.id);
    draw();
  };
  const select = (x) => { selId = x && x.id !== selId ? x.id : null; draw(); };
  const zoomTo = (x) => { const pad = Math.max((clock.map(x.b) - clock.map(x.a)) * 0.08, 0.5); view = [Math.max(0, clock.map(x.a) - pad), Math.min(clock.total, clock.map(x.b) + pad)]; draw(); };

  // pointer: hover cursor, drag to zoom, click to select
  let drag = null, dragged = false;
  const frac = (ev) => { const g = $(".tr-grid", body).getBoundingClientRect(); return (ev.clientX - g.left - 16) / (g.width - 32); };
  body.addEventListener("pointermove", (ev) => {
    const f = frac(ev), cur = $(".cur", body), lab = $(".cur-lab", body);
    if (f < 0 || f > 1) { cur.hidden = lab.hidden = true; } else {
      const [v0, v1] = view || [0, clock.total], c = v0 + f * (v1 - v0);
      cur.hidden = lab.hidden = false;
      cur.style.left = lab.style.left = pos(f * 100);
      lab.textContent = `+${mss(c)} · ${hms(clock.inv(c))}`;
    }
    if (drag && Math.abs(ev.clientX - drag.x) > 5) {
      if (!dragged) body.setPointerCapture(drag.id);  // capture only once dragging, so plain clicks still hit rows
      dragged = true;
      const sh = $(".shade", body), lo = Math.max(0, Math.min(drag.f, f)), hi = Math.min(1, Math.max(drag.f, f));
      sh.hidden = false; sh.style.left = pos(lo * 100); sh.style.width = `calc((100% - 32px) * ${hi - lo})`;
    }
  });
  body.addEventListener("pointerleave", () => { const c = $(".cur", body); if (c) c.hidden = $(".cur-lab", body).hidden = true; });
  body.addEventListener("pointerdown", (ev) => {
    dragged = false;
    if (ev.button || ev.target.closest("button")) return;
    const f = frac(ev);
    if (f >= 0 && f <= 1) drag = { x: ev.clientX, f, id: ev.pointerId };
  });
  body.addEventListener("pointerup", (ev) => {
    if (drag && dragged) {
      const [v0, v1] = view || [0, clock.total], f = frac(ev);
      const lo = Math.max(0, Math.min(drag.f, f)), hi = Math.min(1, Math.max(drag.f, f));
      if ((hi - lo) * (v1 - v0) > 0.2) view = [v0 + lo * (v1 - v0), v0 + hi * (v1 - v0)];
      draw();
    }
    drag = null;
  });
  body.addEventListener("click", (ev) => {
    if (dragged) { dragged = false; return; }
    const c = ev.target.closest("[data-car]");
    if (c) { toggle(rows[+c.dataset.car]); return; }
    const r = ev.target.closest(".tr-row[data-i]");
    if (r) select(rows[+r.dataset.i]);
  });
  body.addEventListener("dblclick", (ev) => { const r = ev.target.closest(".tr-row[data-i]"); if (r) zoomTo(rows[+r.dataset.i]); });
  body.addEventListener("keydown", (ev) => {
    let i = rows.findIndex((x) => x.id === selId);
    const x = rows[i];
    const act = {
      ArrowDown: () => { selId = rows[Math.min(rows.length - 1, i + 1)].id; draw(); },
      ArrowUp: () => { selId = rows[Math.max(0, i - 1)].id; draw(); },
      ArrowRight: () => x && toggle(x, true),
      ArrowLeft: () => { if (!x) return; if (open.has(x.id) && (x.kids || x.lazy)) toggle(x, false); else { const p = rows.slice(0, i).reverse().find((y) => y.depth < x.depth); if (p) { selId = p.id; draw(); } } },
      Enter: () => x && toggle(x),
      Escape: () => { if (view) view = null; else selId = null; draw(); },
    }[ev.key];
    if (act) { ev.preventDefault(); act(); const s = body.querySelector(".tr-row.sel"); if (s) s.scrollIntoView({ block: "nearest" }); }
  });
  panel.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-close]")) select(null);
    if (ev.target.closest("[data-zoom]")) zoomTo(flat(root).find((y) => y.id === selId));
  });
  el.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { mode = b.dataset.mode; localSet("trace-mode", mode); view = null; rebuild(); draw(); }));
  el.querySelectorAll("[data-x]").forEach((b) => b.addEventListener("click", async () => {
    if (b.dataset.x === "reset") view = null;
    else if (b.dataset.x === "close") { open.clear(); open.add(root.id); }
    else { await Promise.all(flat(root).filter((y) => y.lazy).map(load)); flat(root).forEach((y) => { if ((y.kids && y.kids.length) || y.lazy) open.add(y.id); }); }
    draw();
  }));
  find.addEventListener("input", () => { clearTimeout(find._t); find._t = setTimeout(() => { needle = find.value.trim().toLowerCase(); draw(); }, 200); });
  bindTips(body);
  draw();

  // live: re-read the session every 5 s while it is still being written
  if (isLive()) {
    const timer = setInterval(async () => {
      if (!el.isConnected) { clearInterval(timer); return; }
      try {
        d = await api("session?key=" + encodeURIComponent(key));
        for (const k of Object.keys(cache)) if ([...open].some((id) => flat(root).some((y) => y.id === id && y.child === k))) cache[k] = await api("session?key=" + encodeURIComponent(k));
        rebuild(); draw();
        if (!isLive()) { clearInterval(timer); const l = $(".tr-live", el); if (l) l.remove(); }
      } catch { /* server gone: the presence banner says so */ }
    }, 5000);
  }
}

/* Fixed colour per category so a square means the same thing on every request. */
const CAT_COLOR = { "Tool definitions": "var(--cat-1)", "Tool results": "var(--cat-2)", "Tool calls": "var(--cat-3)", "Messages": "var(--cat-4)",
  "Harness injections": "var(--cat-5)", "System prompt": "var(--cat-6)", "Thinking": "var(--cat-7)" };
const GRID_N = 400;  // 20 × 20 squares = the whole context window
function shareCells(parts, n) {  // largest-remainder split of n squares
  const tot = parts.reduce((a, p) => a + Math.max(p.tokens, 0), 0) || 1;
  const raw = parts.map((p) => Math.max(p.tokens, 0) / tot * n);
  const out = raw.map(Math.floor);
  let left = n - out.reduce((a, b) => a + b, 0);
  raw.map((r, i) => [r - out[i], i]).sort((x, y) => y[0] - x[0]).forEach(([, i]) => { if (left > 0) { out[i]++; left--; } });
  return out;
}
function itemHint(x) {  // one-line context next to the label
  if (x.hidden) return "";
  if (x.group === "Tool calls") return summarizeInput(x.label, x.preview);
  let p = (x.preview || "").replace(/<\/?system-reminder>/g, "").replace(/\s+/g, " ").trim();
  const l = (x.label || "").replace(/…$/, "");
  if (p.startsWith(l)) p = p.slice(l.length).trim();
  return p.slice(0, 200);
}

async function tabContext(el, key, d, params) {
  const n = d.requests.length;
  if (!n) { el.innerHTML = '<p class="empty">No requests to inspect.</p>'; return; }
  let req = params.has("req") ? Math.max(0, Math.min(n - 1, +params.get("req"))) : n - 1;
  let filter = null, order = localGet("ctxorder", "sent"), find = "", limit = 200, c = null;
  el.innerHTML = `<div class="ctx-controls"><label for="rq">Request</label><input type="range" id="rq" min="0" max="${n - 1}" value="${req}"><span id="rql" class="num"></span><span id="rqm" class="sub"></span></div><div id="ctx"><p class="loading">Rebuilding request…</p></div>`;
  const ctxUrl = (extra) => `context?key=${encodeURIComponent(key)}&req=${req}${extra}`;
  const load = async () => {
    $("#rql").textContent = `#${req} of ${n - 1}`;
    c = await api(ctxUrl(find ? "&find=" + encodeURIComponent(find) : ""));
    render();
  };
  const render = () => {
    const meas = c.request.measured_prompt_tokens;
    const catOf = Object.fromEntries(c.groups.map((g) => [g.group, g.category]));
    const color = (group) => CAT_COLOR[catOf[group]] || "var(--neutral-2)";
    const parts = c.categories.map((x) => ({ name: x.category, tokens: x.tokens, color: CAT_COLOR[x.category] }));
    if (c.unattributed > 0) parts.push({ name: "Unattributed", tokens: c.unattributed, color: null });
    // The grid is the whole window: colored squares are used, the rest is free. Unknown window → grid = this request.
    const win = c.context_window, base = win || meas;
    const used = win ? Math.min(GRID_N, Math.max(1, Math.round(meas / win * GRID_N))) : GRID_N;
    const counts = shareCells(parts, used);
    parts.forEach((p, i) => {  // every category that is present gets at least one square
      const j = counts.indexOf(Math.max(...counts));
      if (p.tokens > 0 && !counts[i] && counts[j] > 1) { counts[j]--; counts[i] = 1; }
    });
    if (win) parts.push({ name: "Free space", tokens: Math.max(win - meas, 0), free: true });
    if (win) counts.push(GRID_N - used);
    const squares = parts.flatMap((p, i) => Array.from({ length: counts[i] }, () =>
      `<i ${p.color ? `style="background:${p.color}" data-cat="${esc(p.name)}"` : `class="${p.free ? "free" : "un"}"`} data-tip="${esc(p.name)}: ${int(p.tokens)} tokens (${pct(p.tokens / base, 1)} of the ${win ? "window" : "request"})"></i>`)).join("");
    const gTok = Object.fromEntries(c.groups.map((g) => [g.group, g]));
    const legend = parts.map((p) => {
      const cat = c.categories.find((x) => x.category === p.name);
      const subs = cat && (cat.groups.length > 1 || cat.groups[0] !== p.name)
        ? `<div class="lg-sub">${cat.groups.map((g) => `<button class="linkish" data-group="${esc(g)}" aria-pressed="${filter && filter.group === g}">${esc(g)} ${tok(gTok[g].tokens)}</button>`).join(" · ")}</div>` : "";
      return `<div class="lg-row"><button class="lg-main" ${p.color ? `data-cat="${esc(p.name)}"` : "disabled"} aria-pressed="${!!filter && filter.cat === p.name}"><span class="swatch ${p.color ? "" : p.free ? "free" : "un"}" ${p.color ? `style="background:${p.color}"` : ""}></span><span class="lg-n">${esc(p.name)}</span><span class="num">${tok(p.tokens)}</span><span class="num lg-p">${pct(p.tokens / base, 1)}</span></button>${subs}</div>`;
    }).join("");

    const matches = (x) => !filter || (filter.cat ? catOf[x.group] === filter.cat : x.group === filter.group);
    let items = c.items.filter(matches);  // server sends them in request order
    if (order === "size") items = items.slice().sort((a, b) => b.tokens - a.tokens);
    const total = items.length;
    items = items.slice(0, limit);
    const row = (x, tag = "") => `<details class="it" data-i="${x.i}"><summary><span class="dot" style="background:${color(x.group)}"></span>${tag}<span class="it-l${x.hidden ? " muted" : ""}">${esc(x.label || "(empty)")}</span><span class="it-h">${esc(itemHint(x))}</span><span class="it-g">${esc(x.group)}</span><span class="it-t num">${tok(x.tokens)}</span></summary><pre class="full">Loading…</pre></details>`;
    let body;
    if (order === "size") {
      body = items.map((x) => row(x, x.msg != null ? `<span class="it-m num">#${x.msg}</span>` : "")).join("");
    } else {
      const sum = (xs) => tok(xs.reduce((a, x) => a + x.tokens, 0));
      const sys = items.filter((x) => x.msg == null && catOf[x.group] !== "Tool definitions");
      const tools = items.filter((x) => x.msg == null && catOf[x.group] === "Tool definitions");
      const msgs = [];
      items.filter((x) => x.msg != null).forEach((x) => { const last = msgs[msgs.length - 1]; if (last && last.msg === x.msg) last.items.push(x); else msgs.push({ msg: x.msg, role: x.role, items: [x] }); });
      body = (sys.length ? `<section class="blk"><h3>System prompt<span class="num">${sum(sys)}</span></h3>${sys.map((x) => row(x)).join("")}</section>` : "")
        + (tools.length ? `<details class="blk" ${filter || find ? "open" : ""}><summary><h3>Tool definitions · ${tools.length}<span class="num">${sum(tools)}</span></h3></summary>${tools.map((x) => row(x)).join("")}</details>` : "")
        + msgs.map((m) => `<section class="blk"><h3>Message ${m.msg} <span class="role">${esc(m.role || "")}</span><span class="num">${sum(m.items)}</span></h3>${m.items.map((x) => row(x)).join("")}</section>`).join("");
    }
    const basisText = c.basis === "exact-request"
      ? `${B.m} Rebuilt from the exact API request Claude Code logged: system prompt, ${c.tools ? c.tools.length : 0} tool definitions and ${c.messages} messages.`
      : `${B.e} Rebuilt from the transcript. Tool definitions and the exact bytes sent are not in this log; long texts were clipped when parsed.`;
    $("#rqm").innerHTML = `${c.request.model ? mdl(c.request.model) : ""} ${dt(c.request.t)}`;
    $("#ctx").innerHTML = `
      <section class="card ctx-top">
        <div class="ctx-sum"><h2><span class="num">${int(meas)}</span> tokens in context ${B.m}</h2><span class="sub">${c.context_window ? pct(meas / c.context_window, 1) + " of the " + tok(c.context_window) + " window" : ""}</span></div>
        <div class="ctx-split">
          <div><div class="sq" role="img" aria-label="Context window by category, ${GRID_N} squares">${squares}</div><p class="sub">${win ? `Each square ≈ ${int(win / GRID_N)} tokens of the ${tok(win)} window · ${used} of ${GRID_N} in use` : `Window size unknown for this model; squares show this request only (≈ ${int(meas / GRID_N)} tokens each)`}</p></div>
          <div class="legend">${legend}</div>
        </div>
        <details class="ctx-more"><summary>How this is measured · request settings</summary>
          <p class="note">${basisText}</p>${c.notes.map((x) => `<p class="note small">${esc(x)}</p>`).join("")}
          ${c.params ? `<dl class="kv"><dt>Effort</dt><dd>${esc((c.params.output_config || {}).effort || "—")}</dd><dt>Thinking</dt><dd>${esc(JSON.stringify(c.params.thinking || null))}</dd><dt>Max output</dt><dd class="num">${int(c.params.max_tokens)}</dd><dt>Cache breakpoints</dt><dd>${(c.cache_breakpoints || []).map((b) => esc(b.path.join(".") + " (" + (b.value.ttl || "5m") + ")")).join(", ") || "—"}</dd><dt>Beta flags</dt><dd>${(c.betas || []).length}</dd></dl>` : ""}
        </details>
      </section>
      <section class="card ctx-list">
        <div class="ctx-tools"><div class="seg" role="group" aria-label="Order">${[["sent", "As sent"], ["size", "By size"]].map(([k, l]) => `<button data-order="${k}" aria-pressed="${order === k}">${l}</button>`).join("")}</div>
          <input type="search" id="cfind" placeholder="Search full content" value="${esc(find)}" aria-label="Search full content">
          ${filter ? `<button class="chip" id="clrf" aria-pressed="true">${esc(filter.cat || filter.group)} ✕</button>` : ""}<span class="sub">${total} items</span></div>
        <div id="citems">${body || '<p class="empty">Nothing matches.</p>'}</div>
        ${total > limit ? `<p><button class="btn" id="cmore">Show ${Math.min(300, total - limit)} more of ${total - limit}</button></p>` : ""}
      </section>`;
    bindTips($("#ctx"));
    const setFilter = (f) => { filter = f && filter && JSON.stringify(f) === JSON.stringify(filter) ? null : f; limit = 200; render(); };
    $("#ctx").querySelectorAll("[data-cat]").forEach((b) => b.addEventListener("click", () => setFilter({ cat: b.dataset.cat })));
    $("#ctx").querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => setFilter({ group: b.dataset.group })));
    $("#ctx").querySelectorAll("[data-order]").forEach((b) => b.addEventListener("click", () => { order = b.dataset.order; localSet("ctxorder", order); limit = 200; render(); }));
    const cf = $("#clrf"); if (cf) cf.addEventListener("click", () => setFilter(null));
    const m = $("#cmore"); if (m) m.addEventListener("click", () => { limit += 300; render(); });
    let ft;
    $("#cfind").addEventListener("input", (ev) => { clearTimeout(ft); ft = setTimeout(() => { find = ev.target.value.trim(); limit = 200; load().then(() => { const f = $("#cfind"); f.focus(); f.setSelectionRange(f.value.length, f.value.length); }).catch(showErr); }, 300); });
    // full text loads when a row is opened (toggle doesn't bubble, so listen in the capture phase)
    $("#citems").addEventListener("toggle", async (ev) => {
      const it = ev.target;
      if (!it.classList || !it.classList.contains("it") || !it.open || it.dataset.loaded) return;
      it.dataset.loaded = "1";
      const pre = it.querySelector("pre.full");
      try {
        const t = (await api(ctxUrl("&item=" + it.dataset.i))).item.text ?? "";
        let pretty = t;
        if (/^\s*[[{]/.test(t)) { try { pretty = JSON.stringify(JSON.parse(t), null, 2); } catch { /* not JSON */ } }
        pre.textContent = pretty || "(empty)";
      } catch (e) { pre.textContent = "Could not load: " + e.message; delete it.dataset.loaded; }
    }, true);
  };
  const rq = $("#rq");
  let t;
  rq.addEventListener("input", () => { req = +rq.value; $("#rql").textContent = `#${req} of ${n - 1}`; clearTimeout(t); t = setTimeout(() => { history.replaceState(null, "", sessHref(key, "tab=context&req=" + req)); load().catch(showErr); }, 200); });
  await load();
}

function tabCost(el, d) {
  const s = d.summary, byModel = {};
  d.requests.forEach((r) => {
    const m = byModel[r.model || "unknown"] || (byModel[r.model || "unknown"] = { n: 0, input: 0, read: 0, write: 0, out: 0, cost: 0, unpriced: false });
    m.n++; m.input += r.usage.input; m.read += r.usage.cache_read; m.write += r.usage.cache_write_5m + r.usage.cache_write_1h; m.out += r.usage.output;
    if (r.cost == null) m.unpriced = true; else m.cost += r.cost;
  });
  const mu = (d.measured || {}).model_usage;
  const rb = s.signals.cache_rebuilds;
  el.innerHTML = `
    <div class="grid"><section class="card c12"><div class="card-h"><h2>Cost per request</h2><span class="sub">${B.e} tokens × price</span></div><div id="cpr"></div></section></div>
    <div class="grid">
      <section class="card c7"><div class="card-h"><h2>By model</h2><span class="sub">tokens ${B.m} · cost ${B.e}</span></div>
        <table><thead><tr><th>Model</th><th class="n">Requests</th><th class="n hide-sm">Uncached</th><th class="n">Cache read</th><th class="n">Cache write</th><th class="n hide-sm">Output</th><th class="n">Cost</th></tr></thead><tbody>
        ${Object.entries(byModel).map(([m, v]) => `<tr><td>${esc(m)}</td><td class="n">${v.n}</td><td class="n hide-sm">${tok(v.input)}</td><td class="n">${tok(v.read)}</td><td class="n">${tok(v.write)}</td><td class="n hide-sm">${tok(v.out)}</td><td class="n">${v.unpriced ? `${DASH} ${B.u}` : usd(v.cost)}</td></tr>`).join("")}
        </tbody></table>
        ${mu ? `<h3 style="margin:20px 0 8px">Claude Code's own meter ${B.m}</h3><p class="small muted" style="margin:0 0 8px">Includes calls that are not written to the transcript (titles, classifiers, background work), so it can exceed the logged estimate.</p>
        <table><thead><tr><th>Model</th><th class="n">Input</th><th class="n">Cache read</th><th class="n">Cache write</th><th class="n">Output</th><th class="n">Cost</th></tr></thead><tbody>
        ${Object.entries(mu).map(([m, v]) => `<tr><td>${esc(m)}</td><td class="n">${tok(v.inputTokens)}</td><td class="n">${tok(v.cacheReadInputTokens)}</td><td class="n">${tok(v.cacheCreationInputTokens)}</td><td class="n">${tok(v.outputTokens)}</td><td class="n">${usd(v.costUSD)}</td></tr>`).join("")}
        </tbody></table>` : ""}
      </section>
      <section class="card c5"><div class="card-h"><h2>Cache rebuilds</h2><span class="sub">${rb.length}</span></div>
        ${rb.length ? `<table><thead><tr><th>Request</th><th>Cause</th><th class="n">Rewritten</th><th class="n">Avoidable ${B.e}</th></tr></thead><tbody>
        ${rb.map((r) => `<tr><td><a href="${sessHref(s.key, "tab=context&req=" + r.req)}">#${r.req}</a><div class="t2">${dt(r.t)}</div></td><td>${esc(r.cause)}${r.gap_s != null ? `<div class="t2">${dur(r.gap_s * 1000)} since previous</div>` : ""}</td><td class="n">${tok(r.write_tokens)}</td><td class="n">${usd(r.waste_usd)}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">The prompt cache was never rebuilt after the first request.</p>'}
        <h3 style="margin:20px 0 8px">Timing ${B.m}</h3>
        <dl class="kv"><dt>Wall clock</dt><dd>${dur((s.duration_s || 0) * 1000)}</dd><dt>Active (turn time)</dt><dd>${dur(s.active_ms)}</dd><dt>Median turn</dt><dd>${dur(s.median_turn_ms)}</dd><dt>Median gap to response ${B.e}</dt><dd>${s.median_latency_s != null ? s.median_latency_s + " s" : DASH}</dd><dt>Turns recorded</dt><dd>${d.turns.length}</dd></dl>
      </section>
    </div>`;
  if (d.requests.length) columns($("#cpr"), d.requests.map((r, i) => ({ label: "#" + i, parts: { c: r.cost || 0 }, tip: `#${i} · ${r.cost == null ? "unpriced" : usd(r.cost, 4)}` })), [{ key: "c", color: "var(--accent)" }], { height: 150, fmt: (v) => "$" + (v < 1 ? v.toFixed(2) : v) });
}
function tabTools(el, d) {
  const t = Object.entries(d.summary.tools).sort((a, b) => b[1].calls - a[1].calls);
  const lo = d.summary.signals.large_outputs, rep = d.summary.signals.repeated_calls;
  el.innerHTML = `<div class="grid"><section class="card c7"><div class="card-h"><h2>Tool usage</h2><span class="sub">${B.m}</span></div>
    ${t.length ? `<table><thead><tr><th>Tool</th><th class="n">Calls</th><th class="n">Errors</th><th class="n">Output ${B.e}</th><th class="n">Total time</th></tr></thead><tbody>
    ${t.map(([n, v]) => `<tr><td>${esc(n)}</td><td class="n">${v.calls}</td><td class="n">${v.errors || 0}</td><td class="n">${tok(v.output_chars / 4)} tok</td><td class="n">${v.timed ? dur(v.ms) : DASH}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">No tool calls.</p>'}</section>
    <section class="card c5"><div class="card-h"><h2>Large results</h2><span class="sub">over ~10k tokens</span></div>
    ${lo.length ? `<table class="fit"><tbody>${lo.map((x) => `<tr><td>${esc(x.tool)}<div class="t2">${esc(x.input)}</div></td><td class="n">${tok(x.est_tokens)}<div class="t2">≈${usd(x.carry_usd)} carried</div></td></tr>`).join("")}</tbody></table>` : '<p class="muted">No tool result exceeded ~10k tokens.</p>'}
    ${rep.length ? `<h3 style="margin:18px 0 8px">Repeated with no change in between</h3><table class="fit"><tbody>${rep.map((x) => `<tr><td>${esc(x.tool)}<div class="t2">${esc(x.input)}</div></td><td class="n">×${x.count}</td></tr>`).join("")}</tbody></table>` : ""}
    </section></div>`;
}
function tabSubagents(el, d) {
  el.innerHTML = `<section class="card"><table><thead><tr><th>Subagent</th><th class="hide-sm">Model</th><th class="n">Requests</th><th class="n">Peak context</th><th class="n">Cost ${B.e}</th></tr></thead><tbody>
    ${d.children.map((c) => `<tr class="click" data-href="${sessHref(c.key)}"><td><a class="t1" href="${sessHref(c.key)}">${esc((c.subagent && c.subagent.description) || c.title)}</a><div class="t2">${esc((c.subagent && c.subagent.type) || "subagent")}</div></td><td class="hide-sm">${modelChips(c.models)}</td><td class="n">${c.n_requests}</td><td class="n">${tok(c.peak_context)}</td><td class="n">${usd(c.cost.estimated)}</td></tr>`).join("")}
    </tbody></table></section>`;
  wireRows();
}

/* ---------- recommendations ---------- */
async function viewRecs(focus) {
  setNav("recommendations");
  const d = await api("recommendations?" + daysQ());
  const recs = d.recommendations;
  const total = recs.reduce((a, r) => a + (r.savings_usd || 0), 0);
  const priced = recs.filter((r) => r.savings_usd).sort((a, b) => b.savings_usd - a.savings_usd);
  const other = recs.filter((r) => !r.savings_usd);
  main.innerHTML = `<div class="title-row"><div><h1>Recommendations</h1><p class="finding">${recs.length} findings from deterministic rules over your logs${total ? `, about <strong>${usd(total)}</strong> of estimated avoidable spend` : ""}. Each one lists the sessions it was found in.</p></div>${periodSeg()}</div>
    ${priced.length ? `<div class="grid"><section class="card c8"><div class="card-h"><h2>Avoidable spend by finding</h2><span class="sub">${B.e} click a bar to jump to it</span></div>
      ${barList(priced.map((r) => ({ label: r.title, value: r.savings_usd, href: "#/recommendations/" + r.id })))}</section>
      <section class="card c4"><div class="card-h"><h2>Without a dollar estimate</h2></div>
      ${other.length ? other.map((r) => `<div class="rec"><a class="rec-title" href="#/recommendations/${r.id}">${esc(r.title)}</a><div class="small" style="margin-top:4px"><span class="tag sev-${r.severity}">${r.severity}</span></div></div>`).join("") : '<p class="muted">None.</p>'}</section></div>` : ""}
    ${recs.map((r) => `<article class="rec-full" id="rec-${r.id}">
      <div class="rec-h"><h2>${esc(r.title)}</h2><span class="rec-save">${r.savings_usd ? usd(r.savings_usd) + " " + B.e : ""}</span></div>
      <div class="small" style="margin-top:6px"><span class="tag sev-${r.severity}">${r.severity}</span> <span class="muted">${esc(r.savings_basis)}</span></div>
      <p>${esc(r.why)}</p><p><strong>Do this:</strong> ${esc(r.action)}</p>
      <div class="lbl">Evidence</div>
      <table class="fit"><tbody>${r.evidence.map((e) => `<tr class="${e.usd ? "ev-bar" : ""}" style="--w:${e.usd && r.evidence[0] ? Math.round(100 * e.usd / Math.max(...r.evidence.map((x) => x.usd || 0))) : 0}%">${e.key ? `<td><a href="${sessHref(e.key, e.req != null ? "tab=context&req=" + e.req : "tab=timeline")}">${esc(e.title)}</a><div class="t2">${esc(e.detail)}</div></td>` : `<td>${esc(e.title)}<div class="t2">${esc(e.detail)}</div></td>`}<td class="n">${e.usd != null ? usd(e.usd) : ""}</td></tr>`).join("")}</tbody></table>
    </article>`).join("") || '<p class="empty">No findings in this period.</p>'}`;
  wirePeriod(() => viewRecs(focus));
  if (focus) { const a = $("#rec-" + CSS.escape(focus)); if (a) a.scrollIntoView(); }
}

/* ---------- data sources ---------- */
async function viewSources() {
  setNav("sources");
  const d = await api("sources");
  renderSideAgents(d.agents);
  const bad = d.files.reduce((a, f) => a + (f.stats.bad_lines || 0), 0);
  main.innerHTML = `<div class="title-row"><div><h1>Data sources</h1><p class="finding">${d.files.length} session logs read from this machine, ${bad} malformed lines skipped, ${d.errors.length} files failed to parse.</p></div></div>
    <div class="grid">
      <section class="card c7"><div class="card-h"><h2>Agents</h2></div><table><thead><tr><th>Agent</th><th>Location</th><th class="n">Logs</th></tr></thead><tbody>
        ${d.agents.map((a) => `<tr><td><span class="agl">${agentIcon(a.agent)}${esc(agentName(a.agent))}<span class="dot ${a.present ? "on" : ""}"></span></span></td><td class="mono">${esc(a.root || a.note || "")}</td><td class="n">${a.present ? a.files : DASH}</td></tr>`).join("")}</tbody></table>
        ${d.errors.length ? `<h3 style="margin:18px 0 8px">Parse errors</h3>${d.errors.map((e) => `<p class="error-box small">${esc(e.path)}: ${esc(e.error)}</p>`).join("")}` : ""}
      </section>
      <section class="card c5"><div class="card-h"><h2>How to read the numbers</h2></div>
        <dl class="kv"><dt>${B.m}</dt><dd>Read directly from the agent's logs: token counts per API response, Claude Code's cost meter, timestamps, Codex's thread totals.</dd>
        <dt>${B.e}</dt><dd>Computed: tokens × list price (${esc(d.pricing_source)}), context shares from character counts, savings from current prices.</dd>
        <dt>${B.u}</dt><dd>Not in the logs, or no verified price (OpenAI models unless you add ~/.config/agents-report/prices.json). Shown as a dash, never as zero.</dd></dl></section>
    </div>
    <section class="card"><div class="card-h"><h2>Session logs</h2><span class="sub">${d.files.length}</span></div><table><thead><tr><th>Session</th><th class="n hide-sm">Records</th><th class="n">Malformed</th></tr></thead><tbody>
      ${d.files.map((f) => `<tr><td><a class="agl" href="${sessHref(f.key)}">${agentIcon(f.agent, 16)}${esc(agentName(f.agent))} · ${esc(f.key.split(":")[1].slice(0, 8))}</a><div class="t2 mono">${esc(f.path)}</div></td><td class="n hide-sm">${int(f.stats.records)}</td><td class="n">${f.stats.bad_lines || 0}${f.stats.error ? ` <span class="tag bad">${esc(f.stats.error)}</span>` : ""}</td></tr>`).join("")}</tbody></table></section>`;
}

/* ---------- router ---------- */
function showErr(e) { main.innerHTML = `<div class="error-box">Could not load this view: ${esc(e.message || e)}</div>`; }
async function route() {
  const h = location.hash.slice(1) || "/";
  const [path, qs] = h.split("?");
  const params = new URLSearchParams(qs || "");
  tip.hidden = true;
  try {
    if (path === "/" || path === "") await viewOverview();
    else if (path === "/sessions") await viewSessions(params);
    else if (path.startsWith("/session/")) await viewSession(decodeURIComponent(path.slice(9)), params);
    else if (path.startsWith("/recommendations")) await viewRecs(path.split("/")[2]);
    else if (path === "/sources") await viewSources();
    else main.innerHTML = '<p class="empty">Page not found. <a href="#/">Go to the overview</a>.</p>';
  } catch (e) { showErr(e); }
  const keepScroll = (path.startsWith("/session/") && params.has("tab")) || /^\/recommendations\/./.test(path);
  if (!keepScroll) window.scrollTo(0, 0);
}
addEventListener("hashchange", route);
route();
api("recommendations").then((d) => { $("#rec-count").textContent = d.recommendations.length || ""; }).catch(() => {});
let resizeT;
addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => { if (main.querySelector(".chart")) route(); }, 250); });
