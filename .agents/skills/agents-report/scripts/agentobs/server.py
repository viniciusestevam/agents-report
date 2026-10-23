"""Local JSON API + static UI. Binds to 127.0.0.1 only and rejects foreign Host headers (DNS rebinding)."""
import hashlib
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import analyze, context, pricing, util
from .store import Store, tree_cost

# The dashboard files: inside the package when installed with pip/uv/pipx, next to scripts/ in the skill folder.
UI = next((p for p in (Path(__file__).resolve().parent / "ui", Path(__file__).resolve().parent.parent.parent / "assets" / "ui")
           if (p / "index.html").is_file()), Path(__file__).resolve().parent.parent.parent / "assets" / "ui")
CODE = Path(__file__).resolve().parent
DEFAULT_PORT = 48765  # dedicated, rarely used; falls back to any free port when taken
STATE = Path(os.environ.get("AGENTOBS_STATE", Path.home() / ".cache" / "agents-report" / "server.json"))


def fingerprint():
    """Changes whenever the code or UI changes, so a stale running server can be detected."""
    h = hashlib.sha1()
    for f in sorted(list(CODE.rglob("*.py")) + list(UI.iterdir())):
        h.update(f"{f.name}:{f.stat().st_mtime_ns}".encode())
    return h.hexdigest()[:12]


def _slim_session(full, store):
    """Detail payload for the UI: drop raw api logs, attach children summaries."""
    sums = {s["key"]: s for s in store.summaries()}
    summ = full["summary"]
    return {
        "summary": summ,
        "tree_cost": tree_cost(list(sums.values()), summ["key"]),
        "parent": sums.get(summ["parent_key"]) and {"key": summ["parent_key"], "title": sums[summ["parent_key"]]["title"]},
        "children": [sums[c] for c in summ["children"] if c in sums],
        "events": full["events"],
        "requests": [{k: r.get(k) for k in ("t", "t_end", "model", "usage", "cost", "latency_s", "stop_reason", "effort", "speed", "after_compaction_reset", "aggregate")}
                     for r in full["requests"]],
        "has_exact_context": bool(full.get("api_log", {}).get("requests")),
        "measured": full.get("measured"),
        "turns": full["turns"],
    }


class Presence:
    """Which dashboard tabs are open, from the page's check-ins. The background server stops when none are left."""
    STALE = 150  # s without a check-in = tab gone (browsers may slow background-tab timers to once a minute)
    GRACE = 20   # s with no open tab before stopping; covers a page reload
    FIRST = 600  # s to wait for the first tab (URL printed for later, or --no-open)

    def __init__(self, now):
        self.tabs, self.empty_since, self.seen = {}, now, False
        self.lock = threading.Lock()

    def update(self, tab, is_open, now):
        with self.lock:
            if is_open:
                self.tabs[tab] = now
                self.seen, self.empty_since = True, None
            elif self.tabs.pop(tab, None) is not None and not self.tabs:
                self.empty_since = now

    def should_stop(self, now):
        with self.lock:
            for tab, last in list(self.tabs.items()):
                if now - last > self.STALE:
                    del self.tabs[tab]
                    if not self.tabs:
                        self.empty_since = last + self.STALE
            if self.tabs:
                return False
            return now - self.empty_since > (self.GRACE if self.seen else self.FIRST)


class Handler(BaseHTTPRequestHandler):
    store: Store = None
    fingerprint = None
    presence: Presence = None  # set only when the server should stop itself

    def log_message(self, fmt, *args):  # quiet by default
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        """Only the page's goodbye beacon (navigator.sendBeacon can only POST)."""
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost") or (origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost")):
            return self._send(403, {"error": "forbidden"})
        self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096))
        url = urlparse(self.path)
        if url.path != "/api/presence":
            return self._send(404, {"error": "unknown route"})
        return self._presence({k: v[0] for k, v in parse_qs(url.query).items()})

    def _presence(self, q):
        tab = (q.get("tab") or "")[:64]
        if tab and self.presence:
            self.presence.update(tab, q.get("state") != "closed", time.time())
        return self._send(200, {"ok": True, "auto_stop": bool(self.presence)})

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._send(403, {"error": "forbidden host"})
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path
        try:
            if path.startswith("/api/"):
                return self._api(path[5:], q)
            return self._static(path)
        except Exception as e:  # surface, don't crash the server
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _sums(self, q):
        sums = self.store.summaries()
        if q.get("days"):
            cutoff = util.now() - float(q["days"]) * 86400
            keep = {s["key"] for s in sums if not s["parent_key"] and (s["started"] or 0) >= cutoff}
            sums = [s for s in sums if s["key"] in keep or s["parent_key"] in keep]
        return sums

    def _api(self, route, q):
        st = self.store
        if route == "presence":
            return self._presence(q)
        if route == "health":
            return self._send(200, {"ok": True, "app": "agents-report", "fingerprint": self.fingerprint, "pid": os.getpid(), "time": time.time()})
        if route == "overview":
            sums = self._sums(q)
            return self._send(200, {"overview": analyze.overview(sums), "recommendations": analyze.recommendations(sums)[:4],
                                    "activity": analyze.activity(st.summaries()),  # whole history, like GitHub
                                    "agents": st.detected_agents(), "errors": st.errors})
        if route == "sessions":
            sums = [s for s in self._sums(q) if not s["parent_key"] or q.get("subagents") == "1"]
            if q.get("agent"):
                sums = [s for s in sums if s["agent"] == q["agent"]]
            if q.get("project"):
                sums = [s for s in sums if s["project"] == q["project"]]
            if q.get("q"):
                needle = q["q"].lower()
                sums = [s for s in sums if needle in " ".join(str(s.get(k) or "") for k in ("title", "first_prompt", "cwd", "id", "branch")).lower()]
            sums.sort(key=lambda s: -(s["started"] or 0))
            every = st.summaries()
            return self._send(200, {"sessions": [{**{k: v for k, v in s.items() if k not in ("signals", "daily")},
                                                  "tree_cost": tree_cost(every, s["key"]) if s["children"] else None} for s in sums]})
        if route == "recommendations":
            return self._send(200, {"recommendations": analyze.recommendations(self._sums(q))})
        if route == "sources":
            return self._send(200, {"agents": st.detected_agents(), "errors": st.errors, "pricing_source": pricing.SOURCE,
                                    "files": [{"agent": s["agent"], "key": s["key"], "path": s["path"], "stats": s["stats"]}
                                              for s in st.summaries() if not s["parent_key"]]})
        if route in ("session", "context"):
            full = st.session(q.get("key", ""), with_api_log=(route == "context"))
            if not full:
                return self._send(404, {"error": "session not found"})
            if route == "context":
                return self._send(200, context.inspect(full, q.get("req"), q.get("item"), q.get("find")))
            return self._send(200, _slim_session(full, st))
        return self._send(404, {"error": "unknown route"})

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (UI / rel).resolve()
        if UI not in f.parents and f != UI or not f.is_file():
            f = UI / "index.html"  # SPA fallback
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        return self._send(200, f.read_bytes(), ctype)


def bind(port=None):
    """Bind the requested port; if it is taken, the default port, then any free port."""
    for p in [x for x in (port, DEFAULT_PORT) if x] + [0]:
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
    raise OSError("no free port")


def _watch(srv, presence, log=print):
    """Stop the server once no dashboard tab is open."""
    while True:
        time.sleep(2)
        if presence.should_stop(time.time()):
            log("Stopping: no dashboard tab open." if presence.seen else "Stopping: no dashboard tab opened in time.", flush=True)
            srv.shutdown()
            return


def serve(port=None, store=None, open_browser=False, view="", auto_stop=False):
    Handler.store = store or Store()
    Handler.fingerprint = fingerprint()
    Handler.store.summaries()  # warm the cache before accepting requests
    srv = bind(port)
    if auto_stop:
        Handler.presence = Presence(time.time())
        threading.Thread(target=_watch, args=(srv, Handler.presence), daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"url": url, "port": srv.server_address[1], "pid": os.getpid(),
                                 "fingerprint": Handler.fingerprint, "started": time.time()}))
    def _term(*_):
        raise KeyboardInterrupt
    import signal
    signal.signal(signal.SIGTERM, _term)
    print(f"Agents Report on {url}  (Ctrl+C to stop{'; stops itself when the last dashboard tab closes' if auto_stop else ''})", flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url + view)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if json.loads(STATE.read_text()).get("pid") == os.getpid():
                STATE.unlink()
        except (OSError, ValueError):
            pass
    return srv
