"""Pi coding agent adapter: ~/.pi/agent/sessions/--<cwd>--/<timestamp>_<id>.jsonl (session format v3).

Built from the documented format (pi.dev/docs/latest/session-format); not yet checked against real files here.
Entries form a tree (id/parentId). Every assistant message on any branch was a real API call, so all count.
Assistant usage: input, output, cacheRead, cacheWrite (disjoint), cost.total = Pi's own cost (stored as measured).
"""
import json
import os
from pathlib import Path

from .. import pricing
from ..util import UnreadableFile, add_event, clip, empty_usage, iter_jsonl, new_session, request, text_of, ts

AGENT = "pi"
ROOT = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent")) / "sessions"


def discover(root=None):
    root = Path(root or ROOT)
    return sorted(root.rglob("*.jsonl")) if root.is_dir() else []


def _text(content):
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return text_of(content)


def parse(path, with_api_log=False):
    path = Path(path)
    s = new_session(AGENT, path.stem.split("_")[-1], path)
    stats = {"bad_lines": 0}
    try:
        records = list(iter_jsonl(path, stats))
    except (OSError, UnreadableFile) as e:
        s["stats"]["error"] = str(e)
        return [s]
    s["stats"]["bad_lines"] = stats["bad_lines"]
    model = effort = None
    calls, measured = {}, 0.0
    for d in records:
        s["stats"]["records"] += 1
        typ, t = d.get("type"), ts(d.get("timestamp"))
        if typ == "session":
            s["id"] = d.get("id") or s["id"]
            s["key"] = f"{AGENT}:{s['id']}"
            s["cwd"], s["version"] = d.get("cwd"), str(d.get("version") or "")
            s["started"] = s["ended"] = t
        elif typ == "session_info" and d.get("name"):
            s["title"] = d["name"]
        elif typ == "model_change":
            model = d.get("modelId") or model
        elif typ == "thinking_level_change":
            effort = d.get("thinkingLevel")
        elif typ == "compaction":
            s["compactions"].append({"t": t, "pre_tokens": d.get("tokensBefore"), "trigger": "compaction"})
            add_event(s, "compaction", t, text=f"Context compacted, {d.get('tokensBefore') or '?'} tokens before")
            summ = d.get("summary") or ""
            add_event(s, "compaction_summary", t, text=clip(summ, 3000), chars=len(summ))
            s["context_sources"].append({"kind": "compaction_summary", "name": "compaction summary", "chars": len(summ), "t": t})
        elif typ == "custom_message":
            text = _text(d.get("content"))
            name = d.get("customType") or "custom"
            add_event(s, "meta", t, name=name, text=clip(text, 3000), chars=len(text))
            s["context_sources"].append({"kind": "custom_message", "name": name, "chars": len(text), "t": t})
        elif typ == "message":
            m = d.get("message") or {}
            role = m.get("role")
            t = ts(m.get("timestamp")) or t
            if role == "user":
                text = _text(m.get("content"))
                if s["first_prompt"] is None:
                    s["first_prompt"] = text[:300]
                add_event(s, "user", t, text=clip(text), chars=len(text))
            elif role == "system":
                text = "\n\n".join(v for v in (m.get("sections") or {}).values() if isinstance(v, str)) or _text(m.get("content"))
                if text:
                    s["system_prompt"] = [text]
                    s["context_sources"].append({"kind": "system_prompt", "name": "system prompt", "chars": len(text), "t": t})
            elif role == "assistant":
                req_i = len(s["requests"])
                for b in m.get("content") or []:
                    bt = b.get("type") if isinstance(b, dict) else None
                    if bt == "text" and b.get("text"):
                        add_event(s, "assistant", t, text=clip(b["text"]), chars=len(b["text"]), req=req_i)
                    elif bt == "thinking":
                        th = b.get("thinking") or ""
                        add_event(s, "thinking", t, text=clip(th, 2000), chars=len(th), req=req_i)
                    elif bt == "toolCall":
                        inp = json.dumps(b.get("arguments"), ensure_ascii=False)
                        e = add_event(s, "tool_call", t, id=b.get("id"), name=b.get("name"), input=clip(inp, 3000),
                                      input_chars=len(inp), req=req_i)
                        calls[e["id"]] = e
                u = m.get("usage") or {}
                if u:
                    uu = empty_usage()
                    uu.update(input=u.get("input") or 0, output=u.get("output") or 0,
                              cache_read=u.get("cacheRead") or 0, cache_write_5m=u.get("cacheWrite") or 0)
                    mdl = m.get("model") or model
                    s["requests"].append(request(d.get("id"), t, mdl, uu, pricing.cost(mdl, uu),
                                                 stop_reason=m.get("stopReason"), effort=m.get("thinkingLevel") or effort))
                    measured += (u.get("cost") or {}).get("total") or 0
            elif role == "toolResult":
                out = _text(m.get("content"))
                call = calls.get(m.get("toolCallId")) or add_event(s, "tool_call", t, id=m.get("toolCallId"),
                                                                   name=m.get("toolName"), input="", input_chars=0)
                call.update(output=clip(out, 4000), output_chars=len(out), is_error=bool(m.get("isError")),
                            dur_ms=round((t - call["t"]) * 1000) if t and call["t"] else None)
            elif role == "bashExecution" and not m.get("excludeFromContext"):
                cmd, out = m.get("command") or "", m.get("output") or ""
                add_event(s, "tool_call", t, id=d.get("id"), name="bash (user)", input=clip(cmd, 3000), input_chars=len(cmd),
                          output=clip(out, 4000), output_chars=len(out), is_error=bool(m.get("exitCode")), dur_ms=None)
    s["title"] = s["title"] or (s["first_prompt"] or "")[:80] or None
    s["measured"] = {"cost_usd": round(measured, 6) if s["requests"] else None, "tokens_used": None}
    return [s]
