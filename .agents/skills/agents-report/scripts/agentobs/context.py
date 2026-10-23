"""Context Inspector: what one request actually sent to the model, broken down by contributor.

Two strategies, labelled in the output `basis`:
- "exact-request": Claude Code >=2.1.30x logs api-request (+shape +blobs). messages = base.messages[:keep] + tail.
  Every byte of system, tools and messages is known; only the token split is estimated (chars, scaled to the
  measured prompt total from the API usage).
- "transcript": rebuilt from transcript events + injected context. Approximate.
"""
import json
import re

from .util import est_tokens, prompt_tokens

_REMINDER = re.compile(r"^\s*<system-reminder>", re.S)


# Claude Code packs several harness contributors into one system message; these lines start each one.
_SEGMENTS = [
    (re.compile(r"^\S+:\S+ hook success:"), "Hooks"),
    (re.compile(r"^# Environment\b"), "Environment"),
    (re.compile(r"^The following deferred tools"), "Deferred tools"),
    (re.compile(r"^The following tools just became available"), "Tools (loaded mid-session)"),
    (re.compile(r"^Available agent types"), "Agent listing"),
    (re.compile(r"^(# MCP Server Instructions|The following MCP servers)"), "MCP instructions"),
    (re.compile(r"^The following skills are available"), "Skills (listing)"),
    (re.compile(r"^<total_tokens>|^Today's date is"), "Injected reminders"),
    (re.compile(r"^<agent-message"), "Subagent messages"),
]


# Top-level buckets for the overview grid (like Claude Code's /context); groups keep the detail.
CATEGORIES = {
    "System prompt": ["System prompt", "Environment"],
    "Tool definitions": ["Tools", "MCP tools", "Deferred tools", "Tools (loaded mid-session)"],
    "Harness injections": ["Hooks", "Skills (listing)", "Skills (loaded)", "Agent listing", "MCP instructions",
                           "Injected reminders", "Injected context", "Subagent messages", "System messages", "Compaction summary"],
    "Messages": ["User messages", "Assistant text", "Images & documents"],
    "Tool calls": ["Tool calls"],
    "Tool results": ["Tool results"],
    "Thinking": ["Thinking"],
}
_CAT_OF = {g: c for c, gs in CATEGORIES.items() for g in gs}


def _segments(role, t):
    """Split harness text into (group, label, text) by the markers above; user text stays whole."""
    if role != "system":
        return [(_kind_of_text(role, t), _label(t.replace("<system-reminder>", "")), t)]
    out, cur, grp = [], [], None
    for ln in t.split("\n"):
        hit = next((g for rx, g in _SEGMENTS if rx.match(ln)), None)
        if hit and (cur and (hit != grp or hit == "Hooks")):
            out.append((grp, cur))
            cur = []
        if hit:
            grp = hit
        cur.append(ln)
    if cur:
        out.append((grp, cur))
    res = []
    for g, lines in out:
        text = "\n".join(lines)
        res.append((g or _kind_of_text(role, text), _label(text), text))
    return res


def _kind_of_text(role, t):
    """Name what a text block really is: loaded skill, hook output, reminder, or plain message."""
    head = t.lstrip()[:200]
    if head.startswith("Base directory for this skill:") or head.startswith("<command-name>/"):
        return "Skills (loaded)"
    if " hook success:" in head[:120] or head.startswith("<hook") or "hook additional context" in head[:120].lower():
        return "Hooks"
    if _REMINDER.match(t):
        return "Injected reminders"
    return {"user": "User messages", "system": "System messages"}.get(role, "Assistant text")


def _label(text, n=70):
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    return (line[:n] + "…") if len(line) > n else line


def _item(group, label, text_or_chars, preview=None, chars=None, **kw):
    """One contributor. `_text` keeps the full content (served one item at a time, never in the list payload)."""
    full = None if isinstance(text_or_chars, int) else (text_or_chars or "")
    if chars is None:
        chars = text_or_chars if full is None else len(full)
    if preview is None and full is not None:
        preview = full[:600]
    return {"group": group, "label": label, "chars": chars, "est_tokens": est_tokens(chars), "preview": preview,
            "_text": full if full is not None else preview, **kw}


def inspect(session, req_index=None, item=None, find=None):
    """Context of one request. item=N returns that item's full text; find=s keeps only items containing s."""
    reqs = session["requests"]
    if not reqs:
        return {"basis": "unavailable", "notes": ["This session has no API requests."], "items": [], "requests": 0}
    i = len(reqs) - 1 if req_index is None else max(0, min(int(req_index), len(reqs) - 1))
    r = reqs[i]
    log = session.get("api_log") or {}
    api = {a["id"]: a for a in log.get("requests", [])}
    if r.get("request_ref") in api:
        out = _exact(session, api, r["request_ref"])
    else:
        out = _transcript(session, {**r, "t": r.get("t_end") or r["t"]} if r.get("aggregate") else r)
    est = sum(x["est_tokens"] for x in out["items"])
    measured = prompt_tokens(r["usage"])
    if r.get("aggregate"):  # a total over many calls says nothing about one context: size it from the items
        out["notes"].append(f"This agent logs token totals per model ({r['aggregate']} calls here), not per call; "
                            "the context below is rebuilt from the transcript up to the last of those calls.")
        measured = est
    out.update({
        "request": {"index": i, "t": r["t"], "model": r["model"], "usage": r["usage"], "measured_prompt_tokens": measured},
        "requests": len(reqs),
        "context_window": session.get("context_window") or (1_000_000 if (r["model"] or "").startswith("claude-") and "haiku-4" not in (r["model"] or "") else None),
        "est_total": est,
    })
    # Calibrate: scale the chars/4 estimate so contributors sum to the measured total (only when coverage is complete).
    if out["basis"] == "exact-request" and out.get("complete") and est:
        k = measured / est
        for x in out["items"]:
            x["tokens"] = round(x["est_tokens"] * k)
        out["calibration"] = round(k, 3)
        out["notes"].append(f"Token split = character share × measured total ({measured:,}). Ratio vs chars/4: {k:.2f}.")
    else:
        for x in out["items"]:
            x["tokens"] = x["est_tokens"]
        out["unattributed"] = measured - est
        out["notes"].append("Tokens per item are chars/4 estimates; the gap to the measured total is shown as unattributed.")
    groups = {}
    for x in out["items"]:
        g = groups.setdefault(x["group"], {"group": x["group"], "tokens": 0, "chars": 0, "count": 0})
        g["tokens"] += x["tokens"]
        g["chars"] += x["chars"]
        g["count"] += 1
    out["groups"] = sorted(groups.values(), key=lambda g: -g["tokens"])
    cats = {}
    for g in out["groups"]:
        g["category"] = _CAT_OF.get(g["group"], "Messages")
        c = cats.setdefault(g["category"], {"category": g["category"], "tokens": 0, "groups": []})
        c["tokens"] += g["tokens"]
        c["groups"].append(g["group"])
    out["categories"] = sorted(cats.values(), key=lambda c: -c["tokens"])
    for n, x in enumerate(out["items"]):
        x["i"] = n  # position in the request, as sent
    if item is not None:
        x = dict(out["items"][int(item)])
        x["text"] = x.pop("_text")
        return {"item": x}
    if find:
        needle = find.lower()
        out["items"] = [x for x in out["items"] if needle in f"{x['label']}\n{x['_text'] or ''}".lower()]
    for x in out["items"]:
        x.pop("_text")
    return out


def _messages(api, blobs, rid, memo, responses=None, tool_results=None, user_msgs=None):
    """Iteratively resolve the base/keep/tail chain into a message list (None = blob not recorded).
    Unrecorded messages are rebuilt from the transcript where the evidence is unambiguous."""
    from .util import ts
    by_tool = {}
    for content in (responses or {}).values():
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                by_tool[b.get("id")] = content
    chain, cur = [], rid
    while cur and cur not in memo and cur in api:
        chain.append(cur)
        cur = api[cur].get("base")
    msgs = list(memo.get(cur, [])) if cur else []
    for c in reversed(chain):
        a = api[c]
        tail = [blobs.get(h) for h in a.get("tail") or []]
        # tail[0] missing = the base request's assistant response, which lives in the transcript instead
        if tail and tail[0] is None and a.get("base") and (responses or {}).get(a["base"]):
            tail[0] = {"role": "assistant", "content": responses[a["base"]]}
        msgs = msgs[: a.get("keep") or 0]
        t_req = ts(a.get("timestamp"))
        for j, m in enumerate(tail):
            prev = msgs[-1] if msgs else None
            nxt = tail[j + 1] if j + 1 < len(tail) else None
            prev_tool_ids = [b.get("id") for b in (prev or {}).get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"] if prev and prev.get("role") == "assistant" else []
            if m is None and prev_tool_ids and tool_results and all(i in tool_results for i in prev_tool_ids):
                # tool-result message: the transcript's tool_result blocks for the previous call
                m = {"role": "user", "content": [tool_results[i] for i in prev_tool_ids], "_rebuilt": True}
            elif m is None and nxt and isinstance(nxt.get("content"), list):
                # assistant message: the response that issued the tool calls answered by the next message
                ids = [b.get("tool_use_id") for b in nxt["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
                if ids and ids[0] in by_tool:
                    m = {"role": "assistant", "content": by_tool[ids[0]], "_rebuilt": True}
            if m is None and not prev_tool_ids and user_msgs and t_req:
                # typed or queued user message: the latest user record logged before this request
                cand = [um for tt, um in user_msgs if tt and tt <= t_req]
                if cand and cand[-1] not in msgs:
                    m = dict(cand[-1], _rebuilt=True)
            msgs.append(m)
        memo[c] = msgs
    return memo[rid]


def _exact(session, api, rid):
    log = session["api_log"]
    a = api[rid]
    shape = log["shapes"].get(a.get("shapeHash")) or {}
    items, notes = [], []
    for b in shape.get("system") or []:
        t = b.get("text") if isinstance(b, dict) else str(b)
        items.append(_item("System prompt", _label(t), t))
    tool_names = []
    for tl in shape.get("tools") or []:
        name = tl.get("name") or tl.get("type")
        tool_names.append(name)
        grp = "MCP tools" if (name or "").startswith("mcp__") else "Tools"
        if tl.get("defer_loading"):
            grp = "Deferred tools"
        items.append(_item(grp, name, json.dumps(tl, ensure_ascii=False), preview=(tl.get("description") or "")[:600]))
    msgs = _messages(api, log["blobs"], rid, {}, log.get("responses"), log.get("tool_results"), log.get("user_msgs"))
    missing = 0
    tool_names_by_id = {}
    for mi, m in enumerate(msgs):
        if m is None:
            missing += 1
            continue
        role = m.get("role")
        content = m.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
        for b in blocks:
            bt = b.get("type")
            if role == "system" and bt == "tool_addition":
                t = json.dumps(b, ensure_ascii=False)
                items.append(_item("Deferred tools", ((b.get("tool") or {}).get("definition") or {}).get("name") or _label(t), t, msg=mi, role=role))
            elif bt == "text":
                for grp, label, seg in _segments(role, b.get("text") or ""):
                    items.append(_item(grp, label, seg, msg=mi, role=role))
            elif bt == "thinking" or bt == "redacted_thinking":
                t = b.get("thinking") or b.get("data") or ""
                sig = len(b.get("signature") or "")
                if t.strip():
                    items.append(_item("Thinking", _label(t), t, chars=len(t) + sig, msg=mi, role=role))
                else:  # Claude Code often logs only the encrypted signature, which is still sent back
                    note = f"Thinking text is not in the log. Only its encrypted signature ({sig:,} chars) is stored and sent back to the API."
                    items.append(_item("Thinking", "Hidden thinking", note, chars=sig, preview="encrypted signature only", msg=mi, role=role, hidden=True))
            elif bt == "tool_use":
                tool_names_by_id[b.get("id")] = b.get("name")
                t = json.dumps(b.get("input"), ensure_ascii=False)
                items.append(_item("Tool calls", b.get("name"), t, msg=mi, role=role))
            elif bt == "tool_result":
                from .util import text_of
                t = text_of(b.get("content"))
                items.append(_item("Tool results", tool_names_by_id.get(b.get("tool_use_id")) or "tool result", t, msg=mi, role=role))
            elif bt == "image" or bt == "document":
                items.append(_item("Images & documents", bt, 0, preview=f"[{bt}] (token cost not derivable from logs)", msg=mi, role=role))
            else:
                t = json.dumps(b, ensure_ascii=False)
                items.append(_item("Other", bt or "block", t, msg=mi, role=role))
    params = a.get("params") or {}
    out = {"basis": "exact-request", "complete": missing == 0, "items": items, "notes": notes,
           "messages": len(msgs), "missing_messages": missing, "tools": tool_names,
           "params": {k: params.get(k) for k in ("model", "max_tokens", "thinking", "output_config", "context_management")},
           "betas": params.get("betas"), "cache_breakpoints": a.get("cacheControl"), "query_source": a.get("querySource")}
    if missing:
        notes.append(f"{missing} of {len(msgs)} messages were not recorded in the log (deduplicated blobs); their size is unattributed.")
    return out


def _transcript(session, r):
    items, notes = [], ["Rebuilt from the transcript: shows what the agent logged, not the exact bytes sent."]
    sp = session.get("system_prompt")
    if sp:
        for t in sp if isinstance(sp, list) else [sp]:
            if isinstance(t, str) and t and not t.startswith("__"):
                items.append(_item("System prompt", _label(t), t))
    else:
        notes.append("System prompt not recorded for this session (tool definitions also unavailable).")
    t_req = r["t"] or float("inf")
    start = max([c["t"] for c in session.get("compactions", []) if c["t"] and c["t"] < t_req] or [0])
    if start:
        notes.append("Only context after the last compaction is shown.")
    for c in session.get("context_sources", []):
        if c.get("t") and start <= c["t"] <= t_req and c["kind"] not in ("meta", "compaction_summary"):
            items.append(_item("Injected context", c["name"], c["chars"], preview=c["kind"]))
    kinds = {"user": "User messages", "assistant": "Assistant text", "thinking": "Thinking", "meta": "Injected context",
             "compaction_summary": "Compaction summary"}
    for e in session["events"]:
        if not e.get("t") or e["t"] < start or e["t"] > t_req:
            continue
        if e["kind"] in kinds and (e.get("chars") or 0):
            grp = _kind_of_text("user", e.get("text") or "") if e["kind"] == "meta" else kinds[e["kind"]]
            grp = "Injected context" if grp == "User messages" else grp
            items.append(_item(grp, e.get("name") or _label(e.get("text")), e.get("text") or "", chars=e["chars"], role=e["kind"]))
        elif e["kind"] == "tool_call":
            items.append(_item("Tool calls", e.get("name"), e.get("input") or "", chars=e.get("input_chars") or 0, role="assistant"))
            if e.get("output_chars") and e["t"] < t_req:
                items.append(_item("Tool results", e.get("name"), e.get("output") or "", chars=e["output_chars"], role="user"))
    return {"basis": "transcript", "complete": False, "items": items, "notes": notes}
