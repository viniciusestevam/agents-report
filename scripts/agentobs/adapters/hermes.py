"""Hermes Agent adapter: one SQLite store, ~/.hermes/state.db (read-only).

- sessions: one row per session; parent_session_id marks subagents. Title, cwd, branch, system prompt hash.
- messages: user / assistant (text, reasoning, tool_calls JSON) / tool (tool_call_id, tool_name, content).
- session_model_usage: token totals per (session, model, task) with api_call_count. Hermes does not log usage
  per API call, so each row becomes one aggregate "request" (aggregate = number of calls). Measured, not per call.
Token buckets are disjoint (cache_read is far larger than input in real data, so it is not a subset).
"""
import os
from pathlib import Path

from .. import pricing
from ..util import add_event, clip, empty_usage, jload, new_session, request, sqlite_ro

AGENT = "hermes"
ROOT = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def discover(root=None):
    db = Path(root or ROOT) / "state.db"
    return [db] if db.is_file() else []


def _usage(r):
    u = empty_usage()
    u.update(input=r["input_tokens"] or 0, output=r["output_tokens"] or 0, cache_read=r["cache_read_tokens"] or 0,
             cache_write_5m=r["cache_write_tokens"] or 0, reasoning=r["reasoning_tokens"] or 0)
    return u


def parse(path, with_api_log=False):
    con = sqlite_ro(path)
    try:
        prompts = {r["hash"]: r["prompt"] for r in con.execute("select hash, prompt from system_prompts")}
        usage_rows = {}
        for r in con.execute("select * from session_model_usage order by first_seen"):
            usage_rows.setdefault(r["session_id"], []).append(r)
        msgs = {}
        for r in con.execute("select * from messages order by session_id, timestamp, id"):
            msgs.setdefault(r["session_id"], []).append(r)
        rows = con.execute("select * from sessions order by started_at").fetchall()
    finally:
        con.close()

    out = {}
    for row in rows:
        s = new_session(AGENT, row["id"], path)
        keys = row.keys()
        s.update(title=row["title"], cwd=row["cwd"], branch=row["git_branch"],
                 started=row["started_at"], ended=row["ended_at"] or row["started_at"])
        if row["parent_session_id"]:
            s["parent_key"] = f"{AGENT}:{row['parent_session_id']}"
            s["subagent"] = {"type": row["source"], "description": row["title"], "tool_use_id": None}
        sp = row["system_prompt"] or prompts.get(row["system_prompt_hash"])
        if sp:
            s["system_prompt"] = [sp]
            s["context_sources"].append({"kind": "system_prompt", "name": "system prompt", "chars": len(sp), "t": row["started_at"]})
        _messages(s, msgs.get(row["id"], []))
        for u in usage_rows.get(row["id"], []):
            uu = _usage(u)
            s["requests"].append(request(f"{u['model']}:{u['task'] or 'main'}", u["first_seen"], u["model"], uu,
                                         pricing.cost(u["model"], uu), t_end=u["last_seen"], effort=u["task"] or None,
                                         aggregate=u["api_call_count"] or 1))
        if not s["requests"] and (row["input_tokens"] or row["output_tokens"]):
            uu = _usage(row)
            s["requests"].append(request("session", row["started_at"], row["model"], uu, pricing.cost(row["model"], uu),
                                         t_end=row["ended_at"], aggregate=row["api_call_count"] or 1))
        measured = row["actual_cost_usd"] if "actual_cost_usd" in keys else None
        s["measured"] = {"cost_usd": measured, "tokens_used": None, "billing": row["billing_mode"] or row["billing_provider"]}
        s["stats"]["records"] = len(msgs.get(row["id"], []))
        out[s["key"]] = s
    for s in out.values():
        if s["parent_key"] in out:
            out[s["parent_key"]]["children"].append(s["key"])
    return list(out.values())


def _messages(s, rows):
    calls = {}
    for m in rows:
        t, role, text = m["timestamp"], m["role"], m["content"] or ""
        if m["_compressed_summary"]:
            s["compactions"].append({"t": t, "pre_tokens": None, "trigger": "compression"})
            add_event(s, "compaction", t, text="Context compressed")
            add_event(s, "compaction_summary", t, text=clip(text, 3000), chars=len(text))
            s["context_sources"].append({"kind": "compaction_summary", "name": "compression summary", "chars": len(text), "t": t})
        elif role == "user":
            if s["first_prompt"] is None:
                s["first_prompt"] = text[:300]
            add_event(s, "user", t, text=clip(text), chars=len(text))
        elif role == "assistant":
            r = m["reasoning"] or m["reasoning_content"] or ""
            if r:
                add_event(s, "thinking", t, text=clip(r, 2000), chars=len(r))
            if text:
                add_event(s, "assistant", t, text=clip(text), chars=len(text))
            for c in jload(m["tool_calls"], []) or []:
                fn = c.get("function") or {}
                args = fn.get("arguments") if isinstance(fn.get("arguments"), str) else str(fn.get("arguments") or "")
                e = add_event(s, "tool_call", t, id=c.get("id") or c.get("call_id"), name=fn.get("name") or c.get("type"),
                              input=clip(args, 3000), input_chars=len(args))
                calls[e["id"]] = e
        elif role == "tool":
            call = calls.get(m["tool_call_id"])
            if call is None:  # result without a logged call: keep it visible
                call = add_event(s, "tool_call", t, id=m["tool_call_id"], name=m["tool_name"], input="", input_chars=0)
            call["output"] = clip(text, 4000)
            call["output_chars"] = len(text)
            call["is_error"] = text.lstrip().startswith(("Error", "error:", '{"error"'))
            call["dur_ms"] = round((t - call["t"]) * 1000) if t and call["t"] else None
