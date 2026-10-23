"""Synthetic, anonymous agent logs for screenshots and demos. Nothing here comes from real sessions.

Writes Claude Code (with exact api-request logs), Codex and Hermes data under OUT, shaped like the real formats,
and prints the environment variables that point Agents Report at it:

    python3 tools/make_demo_data.py /tmp/demo
    eval "$(python3 tools/make_demo_data.py /tmp/demo --env)"; python3 .agents/skills/agents-report/scripts/agents_report.py serve --port 48799
"""
import hashlib
import json
import random
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".agents" / "skills" / "agents-report" / "scripts"))
from agentobs import pricing  # noqa: E402

R = random.Random(7)
NOW = datetime.now(timezone.utc).replace(microsecond=0)
HOME = "/home/alex/code"

PROJECTS = {
    "storefront": ["Add a wishlist to the product page", "Fix the checkout total rounding bug", "Make the cart drawer accessible",
                   "Migrate the product grid to server components", "Speed up the category page"],
    "billing-api": ["Add idempotency keys to the charge endpoint", "Why do webhook retries double-charge?", "Write tests for proration",
                    "Refactor invoice generation into a service", "Add rate limiting to the public API"],
    "mobile-app": ["Offline mode for the orders screen", "Fix the crash on Android 15 when rotating", "Add push notification settings",
                   "Reduce app startup time"],
    "data-pipeline": ["Backfill last quarter's events", "Make the nightly job resumable", "Add schema validation to ingestion",
                      "Why is the dedupe step so slow?"],
    "design-system": ["Add a DatePicker component", "Audit color contrast in dark mode", "Document the Button variants",
                      "Replace the icon set"],
    "infra": ["Move staging to the new cluster", "Add alerts for queue backlog", "Write a runbook for failovers"],
}
BRANCHES = ["main", "feat/wishlist", "fix/rounding", "chore/deps", "feat/offline", "perf/startup"]
FILES = ["src/app/page.tsx", "src/lib/cart.ts", "src/api/charge.ts", "src/services/invoice.ts", "src/components/Drawer.tsx",
         "src/jobs/nightly.py", "src/ingest/schema.py", "tests/test_proration.py", "src/screens/Orders.tsx", "README.md"]
IDENT = ["cart", "order", "invoice", "customer", "total", "price", "event", "batch", "user", "session", "item", "queue"]
REPLIES = ["Found it: the total is rounded per line instead of once.", "Tests pass now.", "I'll check how the endpoint is called first.",
           "That file is large; reading the part we need.", "Done. The change is small and covered by a test.",
           "The slow part is the N+1 query in the loop.", "Updated the docs to match.", "Let me run the suite again."]


def code(n_chars):
    """Plausible-looking source text of about n_chars."""
    out, size = [], 0
    while size < n_chars:
        a, b = R.choice(IDENT), R.choice(IDENT)
        line = R.choice([f"export function get{a.title()}{b.title()}({a}: {b.title()}) {{",
                         f"  const {a} = await db.{b}.findMany({{ where: {{ id }} }});",
                         f"  if (!{a}) throw new NotFoundError('{b}');", "  return result;", "}",
                         f"def {a}_{b}(self, {a}):", f"    return self.{b}.get({a}.id)",
                         f"// TODO: handle {a} without {b}", f"  {a}.total += {b}.price * {b}.qty;"])
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def test_log(n_chars):
    """Test-runner output of about n_chars."""
    out, size = [], 0
    while size < n_chars:
        line = R.choice([f"  ✓ {R.choice(IDENT)} {R.choice(['totals', 'rounding', 'retries', 'empty input', 'pagination'])} ({R.randint(2, 90)} ms)",
                         f" PASS  src/{R.choice(IDENT)}.test.ts", f"  ✓ handles {R.choice(IDENT)} without {R.choice(IDENT)}"])
        out.append(line)
        size += len(line) + 1
    return "\n".join(out + [f"Tests: {len(out)} passed, {len(out)} total"])


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def h(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


# ---------- Claude Code ----------
SYSTEM = ["You are a coding agent running in the user's terminal.",
          "<intro>\nYou help with software engineering tasks. " + "Follow the project's conventions, keep changes small, and verify them. " * 120,
          "<guidelines>\n# Working with the user\n" + "Explain what you changed and why, briefly. Ask before destructive actions. " * 230]
TOOLS = [("Read", 2800), ("Edit", 2600), ("Write", 1800), ("Bash", 5200), ("Grep", 2400), ("Glob", 900), ("Agent", 4300),
         ("WebFetch", 1600), ("TodoWrite", 3100), ("mcp__github__create_pull_request", 1400), ("mcp__github__list_issues", 1200),
         ("mcp__linear__get_issue", 900), ("mcp__linear__update_issue", 1100)]
DEFERRED = [("mcp__sentry__search_events", 1300), ("mcp__figma__get_frame", 1500), ("NotebookEdit", 1200), ("WebSearch", 1400)]
HARNESS = ("SessionStart:startup hook success: project rules loaded\n# Project rules\n" + "Use pnpm. Run tests before committing. " * 40 +
           "\n# Environment\nWorking directory: {cwd}\nPlatform: linux\n"
           "Available agent types for the Agent tool:\n" + "- explorer: read-only search across the codebase\n" * 12 +
           "# MCP Server Instructions\n## github\nUse the github tools for pull requests and issues.\n" * 3 +
           "The following skills are available for use with the Skill tool:\n" +
           "".join(f"- skill-{i}: helps with task family {i}, with examples and checklists for that kind of work.\n" for i in range(60)))


def shape():
    tools = [{"name": n, "description": ("Tool documentation. " * (c // 20))[:c], "input_schema": {"type": "object"}} for n, c in TOOLS]
    tools += [{"name": n, "description": ("Deferred tool. " * (c // 15))[:c], "input_schema": {"type": "object"}, "defer_loading": True}
              for n, c in DEFERRED]
    return {"system": [{"type": "text", "text": t} for t in SYSTEM], "tools": tools}


BASE_TOKENS = round(sum(len(t) for t in SYSTEM) / 4 + sum(c for _, c in TOOLS + DEFERRED) / 3.2)


def tool_call():
    name = R.choices(["Read", "Bash", "Grep", "Edit", "Glob"], [5, 3, 2, 3, 1])[0]
    f = R.choice(FILES)
    inp = {"Read": {"file_path": f}, "Bash": {"command": R.choice(["pnpm test", "pytest -q", "pnpm lint", "git diff --stat"])},
           "Grep": {"pattern": R.choice(IDENT), "path": "src"}, "Edit": {"file_path": f, "old_string": "total", "new_string": "roundedTotal"},
           "Glob": {"pattern": "src/**/*.ts"}}[name]
    size = {"Read": R.choice([1500, 4000, 9000, 16000, 42000]), "Bash": R.randint(300, 6000), "Grep": R.randint(200, 3000),
            "Edit": 120, "Glob": R.randint(200, 900)}[name]
    out = code(size) if name in ("Read", "Grep") else test_log(size) if name == "Bash" else "The file was updated."
    return name, inp, out


def claude_session(root, project, start, n_req, model, gap_rebuild=False, subagent=False, compact=False):
    sid = str(uuid.UUID(int=R.getrandbits(128), version=4))
    cwd = f"{HOME}/{project}"
    proj = root / "projects" / cwd.replace("/", "-")
    proj.mkdir(parents=True, exist_ok=True)
    branch = R.choice(BRANCHES)
    rec, t = [], start
    sh = "S" + h(sid)
    rec.append({"type": "api-request-shape", "sessionId": sid, "shapeHash": sh, "shape": shape()})
    base = {"sessionId": sid, "cwd": cwd, "gitBranch": branch, "version": "2.1.308"}

    def put(d, **kw):
        rec.append({**base, **d, **kw})

    hook = HARNESS.format(cwd=cwd)
    put({"type": "attachment", "uuid": h(sid, "hook"), "timestamp": iso(t),
         "attachment": {"type": "hook_success", "hookName": "SessionStart:startup", "content": hook[:2400]},
         "rendered": [{"content": "<system-reminder>\n" + hook[:2400] + "\n</system-reminder>"}]})
    msgs = [{"role": "system", "content": [{"type": "text", "text": hook}]}]
    blob_of = []

    def blob(m):
        k = h(sid, len(blob_of), json.dumps(m)[:200])
        rec.append({"type": "api-request-blob", "sessionId": sid, "hash": k, "message": m})
        blob_of.append(k)
        return k

    sys_blob = blob(msgs[0])
    prompts = PROJECTS[project]
    usage_by_model, prev_total, prev_ref, keep_from = {}, 0, None, 0
    tail = [sys_blob]
    req = 0
    rebuild_at = R.randint(n_req // 3, n_req - 2) if gap_rebuild and n_req > 6 else None
    compact_at = int(n_req * 0.7) if compact else None
    sub_at = R.randint(2, max(2, n_req - 2)) if subagent else None
    turn_left = 0
    while req < n_req:
        if turn_left <= 0:  # a new prompt from the user
            t += timedelta(minutes=R.randint(1, 6))
            if rebuild_at and req >= rebuild_at:
                t += timedelta(minutes=R.randint(70, 300))  # a break longer than the cache TTL
                rebuild_at = None
            prompt = R.choice(prompts)
            m = {"role": "user", "content": [{"type": "text", "text": "<system-reminder>\nToday's date is " + t.date().isoformat() + ".\n</system-reminder>"},
                                             {"type": "text", "text": prompt}]}
            put({"type": "user", "uuid": h(sid, "u", req), "timestamp": iso(t), "message": {"role": "user", "content": prompt}})
            msgs.append(m)
            tail.append(blob(m))
            turn_left = R.randint(2, 9)
            turn_start = t
        turn_left -= 1
        t += timedelta(seconds=R.randint(4, 40))
        mid = "msg_" + h(sid, req)
        ref = "rq" + h(sid, "r", req)
        last_in_turn = turn_left <= 0 or req == n_req - 1
        content = [{"type": "thinking", "thinking": "", "signature": "E" * R.randint(600, 4000)}]
        if R.random() < 0.5 or last_in_turn:
            content.append({"type": "text", "text": R.choice(REPLIES)})
        calls = []
        if not last_in_turn:
            for _ in range(1 if R.random() < 0.8 else 2):
                name, inp, out = tool_call()
                tid = "toolu_" + h(sid, req, name, len(calls))
                if sub_at is not None and req == sub_at:
                    name, inp, out = "Agent", {"description": "Explore the codebase", "prompt": "Find where totals are computed."}, \
                        "The total is computed in src/lib/cart.ts:42 and again in src/api/charge.ts:88."
                content.append({"type": "tool_use", "id": tid, "name": name, "input": inp})
                calls.append((tid, name, out))
        # exact request log: base = previous request, tail = what was appended since
        rec.append({"type": "api-request", "sessionId": sid, "id": ref, "base": prev_ref, "keep": keep_from, "tail": tail,
                    "shapeHash": sh, "timestamp": iso(t - timedelta(seconds=2)), "querySource": "repl_main_thread",
                    "params": {"model": model, "max_tokens": 64000, "thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}},
                    "cacheControl": [{"path": ["system", 1], "value": {"type": "ephemeral", "ttl": "1h"}},
                                     {"path": ["messages", len(msgs) - 1, "content", 0], "value": {"type": "ephemeral", "ttl": "1h"}}]})
        # usage: the prompt is everything in msgs + system + tools
        chars = sum(len(json.dumps(m["content"])) for m in msgs)
        total = BASE_TOKENS + round(chars / 3.3)
        gap = (t - last_t).total_seconds() if req else 0
        if req == 0 or gap > 3600:
            read, write = 0, total
        else:
            read, write = prev_total, max(total - prev_total, 0)
        out_tokens = R.randint(80, 900)
        u = {"input_tokens": R.randint(2, 12), "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
             "output_tokens": out_tokens, "cache_creation": {"ephemeral_1h_input_tokens": write, "ephemeral_5m_input_tokens": 0}}
        put({"type": "assistant", "uuid": h(sid, "a", req), "timestamp": iso(t), "requestRef": ref, "requestId": "req_" + mid,
             "message": {"id": mid, "model": model, "role": "assistant", "content": content, "usage": u,
                         "stop_reason": "end_turn" if last_in_turn else "tool_use"}})
        mu = usage_by_model.setdefault(model, {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0})
        mu["inputTokens"] += u["input_tokens"]
        mu["outputTokens"] += out_tokens
        mu["cacheReadInputTokens"] += read
        mu["cacheCreationInputTokens"] += write
        prev_total, last_t, prev_ref = total + out_tokens, t, ref
        asst_msg = {"role": "assistant", "content": content}
        msgs.append(asst_msg)
        keep_from = len(msgs) - 1
        tail = [blob(asst_msg)]
        if calls:
            t += timedelta(seconds=R.randint(1, 20))
            results = [{"type": "tool_result", "tool_use_id": tid, "content": out, **({"is_error": True} if name == "Bash" and R.random() < 0.08 else {})}
                       for tid, name, out in calls]
            m = {"role": "user", "content": results}
            put({"type": "user", "uuid": h(sid, "tr", req), "timestamp": iso(t), "message": m})
            msgs.append(m)
            tail.append(blob(m))
            for tid, name, out in calls:
                if name == "Agent":
                    write_subagent(proj, sid, cwd, tid, t)
        if last_in_turn:
            put({"type": "system", "subtype": "turn_duration", "durationMs": int((t - turn_start).total_seconds() * 1000), "timestamp": iso(t)})
        req += 1
        if compact_at and req == compact_at:
            t += timedelta(seconds=30)
            put({"type": "system", "subtype": "compact_boundary", "timestamp": iso(t), "compactMetadata": {"trigger": "auto", "preTokens": total}})
            summary = "Summary of the work so far: " + "the user asked for changes; they were made and tested. " * 60
            put({"type": "user", "uuid": h(sid, "cs"), "timestamp": iso(t), "isCompactSummary": True, "message": {"role": "user", "content": summary}})
            msgs = [msgs[0], {"role": "user", "content": [{"type": "text", "text": summary}]}]
            prev_ref, keep_from, tail = None, 0, [sys_blob, blob(msgs[1])]
            last_t = t - timedelta(hours=2)  # forces a full write on the next request
            turn_left = 0
    title = R.choice(prompts)
    put({"type": "ai-title", "aiTitle": title})
    for mdl, mu in usage_by_model.items():
        cost = pricing.cost(mdl, {"input": mu["inputTokens"], "output": mu["outputTokens"], "cache_read": mu["cacheReadInputTokens"],
                                  "cache_write_5m": 0, "cache_write_1h": mu["cacheCreationInputTokens"], "reasoning": 0}) or 0
        mu["costUSD"] = round(cost, 4)
    total_cost = sum(mu["costUSD"] for mu in usage_by_model.values()) * R.uniform(1.0, 1.05)
    put({"type": "cost-state", "totalCostUSD": round(total_cost, 4), "totalAPIDuration": n_req * 9000, "totalToolDuration": n_req * 1500,
         "modelUsage": usage_by_model})
    (proj / f"{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in rec) + "\n")


def write_subagent(proj, sid, cwd, tool_id, t):
    aid = h(sid, tool_id)[:12]
    d = proj / sid / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    recs, size = [], 18000
    for i in range(R.randint(4, 10)):
        t += timedelta(seconds=R.randint(3, 15))
        size += R.randint(2000, 9000)
        recs.append({"type": "assistant", "isSidechain": True, "agentId": aid, "sessionId": sid, "cwd": cwd, "uuid": h(aid, i), "timestamp": iso(t),
                     "message": {"id": "msg_" + h(aid, i), "model": "claude-sonnet-5-5", "role": "assistant",
                                 "content": [{"type": "tool_use", "id": "toolu_" + h(aid, i), "name": "Grep", "input": {"pattern": R.choice(IDENT)}}],
                                 "usage": {"input_tokens": 4, "cache_read_input_tokens": size - 3000 if i else 0,
                                           "cache_creation_input_tokens": 3000 if i else size, "output_tokens": R.randint(60, 300),
                                           "cache_creation": {"ephemeral_5m_input_tokens": 3000 if i else size, "ephemeral_1h_input_tokens": 0}}}})
    (d / f"agent-{aid}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    (d / f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": "explorer", "description": "Explore the codebase", "toolUseId": tool_id}))


# ---------- Codex ----------
def codex_session(root, project, start):
    cid = str(uuid.UUID(int=R.getrandbits(128), version=7))
    t, cwd, recs = start, f"{HOME}/{project}", []
    recs.append({"timestamp": iso(t), "type": "session_meta", "payload": {"id": cid, "cwd": cwd, "cli_version": "0.154.0", "source": "cli",
                                                                           "git": {"branch": R.choice(BRANCHES)}, "base_instructions": {"text": "You are a coding agent. " * 300}}})
    recs.append({"timestamp": iso(t), "type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "medium"}})
    recs.append({"timestamp": iso(t), "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": R.choice(PROJECTS[project])}]}})
    ctx = 12000
    for i in range(R.randint(6, 30)):
        t += timedelta(seconds=R.randint(5, 40))
        recs.append({"timestamp": iso(t), "type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": f"c{i}",
                                                                                "arguments": json.dumps({"cmd": R.choice(["rg total", "pnpm test", "cat src/lib/cart.ts"])})}})
        ctx += R.randint(500, 5000)
        recs.append({"timestamp": iso(t), "type": "token_usage_record", "payload": {"response_id": f"r{i}", "usage": {
            "input_tokens": ctx, "cached_input_tokens": int(ctx * 0.9), "output_tokens": R.randint(50, 400), "reasoning_output_tokens": R.randint(0, 120)}}})
        recs.append({"timestamp": iso(t + timedelta(seconds=2)), "type": "response_item", "payload": {"type": "function_call_output", "call_id": f"c{i}",
                                                                                                       "output": json.dumps({"exit_code": 0, "output": code(800)})}})
    recs.append({"timestamp": iso(t), "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": R.choice(REPLIES)}]}})
    recs.append({"timestamp": iso(t), "type": "event_msg", "payload": {"type": "task_complete", "duration_ms": int((t - start).total_seconds() * 1000)}})
    d = root / "sessions" / start.strftime("%Y/%m/%d")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"rollout-{start.strftime('%Y-%m-%dT%H-%M-%S')}-{cid}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")


# ---------- Hermes ----------
def hermes_db(root, sessions):
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "state.db")
    con.executescript("""
      create table system_prompts (hash text primary key, prompt text);
      create table sessions (id text primary key, source text, title text, cwd text, git_branch text, model text,
        system_prompt text, system_prompt_hash text, parent_session_id text, started_at real, ended_at real,
        input_tokens int, output_tokens int, cache_read_tokens int, cache_write_tokens int, reasoning_tokens int,
        api_call_count int, actual_cost_usd real, billing_mode text, billing_provider text);
      create table messages (id integer primary key, session_id text, role text, content text, tool_call_id text,
        tool_calls text, tool_name text, timestamp real, reasoning text, reasoning_content text, _compressed_summary int default 0);
      create table session_model_usage (session_id text, model text, task text, api_call_count int, input_tokens int,
        output_tokens int, cache_read_tokens int, cache_write_tokens int, reasoning_tokens int, first_seen real, last_seen real);
    """)
    con.execute("insert into system_prompts values ('p1', ?)", ("You are Hermes, a desktop agent. " * 200,))
    for i, (project, start) in enumerate(sessions):
        sid, t0 = f"h{i:03d}", start.timestamp()
        calls = R.randint(20, 90)
        con.execute("insert into sessions values (?,?,?,?,?,?,?,?,?,?,?,0,0,0,0,0,?,null,null,'anthropic')",
                    (sid, "desktop", R.choice(PROJECTS[project]), f"{HOME}/{project}", "main", "claude-sonnet-5-5", None, "p1", None,
                     t0, t0 + calls * 25, calls))
        t = t0
        con.execute("insert into messages (session_id, role, content, timestamp) values (?,?,?,?)", (sid, "user", R.choice(PROJECTS[project]), t))
        for j in range(calls // 3):
            t += R.randint(10, 40)
            con.execute("insert into messages (session_id, role, content, tool_calls, timestamp) values (?,?,?,?,?)",
                        (sid, "assistant", "", json.dumps([{"id": f"c{j}", "type": "function", "function": {"name": "terminal", "arguments": "{\"cmd\":\"make test\"}"}}]), t))
            con.execute("insert into messages (session_id, role, content, tool_call_id, tool_name, timestamp) values (?,?,?,?,?,?)",
                        (sid, "tool", code(R.randint(300, 3000)), f"c{j}", "terminal", t + 3))
        con.execute("insert into session_model_usage values (?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, "claude-sonnet-5-5", "", calls, calls * 40, calls * 300, calls * 30000, calls * 2500, 0, t0, t))
        con.execute("insert into session_model_usage values (?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, "claude-haiku-4-5", "title_generation", 1, 300, 20, 0, 0, 0, t0, t0))
    con.commit()
    con.close()


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo").resolve()
    env = {"AGENTS_REPORT_CLAUDE_PROJECTS": out / "claude" / "projects", "CODEX_HOME": out / "codex", "HERMES_HOME": out / "hermes",
           "PI_CODING_AGENT_DIR": out / "pi", "XDG_DATA_HOME": out / "xdg", "AGENTOBS_STATE": out / "server.json",
           "AGENTOBS_PRICES": out / "prices.json"}
    if "--env" in sys.argv:
        print("\n".join(f"export {k}={v}" for k, v in env.items()))
        return
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} is not empty")
    names = list(PROJECTS)
    # last ~10 weeks: busy; earlier in the year: occasional sessions (the heatmap shows both)
    days = [NOW - timedelta(days=d) for d in range(0, 70) if R.random() < 0.62] + [NOW - timedelta(days=d) for d in range(70, 360) if R.random() < 0.07]
    for i, day in enumerate(sorted(days)):
        recent = (NOW - day).days < 70
        for _ in range(R.choice([1, 1, 2]) if recent else 1):
            start = day.replace(hour=R.randint(8, 18), minute=R.randint(0, 59), second=0)
            if start > NOW:
                start = NOW - timedelta(hours=3)
            project = R.choice(names[:5] if recent else names)
            n = R.choice([12, 25, 40, 70, 110, 160]) if recent else R.randint(5, 20)
            claude_session(out / "claude", project, start, n, R.choice(["claude-opus-5-5"] * 3 + ["claude-sonnet-5-5"]),
                           gap_rebuild=R.random() < 0.4, subagent=R.random() < 0.3, compact=n >= 160)
            if recent and R.random() < 0.15:
                codex_session(out / "codex", R.choice(names), start + timedelta(hours=1))
    hermes_db(out / "hermes", [(R.choice(names), NOW - timedelta(days=d, hours=R.randint(1, 8))) for d in (3, 9, 16, 30, 41)])
    print(f"Demo data written to {out}")


if __name__ == "__main__":
    main()
