"""Claude Code adapter: ~/.claude/projects/<project>/<session>.jsonl (+ <session>/subagents/agent-*.jsonl).

Format notes (verified against Claude Code 2.1.2xx-2.1.30x logs):
- One API response is written as several `assistant` lines (one per content block) that all repeat
  the same `message.usage`. Usage must be counted once per `message.id`.
- `attachment.rendered[].content` is the exact text injected into the model context.
- `cost-state` holds Claude Code's own measured session cost.
"""
import json
import os
from pathlib import Path

from .. import pricing
from ..util import UnreadableFile, add_usage, clip, empty_usage, iter_jsonl, text_of, ts

AGENT = "claude-code"
# AGENTS_REPORT_CLAUDE_PROJECTS reads another projects folder (logs copied from elsewhere, demo data)
# without moving Claude Code's own config, as CLAUDE_CONFIG_DIR would.
ROOT = Path(os.environ.get("AGENTS_REPORT_CLAUDE_PROJECTS") or Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects")


def discover(root=None):
    root = Path(root or ROOT)
    if not root.is_dir():
        return []
    files = []
    for proj in sorted(root.iterdir()):
        if proj.is_dir():
            files += sorted(proj.glob("*.jsonl"))
    return files


def _usage(u):
    if not u:
        return empty_usage()
    cc = u.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    total_w = u.get("cache_creation_input_tokens") or 0
    if w5 is None and w1 is None:
        w5, w1 = total_w, 0  # older logs: no TTL split -> assume default 5m TTL
    return {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
            "cache_read": u.get("cache_read_input_tokens") or 0,
            "cache_write_5m": w5 or 0, "cache_write_1h": w1 or 0,
            "reasoning": (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0}


def _new_session(key, sid, path):
    return {"key": key, "agent": AGENT, "id": sid, "path": str(path), "title": None, "first_prompt": None,
            "cwd": None, "branch": None, "version": None, "started": None, "ended": None,
            "parent_key": None, "subagent": None, "children": [],
            "requests": [], "events": [], "compactions": [], "turns": [], "context_sources": [],
            "measured": None, "api_log": {"requests": [], "shapes": {}, "blobs": {}},
            "stats": {"bad_lines": 0, "records": 0}}


def parse(path, with_api_log=False):
    """Parse one main-session file plus its subagent files. Returns list of sessions (main first)."""
    path = Path(path)
    sid = path.stem
    stats = {"bad_lines": 0}
    groups = {}  # agentId (None = main thread) -> session
    main = _new_session(f"{AGENT}:{sid}", sid, path)
    groups[None] = main

    sources = [(path, None)]
    subdir = path.with_suffix("") / "subagents"
    metas = {}
    if subdir.is_dir():
        for f in sorted(subdir.glob("agent-*.jsonl")):
            aid = f.stem[len("agent-"):]
            sources.append((f, aid))
            try:
                metas[aid] = json.loads(f.with_suffix(".meta.json").read_text())
            except (OSError, ValueError):
                metas[aid] = {}

    for f, file_aid in sources:
        try:
            records = list(iter_jsonl(f, stats))
        except (OSError, UnreadableFile) as e:
            main["stats"]["error"] = str(e)
            continue
        for d in records:
            aid = d.get("agentId") if d.get("isSidechain") else None
            aid = aid or file_aid
            s = groups.get(aid)
            if s is None:
                s = groups[aid] = _new_session(f"{AGENT}:{sid}/{aid}", f"{sid}/{aid}", f)
                s["parent_key"] = main["key"]
                meta = metas.get(aid, {})
                s["subagent"] = {"type": meta.get("agentType"), "description": meta.get("description"),
                                 "tool_use_id": meta.get("toolUseId")}
                main["children"].append(s["key"])
            _ingest(s, d, with_api_log)

    out = [main] + [s for a, s in groups.items() if a is not None]
    for s in out:
        _finish(s)
    main["stats"]["bad_lines"] = stats["bad_lines"]
    # link Agent tool calls to the subagent they spawned
    by_tool = {s["subagent"]["tool_use_id"]: s["key"] for s in out[1:] if s["subagent"].get("tool_use_id")}
    for e in main["events"]:
        if e["kind"] == "tool_call" and e.get("id") in by_tool:
            e["child_key"] = by_tool[e["id"]]
    return out


def _event(s, kind, t, **kw):
    e = {"i": len(s["events"]), "kind": kind, "t": t, **kw}
    s["events"].append(e)
    return e


def _ingest(s, d, with_api_log):
    s["stats"]["records"] += 1
    typ = d.get("type")
    t = ts(d.get("timestamp"))
    if t:
        s["started"] = min(s["started"] or t, t)
        s["ended"] = max(s["ended"] or t, t)
    if d.get("cwd") and not s["cwd"]:
        s["cwd"] = d["cwd"]  # the directory the session started in = its project
    for k_src, k_dst in (("gitBranch", "branch"), ("version", "version")):
        if d.get(k_src):
            s[k_dst] = d[k_src]

    if typ == "ai-title":
        s["title"] = d.get("aiTitle") or s["title"]
    elif typ == "cost-state":
        s["measured"] = {"cost_usd": d.get("totalCostUSD"), "api_ms": d.get("totalAPIDuration"),
                         "tool_ms": d.get("totalToolDuration"), "model_usage": d.get("modelUsage"),
                         "lines_added": d.get("totalLinesAdded"), "lines_removed": d.get("totalLinesRemoved"),
                         "has_unknown_model_cost": d.get("hasUnknownModelCost")}
    elif typ == "assistant":
        _assistant(s, d, t)
        if with_api_log and d.get("requestRef"):
            # the next api-request references this response by hash but doesn't store it again
            s["api_log"].setdefault("responses", {}).setdefault(d["requestRef"], []).extend((d.get("message") or {}).get("content") or [])
    elif typ == "user":
        _user(s, d, t)
        if with_api_log:
            content = (d.get("message") or {}).get("content")
            blocks = content if isinstance(content, list) else []
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    s["api_log"].setdefault("tool_results", {})[b.get("tool_use_id")] = b
            if not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
                s["api_log"].setdefault("user_msgs", []).append((t, d.get("message")))
    elif typ == "attachment":
        a = d.get("attachment") or {}
        rendered = "".join(r.get("content", "") for r in d.get("rendered") or [] if isinstance(r, dict))
        if a.get("type") == "prompt_snapshot":
            s["system_prompt"] = a.get("systemPrompt")
        if rendered:
            name = a.get("hookName") or a.get("skillName") or a.get("type")
            s["context_sources"].append({"kind": a.get("type"), "name": name, "chars": len(rendered), "t": t})
            if a.get("type") in ("hook_success", "hook_additional_context", "hook_system_message"):
                _event(s, "hook", t, name=name, text=clip(rendered, 1500), chars=len(rendered))
    elif typ == "system":
        st = d.get("subtype")
        if st == "compact_boundary":
            m = d.get("compactMetadata") or {}
            s["compactions"].append({"t": t, "pre_tokens": m.get("preTokens"), "trigger": m.get("trigger")})
            _event(s, "compaction", t, text=f"Context compacted ({m.get('trigger', '?')}), {m.get('preTokens') or '?'} tokens before",
                   pre_tokens=m.get("preTokens"))
        elif st == "turn_duration":
            s["turns"].append({"t": t, "duration_ms": d.get("durationMs"), "messages": d.get("messageCount")})
        elif st in ("local_command", "informational", "away_summary") and d.get("content"):
            _event(s, "system", t, name=st, text=clip(d["content"], 1500))
    elif with_api_log and typ == "api-request":
        s["api_log"]["requests"].append(d)
    elif with_api_log and typ == "api-request-shape":
        s["api_log"]["shapes"][d.get("shapeHash")] = d.get("shape")
    elif with_api_log and typ == "api-request-blob":
        s["api_log"]["blobs"][d.get("hash")] = d.get("message")


def _assistant(s, d, t):
    m = d.get("message") or {}
    mid = m.get("id") or d.get("requestId") or d.get("uuid")
    reqs = s["requests"]
    if d.get("isApiErrorMessage"):
        _event(s, "error", t, text=clip(text_of(m.get("content")), 1500), name=str(d.get("apiErrorStatus") or "api_error"))
        return
    if not reqs or reqs[-1]["msg_id"] != mid:
        if m.get("model") == "<synthetic>":
            return
        u = m.get("usage") or {}
        reqs.append({"msg_id": mid, "request_ref": d.get("requestRef"), "request_id": d.get("requestId"),
                     "t": t, "t_end": t, "model": m.get("model"), "usage": _usage(u), "speed": u.get("speed"),
                     "web_searches": (u.get("server_tool_use") or {}).get("web_search_requests") or 0,
                     "stop_reason": m.get("stop_reason"), "effort": d.get("effort"),
                     "prev_t": s["events"][-1]["t"] if s["events"] else None})
    else:
        r = reqs[-1]
        r["t_end"] = t
        r["usage"] = _usage(m.get("usage")) if m.get("usage") else r["usage"]  # last line is final
        r["stop_reason"] = m.get("stop_reason") or r["stop_reason"]
    req_i = len(reqs) - 1
    for b in m.get("content") or []:
        bt = b.get("type")
        if bt == "text" and b.get("text"):
            _event(s, "assistant", t, text=clip(b["text"]), chars=len(b["text"]), req=req_i)
        elif bt == "thinking":
            th = b.get("thinking") or ""
            _event(s, "thinking", t, text=clip(th, 2000), chars=len(th), req=req_i)
        elif bt in ("tool_use", "server_tool_use"):
            inp = json.dumps(b.get("input"), ensure_ascii=False)
            _event(s, "tool_call", t, id=b.get("id"), name=b.get("name"), input=clip(inp, 3000),
                   input_chars=len(inp), req=req_i, attribution=d.get("attributionSkill") or d.get("attributionMcpServer"))


def _user(s, d, t):
    m = d.get("message") or {}
    content = m.get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        idx = {e.get("id"): e for e in s["events"][-200:] if e["kind"] == "tool_call"}
        for b in content:
            if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                continue
            out = text_of(b.get("content"))
            call = idx.get(b.get("tool_use_id"))
            if call is not None:
                call["output"] = clip(out, 4000)
                call["output_chars"] = len(out)
                call["is_error"] = bool(b.get("is_error"))
                call["dur_ms"] = round((t - call["t"]) * 1000) if t and call["t"] else None
        return
    text = text_of(content)
    if d.get("isMeta") or d.get("isCompactSummary") or text.startswith("<command-") or text.startswith("<local-command"):
        kind = "compaction_summary" if d.get("isCompactSummary") else "meta"
        _event(s, kind, t, text=clip(text, 3000), chars=len(text))
        s["context_sources"].append({"kind": kind, "name": kind, "chars": len(text), "t": t})
        return
    if text.startswith("[Request interrupted"):
        _event(s, "system", t, name="interrupted", text=text)
        return
    if text:
        if s["first_prompt"] is None:
            s["first_prompt"] = text[:300]
        _event(s, "user", t, text=clip(text), chars=len(text))


def _finish(s):
    for r in s["requests"]:
        r["cost"] = pricing.cost(r["model"], r["usage"], r["speed"], r["web_searches"])
        # estimated latency: previous logged event -> first block of this response
        r["latency_s"] = round(r["t"] - r["prev_t"], 2) if r["t"] and r["prev_t"] and r["t"] >= r["prev_t"] else None
