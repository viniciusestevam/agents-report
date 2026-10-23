// Records the demo video and screenshots with headless Chrome over the DevTools protocol (no dependencies).
//   node tools/record.mjs video <outDir> <dashboardUrl> <replay.html>
//   node tools/record.mjs shots <outDir> <dashboardUrl>     (README screenshots: .github/assets/screenshots)
// The dashboard must be serving synthetic demo data (tools/make_demo_data.py).
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const [mode, OUT, DASH, REPLAY] = process.argv.slice(2);
const W = 1440, H = 900, PORT = 9333;
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const profile = join(tmpdir(), "agents-report-rec-" + process.pid);
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, `--window-size=${W},${H}`,
  "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--force-color-profile=srgb", "about:blank"], { stdio: "ignore" });
let ws, id = 0;
const pending = new Map(), handlers = [];
async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); break; }
    } catch { /* not up yet */ }
    await sleep(200);
  }
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { const [res, rej] = pending.get(d.id); pending.delete(d.id); d.error ? rej(new Error(d.error.message)) : res(d.result); }
    else if (d.method) handlers.forEach((h) => h(d));
  };
}
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, [res, rej]); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result.value;
async function go(url, settle = 1200) { await send("Page.navigate", { url }); await sleep(settle); }
async function waitFor(expr, ms = 60000) { const t = Date.now(); while (Date.now() - t < ms) { if (await evaluate(expr)) return; await sleep(150); } throw new Error("timeout: " + expr); }
async function center(sel, i = 0) {
  return evaluate(`(() => { const e = document.querySelectorAll(${JSON.stringify(sel)})[${i}]; if (!e) return null; e.scrollIntoViewIfNeeded && e.scrollIntoViewIfNeeded(); const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
}
let mx = W / 2, my = H / 2;
async function moveTo(x, y, ms = 600) {
  const n = Math.max(2, Math.round(ms / 16)), x0 = mx, y0 = my;
  for (let k = 1; k <= n; k++) {
    const p = k / n, e = p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2;
    mx = x0 + (x - x0) * e; my = y0 + (y - y0) * e;
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: mx, y: my });
    await sleep(16);
  }
}
async function click(x, y) {
  await moveTo(x, y);
  await sleep(120);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
}
async function clickSel(sel, i = 0) { const c = await center(sel, i); if (!c) throw new Error("missing " + sel); await sleep(250); await click(c.x, c.y); }
async function hoverSel(sel, i = 0, ms = 700) { const c = await center(sel, i); if (c) await moveTo(c.x, c.y, ms); }
async function scrollTo(y, ms = 900) {  // eased page scroll
  await evaluate(`new Promise((r) => { const y0 = scrollY, y1 = ${y}, t0 = performance.now(); const f = (t) => { const p = Math.min(1, (t - t0) / ${ms}); const e = p < .5 ? 2*p*p : 1 - (-2*p + 2) ** 2 / 2; scrollTo(0, y0 + (y1 - y0) * e); p < 1 ? requestAnimationFrame(f) : r(); }; requestAnimationFrame(f); })`);
}
const topOf = (sel, off = 80) => evaluate(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); return e ? e.getBoundingClientRect().top + scrollY - ${off} : 0; })()`);

// A visible cursor for the video (headless Chrome draws none).
const CURSOR = `addEventListener("DOMContentLoaded", () => {
  const c = document.createElement("div");
  c.innerHTML = '<svg width="22" height="26" viewBox="0 0 22 26"><path d="M2 2l7 20 3-8 8-3z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  c.style.cssText = "position:fixed;left:0;top:0;z-index:99999;pointer-events:none;transform:translate(-100px,-100px);filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))";
  document.body.append(c);
  addEventListener("mousemove", (e) => { c.style.transform = "translate(" + (e.clientX - 2) + "px," + (e.clientY - 2) + "px)"; }, true);
  addEventListener("mousedown", () => { c.animate([{ scale: 1 }, { scale: .8 }, { scale: 1 }], { duration: 220 }); }, true);
});`;

async function main() {
  await connect();
  await send("Page.enable");
  await send("Runtime.enable");
  const dsf = mode === "shots" ? 2 : 1;
  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: dsf, mobile: false });
  if (mode === "shots") return shots();
  await send("Page.addScriptToEvaluateOnNewDocument", { source: CURSOR });
  // frames arrive when the page repaints; keep their timestamps for exact timing in ffmpeg
  const frames = [];
  const dir = join(OUT, "frames");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  handlers.push((d) => {
    if (d.method !== "Page.screencastFrame") return;
    const f = join(dir, String(frames.length).padStart(6, "0") + ".jpg");
    writeFileSync(f, Buffer.from(d.params.data, "base64"));
    frames.push({ f, t: d.params.metadata.timestamp });
    send("Page.screencastFrameAck", { sessionId: d.params.sessionId });
  });
  await go("file://" + REPLAY, 300);
  await send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  await waitFor("window.done === true", 120000);

  // Overview: activity heatmap and spend
  await go(DASH + "#/", 2200);
  await waitFor("!!document.querySelector('.act-grid')");
  await moveTo(700, 300, 500);
  await sleep(600);
  await scrollTo(await topOf("#activity", 20), 1100);
  await sleep(400);
  const cells = await evaluate(`[...document.querySelectorAll('.act-grid i.l4, .act-grid i.l3')].length`);
  for (let k = 1; k <= 3; k++) { await hoverSel(".act-grid i.l4, .act-grid i.l3", Math.floor(cells * k / 4), 650); await sleep(900); }
  await scrollTo(await topOf("#daily", 90), 1000);
  const bars = await evaluate(`document.querySelectorAll('.spend .hit').length`);
  for (const k of [0.45, 0.7, 0.95]) { await hoverSel(".spend .hit", Math.floor(bars * k), 600); await sleep(900); }

  // Sessions: timeline
  await scrollTo(0, 600);
  await clickSel('nav a[data-nav="sessions"]');
  await waitFor("!!document.querySelector('.tl-plot svg rect.bar')");
  await sleep(1200);
  await hoverSel(".tl-plot rect.bar", 3, 700);
  await sleep(1100);
  await clickSel('[data-z="in"]'); await sleep(700);
  await clickSel('[data-z="in"]'); await sleep(900);
  await hoverSel(".tl-plot rect.bar", 0, 600);
  await sleep(1000);

  // One session: context per request, then the context viewer
  const key = await evaluate(`(async () => { const s = (await (await fetch('/api/sessions')).json()).sessions.filter((x) => x.agent === 'claude-code'); s.sort((a, b) => (b.peak_context || 0) - (a.peak_context || 0)); return s[0].key; })()`);
  await scrollTo(await topOf(`tr[data-href*="${encodeURIComponent(key)}"]`, 300), 800);
  await clickSel(`tr[data-href*="${encodeURIComponent(key)}"] a.t1`);
  await waitFor("!!document.querySelector('#strip svg')");
  await sleep(1500);
  const cols = await evaluate(`document.querySelectorAll('#strip [data-i]').length`);
  for (const k of [0.3, 0.75]) { await hoverSel("#strip [data-i]", Math.floor(cols * k), 600); await sleep(900); }
  await clickSel('.tabs a[href*="tab=context"]');
  await waitFor("!!document.querySelector('.sq i')");
  await sleep(600);
  await scrollTo(await topOf(".ctx-top", 20), 1000);
  await hoverSel(".sq i", 8, 600); await sleep(900);
  await hoverSel(".lg-main", 1, 600); await sleep(700);
  await clickSel(".lg-main", 1);  // filter to the largest category after tool definitions
  await sleep(800);
  await scrollTo(await topOf(".ctx-list", 20), 1000);
  await clickSel(".it > summary", 0);
  await sleep(2200);
  await clickSel(".it > summary", 0);
  await sleep(500);

  // Recommendations
  await scrollTo(0, 500);
  await clickSel('nav a[data-nav="recommendations"]');
  await sleep(2000);
  await scrollTo(420, 1600);
  await sleep(1800);
  await send("Page.stopScreencast");
  await sleep(300);

  // ffconcat: each frame lasts until the next one
  let list = "ffconcat version 1.0\n";
  frames.forEach((fr, i) => {
    const d = i + 1 < frames.length ? frames[i + 1].t - fr.t : 1.5;
    list += `file '${fr.f}'\nduration ${Math.max(d, 0.001).toFixed(4)}\n`;
  });
  list += `file '${frames[frames.length - 1].f}'\n`;
  writeFileSync(join(OUT, "frames.ffconcat"), list);
  console.log(`${frames.length} frames over ${(frames[frames.length - 1].t - frames[0].t).toFixed(1)} s`);
}

async function shot(name) {
  await sleep(500);
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, name), Buffer.from(data, "base64"));
  console.log("wrote", name);
}
async function shots() {
  // README screenshots, light theme unless named -dark. The look is set through the page's own saved preferences.
  const prefs = (theme) => evaluate(`localStorage.setItem("obs:theme", "${theme}"); localStorage.setItem("obs:sess-group", "project"); localStorage.setItem("obs:tl-sort", "cost"); localStorage.setItem("obs:trace-mode", "active"); location.reload()`);
  await go(DASH + "#/", 1500);
  await prefs("light");
  await sleep(2500);
  await waitFor("!!document.querySelector('.act-grid')");
  await shot("overview.png");

  await go(DASH + "#/sessions", 2200);
  await waitFor("!!document.querySelector('.tl-plot .bar')");
  await evaluate(`document.querySelector('tr.grp').click()`);  // open the costliest project
  await evaluate(`scrollTo(0, ${await topOf("#stl", 24)})`);
  await shot("sessions.png");

  // the trace of the costliest session that used subagents (and has its prompts open: ≤ 8), one subagent opened, the slowest span selected
  // pick the costliest session (prompts open: ≤ 8) whose first prompt launches a subagent
  const key = await evaluate(`(async () => {
    const s = (await (await fetch('/api/sessions')).json()).sessions.filter((x) => x.n_subagents && x.n_user <= 8);
    s.sort((a, b) => (b.tree_cost || 0) - (a.tree_cost || 0));
    for (const x of s) {
      const ev = (await (await fetch('/api/session?key=' + encodeURIComponent(x.key))).json()).events;
      const users = ev.filter((e) => e.kind === 'user'), sub = ev.find((e) => e.child_key);
      if (sub && (users.length < 2 || sub.t < users[1].t)) return x.key;
    }
    return s[0].key;
  })()`);
  const trace = async (name) => {
    await go(DASH + "#/session/" + encodeURIComponent(key), 2200);
    await waitFor("!!document.querySelector('.tr-row.k-agent')");
    await evaluate(`document.querySelector('.tr-row.k-agent [data-car]').click()`);
    await waitFor("document.querySelectorAll('.tr-row').length > 12 && ![...document.querySelectorAll('.tr-car')].some((c) => c.textContent.includes('…'))");
    // keep the first prompt open, fold the others, then select the slowest span (or the subagent's first model call)
    for (let i = 0; i < 12; i++) {
      const more = await evaluate(`(() => { const t = [...document.querySelectorAll('.tr-row.k-turn[aria-expanded="true"]')].slice(1)[0]; if (!t) return false; t.querySelector('[data-car]').click(); return true; })()`);
      if (!more) break;
      await sleep(150);
    }
    await sleep(400);
    await evaluate(`(() => { const r = document.querySelector('.bd.slow')?.closest('.tr-row') || [...document.querySelectorAll('.tr-row.k-llm')].find((x) => +x.getAttribute('aria-level') > 3) || document.querySelectorAll('.tr-row.k-llm')[1]; r.click(); })()`);
    await evaluate(`scrollTo(0, ${await topOf(".tr-card", 24)})`);
    await shot(name);
  };
  await trace("trace.png");

  // the context window of the Claude Code session with the largest context
  const big = await evaluate(`(async () => { const s = (await (await fetch('/api/sessions')).json()).sessions.filter((x) => x.agent === 'claude-code'); s.sort((a, b) => (b.peak_context || 0) - (a.peak_context || 0)); return s[0].key; })()`);
  await go(DASH + "#/session/" + encodeURIComponent(big) + "?tab=context", 2500);
  await waitFor("!!document.querySelector('.sq i')");
  await evaluate(`scrollTo(0, ${await topOf(".ctx-controls", 24)})`);
  await shot("context.png");

  await go(DASH + "#/recommendations", 2200);
  await shot("recommendations.png");

  await prefs("dark");
  await sleep(2500);
  await trace("trace-dark.png");
  await evaluate(`localStorage.clear()`);
}

async function done(code) {
  chrome.kill();
  await sleep(800);  // let Chrome let go of its profile
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* a temp dir; the OS cleans it */ }
  process.exit(code);
}
main().then(() => done(0), (e) => { console.error(e); done(1); });
