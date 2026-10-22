"""Session discovery, in-memory cache, and per-session summaries + deterministic signals."""
import statistics
import threading
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from . import pricing
from .adapters import claude_code, codex, hermes, opencode, pi
from .util import add_usage, empty_usage, est_tokens, prompt_tokens

ADAPTERS = {m.AGENT: m for m in (claude_code, codex, hermes, pi, opencode)}

LARGE_OUTPUT_CHARS = 40_000  # ~10k tokens
REBUILD_MIN_TOKENS = 10_000
READ_ONLY = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "ToolSearch", "LS"}
MUTATING = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "exec", "apply_patch", "shell", "exec_command"}


def _carry(requests, t, tokens):
    """Estimated $ to carry `tokens` inserted at time t: one cache write + a cache read on each later request
    (until the next compaction resets context)."""
    usd, wrote = 0.0, False
    for r in requests:
        if r["t"] is None or r["t"] <= t:
            continue
        if r.get("after_compaction_reset"):
            break
        rt = pricing.rates(r["model"])
        if not rt:
            return None
        if not wrote:
            usd += tokens * rt["cache_write_1h" if r["usage"]["cache_write_1h"] else "cache_write_5m"] / 1e6
            wrote = True
        else:
            usd += tokens * rt["cache_read"] / 1e6
    return usd


def summarize(s):
    reqs = s["requests"]
    usage = empty_usage()
    models = Counter()
    cost_est, unpriced = 0.0, set()
    daily = defaultdict(lambda: {"cost": 0.0, "tokens": 0, "requests": 0, "models": defaultdict(lambda: {"requests": 0, "cost": 0.0})})
    by_model = defaultdict(lambda: {"requests": 0, "tokens": 0, "cost": 0.0, "unpriced": False})
    for r in reqs:
        bm = by_model[r["model"] or "unknown"]
        bm["requests"] += r.get("aggregate") or 1
        bm["tokens"] += prompt_tokens(r["usage"]) + r["usage"]["output"]
        bm["cost"] += r["cost"] or 0
        bm["unpriced"] |= r["cost"] is None
        add_usage(usage, r["usage"])
        models[r["model"] or "unknown"] += r.get("aggregate") or 1
        if r["cost"] is None:
            unpriced.add(r["model"] or "unknown")
        else:
            cost_est += r["cost"]
        if r["t"]:
            d = daily[datetime.fromtimestamp(r["t"]).strftime("%Y-%m-%d")]
            d["cost"] += r["cost"] or 0
            d["tokens"] += prompt_tokens(r["usage"]) + r["usage"]["output"]
            d["requests"] += r.get("aggregate") or 1
            dm = d["models"][r["model"] or "unknown"]
            dm["requests"] += r.get("aggregate") or 1
            dm["cost"] += r["cost"] or 0

    # mark requests that follow a compaction (context reset)
    comp_ts = sorted(c["t"] for c in s["compactions"] if c["t"])
    for r in reqs:
        r["after_compaction_reset"] = False
    for ct in comp_ts:
        nxt = next((r for r in reqs if r["t"] and r["t"] > ct), None)
        if nxt:
            nxt["after_compaction_reset"] = True

    tools = defaultdict(lambda: {"calls": 0, "errors": 0, "output_chars": 0, "ms": 0, "timed": 0})
    calls = [e for e in s["events"] if e["kind"] == "tool_call"]
    for e in calls:
        tl = tools[e.get("name") or "?"]
        tl["calls"] += 1
        tl["errors"] += 1 if e.get("is_error") else 0
        tl["output_chars"] += e.get("output_chars") or 0
        if e.get("dur_ms") is not None:
            tl["ms"] += e["dur_ms"]
            tl["timed"] += 1

    per_call = [r for r in reqs if not r.get("aggregate")]  # aggregate rows are totals over many calls
    prompts = [prompt_tokens(r["usage"]) for r in per_call]
    total_prompt = sum(prompt_tokens(r["usage"]) for r in reqs)
    lat = [r["latency_s"] for r in reqs if r.get("latency_s") is not None]
    turn_ms = [t["duration_ms"] for t in s["turns"] if t.get("duration_ms")]
    measured = s.get("measured") or {}

    summary = {
        k: s.get(k) for k in ("key", "agent", "id", "title", "first_prompt", "cwd", "branch", "version", "started",
                              "ended", "parent_key", "subagent", "children", "path", "context_window")
    }
    summary.update({
        "project": Path(s["cwd"]).name if s.get("cwd") else None,
        "title": s.get("title") or ((s.get("subagent") or {}).get("description")) or (s.get("first_prompt") or "")[:80] or "(untitled)",
        "duration_s": round(s["ended"] - s["started"]) if s["started"] and s["ended"] else None,
        "active_ms": sum(turn_ms) if turn_ms else None,
        "models": dict(models),
        "model_stats": {m: {**v, "cost": round(v["cost"], 6) if not v["unpriced"] or v["cost"] else None} for m, v in by_model.items()},
        "n_requests": sum(r.get("aggregate") or 1 for r in reqs),
        "per_call_usage": len(per_call) == len(reqs),
        "n_user": sum(1 for e in s["events"] if e["kind"] == "user"),
        "n_tool_calls": len(calls),
        "n_tool_errors": sum(1 for e in calls if e.get("is_error")),
        "n_compactions": len(s["compactions"]),
        "n_subagents": len(s.get("children") or []),
        "usage": usage,
        "cost": {"estimated": round(cost_est, 6) if not unpriced or cost_est else None,
                 "complete": not unpriced, "unpriced_models": sorted(unpriced),
                 "measured": measured.get("cost_usd"), "measured_tokens": measured.get("tokens_used")},
        "cache_hit_rate": round(usage["cache_read"] / total_prompt, 4) if total_prompt else None,
        "peak_context": max(prompts) if prompts else None,
        "baseline_context": prompts[0] if prompts else None,
        "median_latency_s": round(statistics.median(lat), 2) if lat else None,
        "median_turn_ms": round(statistics.median(turn_ms)) if turn_ms else None,
        "tools": {k: dict(v) for k, v in tools.items()},
        "daily": {k: {**v, "models": {m: dict(x) for m, x in v["models"].items()}} for k, v in daily.items()},
        "stats": s["stats"],
        "rate_limits": s.get("rate_limits"),
        "signals": _signals(s, per_call, calls),
    })
    return summary


def _signals(s, reqs, calls):
    sig = {}
    # 1. cache rebuilds: big write after the first request with little read
    rebuilds, prev = [], None
    for i, r in enumerate(reqs):
        u = r["usage"]
        w = u["cache_write_5m"] + u["cache_write_1h"]
        if prev is not None and w >= REBUILD_MIN_TOKENS and u["cache_read"] < w:
            gap = (r["t"] - prev["t_end"]) if r["t"] and prev.get("t_end") else None
            ttl = 3600 if u["cache_write_1h"] else 300
            if r.get("after_compaction_reset"):
                cause = "compaction"
            elif r["model"] != prev["model"]:
                cause = "model switch"
            elif gap is not None and gap > ttl:
                cause = f"idle gap > {ttl // 60}m TTL"
            else:
                cause = "prefix changed"
            rt = pricing.rates(r["model"])
            waste = w * (rt["cache_write_1h" if u["cache_write_1h"] else "cache_write_5m"] - rt["cache_read"]) / 1e6 if rt else None
            rebuilds.append({"req": i, "t": r["t"], "write_tokens": w, "read_tokens": u["cache_read"],
                             "gap_s": round(gap) if gap is not None else None, "cause": cause, "waste_usd": waste})
        prev = r
    sig["cache_rebuilds"] = rebuilds

    # 2. large tool outputs and their carried cost
    large = []
    for e in calls:
        if (e.get("output_chars") or 0) >= LARGE_OUTPUT_CHARS:
            tok = est_tokens(e["output_chars"])
            large.append({"event": e["i"], "tool": e.get("name"), "chars": e["output_chars"], "est_tokens": tok,
                          "input": (e.get("input") or "")[:200], "carry_usd": _carry(reqs, e["t"], tok) if e["t"] else None})
    sig["large_outputs"] = large

    # 3. repeated identical tool calls
    # Only read-only tools, and a mutating call in between resets the count (re-reading after an edit is fine).
    seen, live = Counter(), set()
    for e in calls:
        if e.get("name") in MUTATING:
            live.clear()
        elif e.get("name") in READ_ONLY and e.get("input"):
            k = (e["name"], e["input"])
            if k in live:
                seen[k] += 1
            live.add(k)
    sig["repeated_calls"] = [{"tool": n, "input": (i or "")[:200], "count": c + 1} for (n, i), c in seen.most_common(10)]

    # 4. context injected by hooks / harness, with carried cost
    inj = defaultdict(lambda: {"chars": 0, "count": 0, "carry_usd": 0.0})
    for c in s["context_sources"]:
        k = inj[(c["kind"], c["name"])]
        k["chars"] += c["chars"]
        k["count"] += 1
        if c.get("t") and k["carry_usd"] is not None:
            cu = _carry(reqs, c["t"] - 0.001, est_tokens(c["chars"]))
            k["carry_usd"] = None if cu is None else k["carry_usd"] + cu
    sig["injections"] = sorted(({"kind": k[0], "name": k[1], **v} for k, v in inj.items()), key=lambda x: -x["chars"])

    # 5. compactions
    sig["compactions"] = s["compactions"]
    return sig


class Store:
    """Caches summaries by (path, mtime, size). Thread-safe enough for the local server."""

    def __init__(self, roots=None):
        self.roots = roots or {}
        self._cache = {}
        self._lock = threading.Lock()
        self.errors = []

    def files(self):
        out = []
        for name, ad in ADAPTERS.items():
            out += [(name, f) for f in ad.discover(self.roots.get(name))]
        return out

    def summaries(self):
        result, errors = [], []
        with self._lock:
            for agent, f in self.files():
                try:
                    st = f.stat()
                    sig = (st.st_mtime, st.st_size, self._sub_sig(f))
                except OSError:
                    continue
                hit = self._cache.get(str(f))
                if not hit or hit[0] != sig:
                    try:
                        sums = [summarize(s) for s in ADAPTERS[agent].parse(f)]
                    except Exception as e:  # one bad file must not take the product down
                        errors.append({"path": str(f), "error": f"{type(e).__name__}: {e}"})
                        continue
                    hit = self._cache[str(f)] = (sig, sums)
                result += hit[1]
            self.errors = errors
        return result

    @staticmethod
    def _sub_sig(f):
        """Changes the main file's stat misses: Claude subagent files, SQLite write-ahead log."""
        wal = Path(str(f) + "-wal")
        w = (wal.stat().st_mtime, wal.stat().st_size) if wal.is_file() else None
        d = f.with_suffix("") / "subagents"
        subs = tuple(sorted((p.name, p.stat().st_size) for p in d.glob("*.jsonl"))) if d.is_dir() else None
        return (w, subs)

    def session(self, key, with_api_log=True):
        """Full parsed session (events, requests) + its summary."""
        agent = key.split(":", 1)[0]
        for s in self.summaries():
            if s["key"] == key:
                main_path = s["path"] if not s["parent_key"] else None
                path = main_path or next(x["path"] for x in self.summaries() if x["key"] == s["parent_key"])
                for full in ADAPTERS[agent].parse(path, with_api_log=with_api_log):
                    if full["key"] == key:
                        full["summary"] = summarize(full)
                        return full
        return None

    def detected_agents(self):
        out = []
        for name, ad in ADAPTERS.items():
            root = Path(self.roots.get(name) or ad.ROOT)
            out.append({"agent": name, "root": str(root), "present": root.is_dir(), "files": len(ad.discover(root))})
        return out


def tree_cost(summaries, key):
    """Estimated cost of a session plus all its subagents (Claude's measured cost covers the whole tree)."""
    by = {s["key"]: s for s in summaries}
    s = by.get(key)
    if not s:
        return None
    total = s["cost"]["estimated"] or 0
    for c in s.get("children") or []:
        if c in by:
            total += by[c]["cost"]["estimated"] or 0
    return total

