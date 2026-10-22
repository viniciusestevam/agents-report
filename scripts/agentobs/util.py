"""Small shared helpers: reading (possibly zstd-compressed) JSONL, timestamps, text sizing."""
import json
import shutil
import subprocess
from datetime import datetime

try:
    from compression import zstd as _zstd  # Python 3.14+
except ImportError:
    _zstd = None

USAGE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h", "reasoning")


def empty_usage():
    return dict.fromkeys(USAGE_KEYS, 0)


def add_usage(acc, u):
    for k in USAGE_KEYS:
        acc[k] += u.get(k) or 0
    return acc


def prompt_tokens(u):
    """Everything the model read for one request."""
    return u["input"] + u["cache_read"] + u["cache_write_5m"] + u["cache_write_1h"]


class UnreadableFile(Exception):
    pass


def read_bytes(path):
    with open(path, "rb") as f:
        raw = f.read()
    if not str(path).endswith(".zst"):
        return raw
    if _zstd:
        return _zstd.decompress(raw)
    if shutil.which("zstd"):
        return subprocess.run(["zstd", "-dc", str(path)], capture_output=True, check=True).stdout
    raise UnreadableFile("zstd support missing: use Python 3.14+ or install the zstd CLI")


def iter_jsonl(path, stats=None):
    """Yield parsed records; malformed lines are counted in stats['bad_lines'], never fatal."""
    for line in read_bytes(path).decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except ValueError:
            if stats is not None:
                stats["bad_lines"] = stats.get("bad_lines", 0) + 1


def ts(s):
    """ISO-8601 (with Z) -> epoch seconds float, or None."""
    if not s:
        return None
    if isinstance(s, (int, float)):
        return s / 1000 if s > 1e11 else float(s)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def text_of(content):
    """Flatten message content (str or list of blocks) to text for sizing/preview."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict):
                if "text" in b and isinstance(b["text"], str):
                    out.append(b["text"])
                elif b.get("type") == "tool_result":
                    out.append(text_of(b.get("content")))
                elif b.get("type") == "tool_use":
                    out.append(json.dumps(b.get("input"), ensure_ascii=False))
                elif b.get("type") == "image":
                    out.append("[image]")
                elif "content" in b:
                    out.append(text_of(b["content"]))
        return "\n".join(out)
    if isinstance(content, dict):
        return text_of([content])
    return str(content)


def est_tokens(chars):
    # ponytail: chars/4 heuristic; real tokenizers vary ~±30%. Always labelled "estimated".
    return round(chars / 4)


def clip(s, n=4000):
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n… [{len(s) - n:,} more chars]"


def new_session(agent, sid, path):
    """Empty session in the adapter contract shape (references/adapters.md)."""
    return {"key": f"{agent}:{sid}", "agent": agent, "id": sid, "path": str(path), "title": None, "first_prompt": None,
            "cwd": None, "branch": None, "version": None, "started": None, "ended": None,
            "parent_key": None, "subagent": None, "children": [],
            "requests": [], "events": [], "compactions": [], "turns": [], "context_sources": [],
            "measured": None, "context_window": None, "rate_limits": None, "stats": {"bad_lines": 0, "records": 0}}


def add_event(s, kind, t, **kw):
    e = {"i": len(s["events"]), "kind": kind, "t": t, **kw}
    s["events"].append(e)
    if t:
        s["started"] = min(s["started"] or t, t)
        s["ended"] = max(s["ended"] or t, t)
    return e


def request(rid, t, model, usage, cost, t_end=None, stop_reason=None, effort=None, aggregate=None):
    """One API response (or, with aggregate=N, a total over N calls the agent did not log one by one)."""
    return {"msg_id": rid, "request_ref": None, "request_id": rid, "t": t, "t_end": t_end or t, "model": model,
            "usage": usage, "speed": None, "web_searches": 0, "stop_reason": stop_reason, "effort": effort,
            "cost": cost, "latency_s": None, "aggregate": aggregate}


def sqlite_ro(path):
    """Read-only connection that still sees the live WAL (agents write while we read)."""
    import sqlite3
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    return con


def jload(s, default=None):
    try:
        return json.loads(s) if isinstance(s, str) else (s if s is not None else default)
    except ValueError:
        return default
