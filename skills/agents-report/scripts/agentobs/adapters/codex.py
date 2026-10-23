"""Codex CLI adapter: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl[.zst].

Token semantics (OpenAI convention): cached_input_tokens and cache_write_input_tokens are subsets of
input_tokens; reasoning_output_tokens is a subset of output_tokens. We normalize to disjoint buckets.
"""
import json
import os
import re
import sqlite3
from pathlib import Path

from .. import pricing
from ..util import UnreadableFile, clip, empty_usage, iter_jsonl, text_of, ts

AGENT = "codex"
ROOT = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"


def discover(root=None):
    root = Path(root or ROOT)
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("rollout-*") if p.name.endswith((".jsonl", ".jsonl.zst")))


_WRAPPED = re.compile(r"^\s*<([a-zA-Z_][\w-]*)[^>]*>.*</\1>\s*$", re.S)


def thread_index(home=None):
    """Codex's own thread metadata (title, tokens_used) from its state DB, read-only. {} if absent."""
    home = Path(home or ROOT.parent)
    out = {}
    try:
        with open(home / "session_index.jsonl") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    out.setdefault(d["id"], {})["title"] = d.get("thread_name")
                except (ValueError, KeyError):
                    pass
    except OSError:
        pass
    for db in sorted(home.glob("state_*.sqlite")):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for tid, title, used, branch in con.execute("select id, title, tokens_used, git_branch from threads"):
                o = out.setdefault(tid, {})
                o.setdefault("title", title)
                o["tokens_used"], o["branch"] = used, branch
            con.close()
        except sqlite3.Error:
            pass
    return out


def _usage(u):
    inp = u.get("input_tokens") or 0
    read = u.get("cached_input_tokens") or 0
    write = u.get("cache_write_input_tokens") or 0
    return {"input": max(inp - read - write, 0), "output": u.get("output_tokens") or 0, "cache_read": read,
            "cache_write_5m": write, "cache_write_1h": 0, "reasoning": u.get("reasoning_output_tokens") or 0}


_THREADS = None


def parse(path, with_api_log=False, threads=None):
    global _THREADS
    if threads is None:
        if _THREADS is None:
            _THREADS = thread_index()
        threads = _THREADS
    path = Path(path)
    sid = path.name.split(".")[0][-36:]
    s = {"key": f"{AGENT}:{sid}", "agent": AGENT, "id": sid, "path": str(path), "title": None, "first_prompt": None,
         "cwd": None, "branch": None, "version": None, "started": None, "ended": None,
         "parent_key": None, "subagent": None, "children": [],
         "requests": [], "events": [], "compactions": [], "turns": [], "context_sources": [],
         "measured": None, "context_window": None, "rate_limits": None, "stats": {"bad_lines": 0, "records": 0}}
    stats = {"bad_lines": 0}
    try:
        records = list(iter_jsonl(path, stats))
    except (OSError, UnreadableFile) as e:
        s["stats"]["error"] = str(e)
        return [s]
    s["stats"]["bad_lines"] = stats["bad_lines"]
    model = effort = None
    calls = {}
    seen_resp = set()

    def ev(kind, t, **kw):
        e = {"i": len(s["events"]), "kind": kind, "t": t, **kw}
        s["events"].append(e)
        return e

    for d in records:
        s["stats"]["records"] += 1
        t = ts(d.get("timestamp"))
        if t:
            s["started"] = min(s["started"] or t, t)
            s["ended"] = max(s["ended"] or t, t)
        typ, p = d.get("type"), d.get("payload") or {}
        pt = p.get("type")
        if typ == "session_meta":
            s["cwd"] = p.get("cwd") or s["cwd"]
            s["version"] = p.get("cli_version")
            git = p.get("git") or {}
            s["branch"] = git.get("branch") or s["branch"]
            bi = (p.get("base_instructions") or {}).get("text") or ""
            if bi:
                s["system_prompt"] = [bi]
                s["context_sources"].append({"kind": "base_instructions", "name": "base_instructions", "chars": len(bi), "t": t})
            if p.get("source") not in (None, "cli", "vscode", "exec", "app") and isinstance(p.get("source"), dict):
                s["subagent"] = {"type": json.dumps(p["source"])[:80], "description": None, "tool_use_id": None}
        elif typ == "turn_context":
            model = p.get("model") or model
            effort = p.get("effort") or p.get("reasoning_effort") or effort
        elif typ == "event_msg" and pt == "thread_settings_applied":
            model = (p.get("thread_settings") or {}).get("model") or model
        elif typ == "response_item" and pt == "message":
            role = p.get("role")
            blocks = p.get("content") if isinstance(p.get("content"), list) else [p.get("content")]
            user_parts = []
            for b in blocks:
                text = text_of(b)
                if not text:
                    continue
                if role == "developer" or (role == "user" and (_WRAPPED.match(text) or text.lstrip().startswith("# AGENTS.md"))):
                    head = text.lstrip()
                    name = (head[1:].split(">")[0].split()[0] if head.startswith("<") else head.split("\n")[0].lstrip("# "))[:60] or role
                    s["context_sources"].append({"kind": role, "name": name, "chars": len(text), "t": t})
                    ev("meta", t, text=clip(text, 3000), chars=len(text), name=name)
                elif role == "user":
                    user_parts.append(text)
                elif role == "assistant":
                    ev("assistant", t, text=clip(text), chars=len(text), req=len(s["requests"]))
            if user_parts:
                text = "\n".join(user_parts)
                if s["first_prompt"] is None:
                    s["first_prompt"] = text[:300]
                ev("user", t, text=clip(text), chars=len(text))
        elif typ == "response_item" and pt == "reasoning":
            summ = text_of(p.get("summary"))
            ev("thinking", t, text=clip(summ, 2000) or "[encrypted reasoning]", chars=len(summ), req=len(s["requests"]))
        elif typ == "response_item" and pt in ("custom_tool_call", "function_call", "local_shell_call", "web_search_call"):
            inp = p.get("input") if pt == "custom_tool_call" else p.get("arguments") or json.dumps(p.get("action") or {})
            inp = inp if isinstance(inp, str) else json.dumps(inp)
            e = ev("tool_call", t, id=p.get("call_id") or p.get("id"), name=p.get("name") or pt, input=clip(inp, 3000),
                   input_chars=len(inp), req=len(s["requests"]))
            calls[e["id"]] = e
        elif typ == "response_item" and pt in ("custom_tool_call_output", "function_call_output"):
            out = p.get("output")
            out = text_of(out) if not isinstance(out, str) else out
            call = calls.get(p.get("call_id"))
            if call is not None:
                call["output"] = clip(out, 4000)
                call["output_chars"] = len(out)
                call["is_error"] = '"exit_code":0' not in out.replace(" ", "") and '"exit_code":' in out.replace(" ", "")
                call["dur_ms"] = round((t - call["t"]) * 1000) if t and call["t"] else None
        elif typ == "token_usage_record":
            rid = p.get("response_id")
            if rid in seen_resp:
                continue
            seen_resp.add(rid)
            u = _usage(p.get("usage") or {})
            s["requests"].append({"msg_id": rid, "request_ref": None, "request_id": rid, "t": t, "t_end": t,
                                  "model": model, "usage": u, "speed": None, "web_searches": 0,
                                  "stop_reason": None, "effort": effort,
                                  "cost": pricing.cost(model, u), "latency_s": None})
        elif typ == "event_msg" and pt == "token_count":
            info = p.get("info") or {}
            s["context_window"] = info.get("model_context_window") or s["context_window"]
            s["rate_limits"] = p.get("rate_limits") or s["rate_limits"]
        elif typ == "event_msg" and pt == "task_started":
            s["context_window"] = p.get("model_context_window") or s["context_window"]
        elif typ == "event_msg" and pt == "task_complete":
            s["turns"].append({"t": t, "duration_ms": p.get("duration_ms"), "ttft_ms": p.get("time_to_first_token_ms")})
        elif typ == "compacted" or (typ == "event_msg" and pt in ("context_compacted", "compacted")):
            s["compactions"].append({"t": t, "pre_tokens": None, "trigger": pt or typ})
            ev("compaction", t, text="Context compacted")
    meta = threads.get(sid) or {}
    s["title"] = meta.get("title") or (s["first_prompt"] or "")[:80] or None
    s["branch"] = s["branch"] or meta.get("branch")
    if meta.get("tokens_used") is not None:
        s["measured"] = {"cost_usd": None, "tokens_used": meta["tokens_used"]}
    return [s]
