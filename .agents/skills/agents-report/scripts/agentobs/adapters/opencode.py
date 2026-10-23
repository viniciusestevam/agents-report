"""OpenCode adapter: ~/.local/share/opencode/opencode*.db (SQLite, read-only), release v1.x schema.

Built from OpenCode's source (v1.19.4: packages/core/src/session/sql.ts, packages/schema/src/v1/session.ts);
not yet checked against a real database here.
- session: id, parent_id (subagents), title, directory, time_created (ms), cost.
- message.data: {role, time{created,completed}, modelID, providerID, path{cwd}, tokens, cost, agent}.
- part.data: text | reasoning | tool {callID, tool, state{status,input,output,error,time{start,end}}} |
  step-finish {tokens{input,output,reasoning,cache{read,write}}, cost} = one LLM call | compaction.
input excludes cached tokens (OpenCode subtracts them), so buckets are disjoint.
"""
import json
import os
from pathlib import Path

from .. import pricing
from ..util import add_event, clip, empty_usage, jload, new_session, request, sqlite_ro

AGENT = "opencode"
ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "opencode"


def discover(root=None):
    if os.environ.get("OPENCODE_DB") and not root:
        p = Path(os.environ["OPENCODE_DB"])
        return [p] if p.is_file() else []
    root = Path(root or ROOT)
    return sorted(root.glob("opencode*.db")) if root.is_dir() else []


def _usage(tk):
    tk = tk or {}
    cache = tk.get("cache") or {}
    u = empty_usage()
    # ponytail: reasoning counted as billed output on top of output; check against a real DB when one exists.
    u.update(input=tk.get("input") or 0, output=(tk.get("output") or 0) + (tk.get("reasoning") or 0),
             cache_read=cache.get("read") or 0, cache_write_5m=cache.get("write") or 0, reasoning=tk.get("reasoning") or 0)
    return u


def parse(path, with_api_log=False):
    con = sqlite_ro(path)
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if not {"session", "message", "part"} <= tables:
            raise ValueError(f"OpenCode database schema not recognised (tables: {', '.join(sorted(tables))[:200]})")
        rows = con.execute("select * from session order by time_created").fetchall()
        msgs, parts = {}, {}
        for r in con.execute("select id, session_id, time_created, data from message order by time_created, id"):
            msgs.setdefault(r["session_id"], []).append(r)
        for r in con.execute("select id, message_id, time_created, data from part order by time_created, id"):
            parts.setdefault(r["message_id"], []).append(r)
    finally:
        con.close()
    out = {}
    for row in rows:
        s = new_session(AGENT, row["id"], path)
        s.update(title=row["title"], cwd=row["directory"], version=row["version"],
                 started=row["time_created"] / 1000, ended=row["time_updated"] / 1000)
        if row["parent_id"]:
            s["parent_key"] = f"{AGENT}:{row['parent_id']}"
            s["subagent"] = {"type": row["agent"] if "agent" in row.keys() else None, "description": row["title"], "tool_use_id": None}
        for m in msgs.get(row["id"], []):
            _message(s, m, parts.get(m["id"], []))
        s["measured"] = {"cost_usd": row["cost"], "tokens_used": None}
        out[s["key"]] = s
    for s in out.values():
        if s["parent_key"] in out:
            out[s["parent_key"]]["children"].append(s["key"])
    return list(out.values())


def _message(s, m, parts):
    d = jload(m["data"], {}) or {}
    s["stats"]["records"] += 1
    t = (d.get("time") or {}).get("created", m["time_created"]) / 1000
    role, model = d.get("role"), d.get("modelID")
    steps = 0
    for p in parts:
        pd = jload(p["data"], {}) or {}
        pt, pt_t = pd.get("type"), p["time_created"] / 1000
        if pt == "text" and pd.get("text"):
            text = pd["text"]
            if role == "user" and not pd.get("synthetic"):
                if s["first_prompt"] is None:
                    s["first_prompt"] = text[:300]
                add_event(s, "user", pt_t, text=clip(text), chars=len(text))
            elif role == "user":
                add_event(s, "meta", pt_t, name="synthetic", text=clip(text, 3000), chars=len(text))
                s["context_sources"].append({"kind": "synthetic", "name": "synthetic", "chars": len(text), "t": pt_t})
            else:
                add_event(s, "assistant", pt_t, text=clip(text), chars=len(text), req=len(s["requests"]))
        elif pt == "reasoning":
            th = pd.get("text") or ""
            add_event(s, "thinking", pt_t, text=clip(th, 2000), chars=len(th), req=len(s["requests"]))
        elif pt == "tool":
            st = pd.get("state") or {}
            inp = json.dumps(st.get("input"), ensure_ascii=False)
            outp = st.get("output") or st.get("error") or ""
            tm = st.get("time") or {}
            add_event(s, "tool_call", (tm.get("start") or p["time_created"]) / 1000, id=pd.get("callID"), name=pd.get("tool"),
                      input=clip(inp, 3000), input_chars=len(inp), output=clip(outp, 4000), output_chars=len(outp),
                      is_error=st.get("status") == "error", req=len(s["requests"]),
                      dur_ms=(tm["end"] - tm["start"]) if tm.get("end") and tm.get("start") else None)
        elif pt == "step-finish":
            steps += 1
            u = _usage(pd.get("tokens"))
            s["requests"].append(request(p["id"], pt_t, model, u, pricing.cost(model, u), stop_reason=pd.get("reason")))
        elif pt == "compaction":
            s["compactions"].append({"t": pt_t, "pre_tokens": None, "trigger": "auto" if pd.get("auto") else "manual"})
            add_event(s, "compaction", pt_t, text="Context compacted")
    if role == "assistant":
        s["cwd"] = s["cwd"] or (d.get("path") or {}).get("cwd")
        if not steps and d.get("tokens"):  # older messages without step parts: the message total is one call
            u = _usage(d["tokens"])
            tc = (d.get("time") or {}).get("completed")
            s["requests"].append(request(m["id"], t, model, u, pricing.cost(model, u), t_end=tc / 1000 if tc else None,
                                         stop_reason=d.get("finish")))
