"""Cross-session aggregates and evidence-backed recommendations. Pure functions over summaries."""
from datetime import datetime
from collections import defaultdict

from . import pricing
from .util import add_usage, empty_usage, prompt_tokens

CHEAPER = {"opus": "claude-sonnet-5-5", "fable": "claude-opus-5-5", "mythos": "claude-opus-5-5"}


def overview(summaries):
    by_agent = defaultdict(lambda: {"sessions": 0, "cost": 0.0, "measured": 0.0, "measured_sessions": 0, "unpriced": set(), "usage": empty_usage(), "requests": 0})
    by_model = defaultdict(lambda: {"requests": 0, "tokens": 0, "cost": 0.0, "unpriced": False, "sessions": 0})
    by_project = defaultdict(lambda: {"sessions": 0, "cost": 0.0, "tokens": 0})
    daily = defaultdict(lambda: defaultdict(float))
    tools = defaultdict(lambda: {"calls": 0, "errors": 0, "output_chars": 0, "ms": 0, "timed": 0})
    usage = empty_usage()
    for s in summaries:
        a = by_agent[s["agent"]]
        a["sessions"] += 0 if s["parent_key"] else 1
        a["cost"] += s["cost"]["estimated"] or 0
        if s["cost"]["measured"] is not None:
            a["measured"] += s["cost"]["measured"]
            a["measured_sessions"] += 1
        a["unpriced"] |= set(s["cost"]["unpriced_models"])
        a["requests"] += s["n_requests"]
        add_usage(a["usage"], s["usage"])
        add_usage(usage, s["usage"])
        for m, v in (s.get("model_stats") or {}).items():
            bm = by_model[m]
            bm["requests"] += v["requests"]
            bm["tokens"] += v["tokens"]
            bm["cost"] += v["cost"] or 0
            bm["unpriced"] |= v["unpriced"]
            bm["sessions"] += 1
        p = by_project[s["project"] or "(none)"]
        p["sessions"] += 0 if s["parent_key"] else 1
        p["cost"] += s["cost"]["estimated"] or 0
        p["tokens"] += prompt_tokens(s["usage"]) + s["usage"]["output"]
        for d, v in s["daily"].items():
            daily[d][s["agent"]] += v["cost"]
            daily[d]["cost"] += v["cost"]
            for m, x in (v.get("models") or {}).items():
                daily[d]["m:" + m] += x["cost"]
            daily[d]["tokens"] += v["tokens"]
        for n, t in s["tools"].items():
            for k in t:
                tools[n][k] += t[k]
    total_prompt = prompt_tokens(usage)
    for a in by_agent.values():
        a["unpriced"] = sorted(a["unpriced"])
        if a["unpriced"] and not a["cost"]:
            a["cost"] = None  # nothing priced: unavailable, not $0
    # Compare measured vs estimated on the same sessions only (measured covers a session + its subagents).
    by = {s["key"]: s for s in summaries}
    rec = {"sessions": 0, "measured": 0.0, "estimated": 0.0}
    for s in summaries:
        if s["parent_key"] or s["cost"]["measured"] is None:
            continue
        rec["sessions"] += 1
        rec["measured"] += s["cost"]["measured"]
        rec["estimated"] += (s["cost"]["estimated"] or 0) + sum(by[c]["cost"]["estimated"] or 0 for c in s["children"] if c in by)
    return {
        "sessions": sum(1 for s in summaries if not s["parent_key"]),
        "subagents": sum(1 for s in summaries if s["parent_key"]),
        "requests": sum(s["n_requests"] for s in summaries),
        "usage": usage,
        "cache_hit_rate": round(usage["cache_read"] / total_prompt, 4) if total_prompt else None,
        "cost_estimated": round(sum(s["cost"]["estimated"] or 0 for s in summaries), 4),
        "cost_measured": round(sum(s["cost"]["measured"] or 0 for s in summaries), 4),
        "reconciliation": rec,
        "unpriced_requests": sum(n for s in summaries for m, n in s["models"].items() if m in s["cost"]["unpriced_models"]),
        "by_agent": dict(by_agent),
        "by_model": dict(sorted(((m, {**v, "cost": round(v["cost"], 4) if not v["unpriced"] or v["cost"] else None}) for m, v in by_model.items()),
                                key=lambda kv: (-(kv[1]["cost"] or 0), -kv[1]["requests"]))),
        "by_project": dict(sorted(by_project.items(), key=lambda kv: -kv[1]["cost"])),
        "daily": {d: dict(v) for d, v in sorted(daily.items())},
        "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1]["calls"])),
        "top_sessions": [_brief(s) for s in sorted(summaries, key=lambda s: -(s["cost"]["estimated"] or 0))[:8]],
    }


def activity(summaries):
    """Per calendar day over all history: API requests, sessions started, tokens and estimated cost (heatmap)."""
    days = defaultdict(lambda: {"requests": 0, "sessions": 0, "tokens": 0, "cost": 0.0, "models": defaultdict(int)})
    for s in summaries:
        for d, v in s["daily"].items():
            days[d]["requests"] += v["requests"]
            days[d]["tokens"] += v["tokens"]
            days[d]["cost"] += v["cost"]
            for m, x in (v.get("models") or {}).items():
                days[d]["models"][m] += x["requests"]
        if s["started"] and not s["parent_key"]:
            days[datetime.fromtimestamp(s["started"]).strftime("%Y-%m-%d")]["sessions"] += 1
    return {d: {**v, "cost": round(v["cost"], 4), "models": dict(v["models"])} for d, v in sorted(days.items())}


def _brief(s):
    return {"key": s["key"], "title": s["title"], "agent": s["agent"], "project": s["project"],
            "cost": s["cost"]["estimated"], "started": s["started"], "models": s["models"]}


def _ev(s, detail, **kw):
    return {"key": s["key"], "title": s["title"], "detail": detail, **kw}


def recommendations(summaries):
    """Deterministic rules. Each rec: id, severity, title, why, action, evidence[], savings_usd (estimate or None)."""
    recs = []

    # R1: cache rebuilds after idle gaps / compaction
    rb = [(s, r) for s in summaries for r in s["signals"]["cache_rebuilds"]]
    idle = [(s, r) for s, r in rb if r["cause"].startswith("idle")]
    if idle:
        waste = sum(r["waste_usd"] or 0 for _, r in idle)
        recs.append({
            "id": "cache-idle-rebuild", "severity": "high" if waste > 5 else "medium",
            "title": f"Resuming long contexts after breaks rebuilt the prompt cache {len(idle)}×",
            "why": "The prompt cache expires after its TTL (5 min or 1 h). The next request re-writes the whole context at "
                   "1.25–2× the input price instead of reading it at ~0.05–0.1×.",
            "action": "Before a long break, finish the task or /compact. When you return, start a fresh session with a "
                      "short handoff note instead of resuming a 100k+ token context.",
            "savings_usd": round(waste, 2), "savings_basis": "estimated: rewritten tokens × (write − read rate)",
            "evidence": [_ev(s, f"request #{r['req']}: {r['write_tokens']:,} tokens rewritten after {r['gap_s'] // 60 if r['gap_s'] else '?'} min idle",
                             req=r["req"], usd=r["waste_usd"]) for s, r in sorted(idle, key=lambda x: -(x[1]["waste_usd"] or 0))[:8]],
        })
    other = [(s, r) for s, r in rb if r["cause"] == "prefix changed"]
    if len(other) >= 3:
        waste = sum(r["waste_usd"] or 0 for _, r in other)
        recs.append({
            "id": "cache-prefix-change", "severity": "medium",
            "title": f"{len(other)} cache rebuilds without an idle gap — the prompt prefix changed",
            "why": "Any byte change early in the prompt (tools list, system prompt, instructions, MCP servers connecting, "
                   "model/effort change) invalidates everything after it.",
            "action": "Avoid toggling MCP servers, plugins, effort or model mid-session; keep CLAUDE.md/AGENTS.md stable while working.",
            "savings_usd": round(waste, 2), "savings_basis": "estimated: rewritten tokens × (write − read rate)",
            "evidence": [_ev(s, f"request #{r['req']}: {r['write_tokens']:,} written, {r['read_tokens']:,} read", req=r["req"], usd=r["waste_usd"])
                         for s, r in sorted(other, key=lambda x: -(x[1]["waste_usd"] or 0))[:8]],
        })

    # R2: large tool outputs carried through context
    lo = [(s, x) for s in summaries for x in s["signals"]["large_outputs"]]
    if lo:
        carry = sum(x["carry_usd"] or 0 for _, x in lo)
        by_tool = defaultdict(int)
        for _, x in lo:
            by_tool[x["tool"]] += 1
        recs.append({
            "id": "large-tool-outputs", "severity": "high" if carry > 5 else "medium",
            "title": f"{len(lo)} tool results over ~10k tokens stayed in context ({', '.join(f'{k} ×{v}' for k, v in sorted(by_tool.items(), key=lambda kv: -kv[1]))})",
            "why": "Every later request re-reads these tokens from cache until the session is compacted or cleared.",
            "action": "Read files with offset/limit, grep for the part you need, cap command output (| head, --quiet), "
                      "or delegate bulk reading to a subagent that returns a summary.",
            "savings_usd": round(carry, 2), "savings_basis": "estimated: chars/4 tokens × (one write + reads on each later request)",
            "evidence": [_ev(s, f"{x['tool']} → {x['chars']:,} chars: {x['input'][:120]}", event=x["event"], usd=x["carry_usd"])
                         for s, x in sorted(lo, key=lambda p: -(p[1]["carry_usd"] or 0))[:8]],
        })

    # R3: hook-injected context
    hooks = defaultdict(lambda: {"chars": 0, "count": 0, "carry": 0.0, "sessions": set()})
    for s in summaries:
        for i in s["signals"]["injections"]:
            if i["kind"].startswith("hook"):
                h = hooks[i["name"]]
                h["chars"] += i["chars"]
                h["count"] += i["count"]
                h["carry"] += i["carry_usd"] or 0
                h["sessions"].add(s["key"])
    big = {n: h for n, h in hooks.items() if h["chars"] / max(h["count"], 1) >= 2000}
    if big:
        recs.append({
            "id": "hook-injection", "severity": "medium",
            "title": f"Hooks inject large text into context ({len(big)} hook{'s' if len(big) > 1 else ''})",
            "why": "Hook output is added to the conversation and paid for on every following request.",
            "action": "Trim hook output to the essential lines, or move long guidance into a skill so it loads only when relevant.",
            "savings_usd": round(sum(h["carry"] for h in big.values()), 2), "savings_basis": "estimated carried cost (upper bound: removing the hook entirely)",
            "evidence": [{"key": None, "title": n, "detail": f"{h['count']} injections, avg {h['chars'] // max(h['count'], 1):,} chars, across {len(h['sessions'])} sessions",
                          "usd": h["carry"]} for n, h in sorted(big.items(), key=lambda kv: -kv[1]["carry"])],
        })

    # R3b: harness listings (skills, MCP instructions, agents, deferred tools) injected into every session
    LIST_KINDS = {"skill_listing": "installed skills", "mcp_instructions_delta": "MCP server instructions",
                  "agent_listing_delta": "subagent types", "deferred_tools_delta": "deferred tool names"}
    per_kind = defaultdict(lambda: {"chars": 0, "sessions": 0, "carry": 0.0})
    main_sessions = [s for s in summaries if not s["parent_key"] and s["n_requests"]]
    for s in main_sessions:
        for i in s["signals"]["injections"]:
            if i["kind"] in LIST_KINDS:
                k = per_kind[i["kind"]]
                k["chars"] += i["chars"]
                k["sessions"] += 1
                k["carry"] += i["carry_usd"] or 0
    skill_calls = sum(s["tools"].get("Skill", {}).get("calls", 0) for s in summaries)
    big_lists = {k: v for k, v in per_kind.items() if v["sessions"] and v["chars"] / v["sessions"] >= 8000}
    if big_lists:
        recs.append({
            "id": "harness-listings", "severity": "medium",
            "title": "Listings of installed skills, MCP servers and agents load into every session",
            "why": "Claude Code tells the model about every installed skill, MCP server and subagent type up front. "
                   "That text is re-read on every request whether or not any of them are used.",
            "action": "Uninstall or disable plugins, skills and MCP servers you don't use (/plugin, /mcp, settings.json). "
                      f"Across these sessions the Skill tool was called {skill_calls} times.",
            "savings_usd": round(sum(v["carry"] for v in big_lists.values()), 2),
            "savings_basis": "estimated carried cost of the listings (upper bound: removing all of them)",
            "evidence": [{"key": None, "title": LIST_KINDS[k], "detail": f"avg {v['chars'] // v['sessions']:,} chars (~{v['chars'] // v['sessions'] // 4:,} tokens) in {v['sessions']} sessions",
                          "usd": v["carry"]} for k, v in sorted(big_lists.items(), key=lambda kv: -kv[1]["carry"])],
        })

    # R4: expensive models on subagents
    subs = [s for s in summaries if s["parent_key"] and s["n_requests"]]
    pricey = []
    for s in subs:
        for m in s["models"]:
            fam = next((f for f in CHEAPER if f in (m or "")), None)
            if fam:
                alt = CHEAPER[fam]
                alt_cost = pricing.cost(alt, s["usage"])
                if s["cost"]["estimated"] and alt_cost is not None:
                    pricey.append((s, m, alt, s["cost"]["estimated"] - alt_cost))
    if pricey and sum(p[3] for p in pricey) > 0.5:
        recs.append({
            "id": "subagent-model", "severity": "low",
            "title": f"{len(pricey)} subagents ran on a top-tier model",
            "why": "Search/exploration and mechanical subagent tasks usually don't need the most capable model.",
            "action": "Set `model: sonnet` (or haiku) in the subagent definition, or pass model when spawning. Keep top-tier for planning and review. Verify quality on your own tasks.",
            "savings_usd": round(sum(p[3] for p in pricey), 2), "savings_basis": "estimated: same tokens re-priced at the cheaper model (quality not guaranteed)",
            "evidence": [_ev(s, f"{(s['subagent'] or {}).get('type') or 'subagent'}: {m} → {alt}", usd=d) for s, m, alt, d in sorted(pricey, key=lambda p: -p[3])[:8]],
        })

    # R5: very long contexts
    long = [s for s in summaries if (s["peak_context"] or 0) > 250_000]
    if long:
        recs.append({
            "id": "long-context", "severity": "medium",
            "title": f"{len(long)} sessions grew past 250k tokens of context",
            "why": "Each request re-reads the whole context; at 500k tokens even cached reads cost ~$0.10 per request on Opus 5.5, and quality degrades with distance.",
            "action": "Use /clear between unrelated tasks, keep one task per session, and hand off with a short summary instead of carrying history.",
            "savings_usd": None, "savings_basis": "unavailable: depends on how the work would have been split",
            "evidence": [_ev(s, f"peak {s['peak_context']:,} tokens over {s['n_requests']} requests, {s['n_compactions']} compactions")
                         for s in sorted(long, key=lambda s: -s["peak_context"])[:8]],
        })

    # R6: tool error hotspots
    errs = defaultdict(lambda: [0, 0])
    for s in summaries:
        for n, t in s["tools"].items():
            errs[n][0] += t["calls"]
            errs[n][1] += t["errors"]
    hot = [(n, c, e) for n, (c, e) in errs.items() if e >= 5 and e / c >= 0.15]
    if hot:
        recs.append({
            "id": "tool-errors", "severity": "low",
            "title": "Tools with high error rates: " + ", ".join(f"{n} ({e}/{c})" for n, c, e in hot),
            "why": "Failed calls cost a round trip and add error text to context.",
            "action": "Open the failing calls in the timeline; common fixes are permission allowlists, correct paths, or project instructions about the toolchain.",
            "savings_usd": None, "savings_basis": "unavailable",
            "evidence": [{"key": None, "title": n, "detail": f"{e} errors in {c} calls ({e / c:.0%})"} for n, c, e in hot],
        })

    # R7: repeated identical calls
    rep = [(s, r) for s in summaries for r in s["signals"]["repeated_calls"] if r["count"] >= 2]
    if rep:
        recs.append({
            "id": "repeated-calls", "severity": "low",
            "title": f"{len(rep)} tool calls were repeated with identical input and no change in between",
            "why": "Re-running an identical call often means the agent lost track of earlier output (after compaction or in long contexts). Some repeats are legitimate (re-reading a file after editing it).",
            "action": "Check whether these repeats were needed; if not, smaller sessions or a note-taking step help the agent keep results.",
            "savings_usd": None, "savings_basis": "unavailable",
            "evidence": [_ev(s, f"{r['tool']} ×{r['count']}: {r['input'][:120]}") for s, r in sorted(rep, key=lambda x: -x[1]["count"])[:8]],
        })

    # R8: unlogged spend (measured > logged)
    gaps = []
    by = {s["key"]: s for s in summaries}
    for s in summaries:
        if s["parent_key"] or s["cost"]["measured"] is None:
            continue
        logged = (s["cost"]["estimated"] or 0) + sum((by[c]["cost"]["estimated"] or 0) for c in s["children"] if c in by)
        if s["cost"]["measured"] - logged > 0.25:
            gaps.append((s, s["cost"]["measured"], logged))
    if gaps:
        recs.append({
            "id": "unlogged-spend", "severity": "info",
            "title": f"${sum(m - l for _, m, l in gaps):.2f} of measured spend has no per-request record",
            "why": "Claude Code's own cost meter includes calls not written to transcripts (titles, classifiers, background work, compaction).",
            "action": "Nothing to fix by itself. Treat per-request analysis as a lower bound on these sessions.",
            "savings_usd": None, "savings_basis": "measured − logged estimate",
            "evidence": [_ev(s, f"measured ${m:.2f} vs logged ${l:.2f}", usd=m - l) for s, m, l in sorted(gaps, key=lambda g: -(g[1] - g[2]))[:8]],
        })

    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return sorted(recs, key=lambda r: (order[r["severity"]], -(r["savings_usd"] or 0)))
