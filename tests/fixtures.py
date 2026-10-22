"""Builds small synthetic agent logs with known answers. Shapes mirror real Claude Code 2.1.30x / Codex 0.15x logs."""
import json
from pathlib import Path

SID = "11111111-2222-3333-4444-555555555555"
CODEX_ID = "01a00000-0000-7000-8000-000000000001"


def _w(path, records, extra_lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in records] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n")


def usage(inp=2, read=0, w1h=0, w5m=0, out=10):
    return {"input_tokens": inp, "cache_read_input_tokens": read, "cache_creation_input_tokens": w1h + w5m, "output_tokens": out,
            "cache_creation": {"ephemeral_1h_input_tokens": w1h, "ephemeral_5m_input_tokens": w5m}}


def asst(uuid, mid, ts, content, u, ref=None, model="claude-opus-5-5", **kw):
    return {"type": "assistant", "uuid": uuid, "timestamp": ts, "sessionId": SID, "cwd": "/work/proj", "gitBranch": "main",
            "version": "2.1.305", "requestRef": ref, "requestId": "req_" + mid,
            "message": {"id": mid, "model": model, "role": "assistant", "content": content, "usage": u, "stop_reason": "tool_use"}, **kw}


def user(uuid, ts, content, **kw):
    return {"type": "user", "uuid": uuid, "timestamp": ts, "sessionId": SID, "cwd": "/work/proj", "message": {"role": "user", "content": content}, **kw}


def build_claude(root):
    """One session: 3 API requests (request 1 spans two log lines), a tool error, a hook, a subagent,
    a compaction, a long idle gap that forces a cache rebuild, and an api-request chain."""
    proj = Path(root) / "-work-proj"
    big = "x" * 48_000
    sys_text = "You are a test agent."
    records = [
        {"type": "attachment", "uuid": "a0", "timestamp": "2026-10-01T10:00:00.000Z", "sessionId": SID, "cwd": "/work/proj",
         "attachment": {"type": "hook_success", "hookName": "SessionStart:startup", "content": "H" * 3000},
         "rendered": [{"content": "<system-reminder>\n" + "H" * 3000 + "\n</system-reminder>"}]},
        user("u1", "2026-10-01T10:00:01.000Z", "Fix the bug in parser.py"),
        # request 0: two content lines, same message id, same usage -> counted once
        asst("x1", "msg_A", "2026-10-01T10:00:05.000Z", [{"type": "thinking", "thinking": "", "signature": "sig"}], usage(2, 0, 20_000, 0, 50), ref="rq0"),
        asst("x2", "msg_A", "2026-10-01T10:00:06.000Z", [{"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/work/proj/parser.py"}}], usage(2, 0, 20_000, 0, 50), ref="rq0"),
        user("u2", "2026-10-01T10:00:07.000Z", [{"type": "tool_result", "tool_use_id": "tu1", "content": big}]),
        # request 1: reads cache, calls a failing Bash and the Agent tool
        asst("x3", "msg_B", "2026-10-01T10:00:10.000Z", [{"type": "text", "text": "Running tests."},
             {"type": "tool_use", "id": "tu2", "name": "Bash", "input": {"command": "pytest"}},
             {"type": "tool_use", "id": "tu3", "name": "Agent", "input": {"description": "Explore", "prompt": "look"}}],
             usage(2, 20_000, 12_000, 0, 30), ref="rq1"),
        user("u3", "2026-10-01T10:00:12.000Z", [{"type": "tool_result", "tool_use_id": "tu2", "content": "FAILED", "is_error": True},
                                                {"type": "tool_result", "tool_use_id": "tu3", "content": "found it"}]),
        {"type": "system", "subtype": "turn_duration", "durationMs": 11000, "timestamp": "2026-10-01T10:00:12.500Z", "sessionId": SID},
        # 2 hours later: cache (1h TTL) expired -> request 2 rewrites everything
        user("u4", "2026-10-01T12:00:00.000Z", "Now also update the docs"),
        asst("x4", "msg_C", "2026-10-01T12:00:03.000Z", [{"type": "text", "text": "Done."}], usage(2, 0, 32_100, 0, 20), ref="rq2"),
        {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-10-01T12:01:00.000Z", "sessionId": SID,
         "compactMetadata": {"trigger": "manual", "preTokens": 32_100}},
        user("u5", "2026-10-01T12:02:00.000Z", "Summary of the conversation so far", isCompactSummary=True),
        asst("x5", "msg_D", "2026-10-01T12:02:05.000Z", [{"type": "text", "text": "Continuing."}], usage(2, 0, 5_000, 0, 10), ref="rq3"),
        {"type": "ai-title", "aiTitle": "Fix parser bug", "sessionId": SID},
        {"type": "cost-state", "sessionId": SID, "totalCostUSD": 1.0, "totalAPIDuration": 9000, "totalToolDuration": 2000,
         "modelUsage": {"claude-opus-5-5": {"inputTokens": 8, "outputTokens": 110, "cacheReadInputTokens": 20_000,
                                             "cacheCreationInputTokens": 69_100, "costUSD": 0.5}}},
        # exact request log for rq1: base rq0 (2 msgs) + tail [missing assistant response, tool result blob]
        {"type": "api-request-shape", "sessionId": SID, "shapeHash": "S1",
         "shape": {"system": [{"type": "text", "text": sys_text}], "tools": [{"name": "Read", "description": "Reads files", "input_schema": {}},
                                                                             {"name": "mcp__x__y", "description": "An MCP tool", "input_schema": {}}]}},
        {"type": "api-request-blob", "sessionId": SID, "hash": "h_user1", "message": {"role": "user", "content": [
            {"type": "text", "text": "<system-reminder>\nhook text\n</system-reminder>"}, {"type": "text", "text": "Fix the bug in parser.py"}]}},
        {"type": "api-request", "sessionId": SID, "id": "rq0", "base": None, "keep": 0, "tail": ["h_user1"], "shapeHash": "S1",
         "params": {"model": "claude-opus-5-5", "max_tokens": 1000}, "querySource": "repl_main_thread"},
        {"type": "api-request-blob", "sessionId": SID, "hash": "h_tr1", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": big}]}},
        {"type": "api-request", "sessionId": SID, "id": "rq1", "base": "rq0", "keep": 1, "tail": ["h_missing_asst", "h_tr1"], "shapeHash": "S1",
         "params": {"model": "claude-opus-5-5", "max_tokens": 1000}, "querySource": "repl_main_thread"},
        # rq2: nothing in its tail was stored -> previous response, its tool results and the typed prompt
        # must all be rebuilt from the transcript
        {"type": "api-request", "sessionId": SID, "id": "rq2", "base": "rq1", "keep": 3, "tail": ["m1", "m2", "m3"], "shapeHash": "S1",
         "timestamp": "2026-10-01T12:00:02.000Z", "params": {"model": "claude-opus-5-5"}, "querySource": "repl_main_thread"},
    ]
    _w(proj / f"{SID}.jsonl", records, extra_lines=["{not json"])
    sub = proj / SID / "subagents"
    _w(sub / "agent-abc.jsonl", [
        {"type": "user", "isSidechain": True, "agentId": "abc", "uuid": "s1", "timestamp": "2026-10-01T10:00:10.500Z", "sessionId": SID,
         "cwd": "/work/proj", "message": {"role": "user", "content": "look"}},
        {**asst("s2", "msg_S", "2026-10-01T10:00:11.000Z", [{"type": "text", "text": "found it"}], usage(2, 0, 8_000, 0, 40)), "isSidechain": True, "agentId": "abc"},
    ])
    (sub / "agent-abc.meta.json").write_text(json.dumps({"agentType": "Explore", "description": "Explore", "toolUseId": "tu3"}))
    return proj / f"{SID}.jsonl"


def build_codex(root, compress=True):
    recs = [
        {"timestamp": "2026-10-02T09:00:00.000Z", "type": "session_meta", "payload": {"id": CODEX_ID, "cwd": "/work/other", "cli_version": "0.154.0",
                                                                                      "source": "cli", "base_instructions": {"text": "You are Codex." * 10}}},
        {"timestamp": "2026-10-02T09:00:00.100Z", "type": "turn_context", "payload": {"model": "gpt-6-astra", "cwd": "/work/other"}},
        {"timestamp": "2026-10-02T09:00:00.200Z", "type": "response_item", "payload": {"type": "message", "role": "developer",
                                                                                       "content": [{"type": "input_text", "text": "<permissions>\nsandbox\n</permissions>"}]}},
        {"timestamp": "2026-10-02T09:00:00.300Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context>\n<cwd>/work/other</cwd>\n</environment_context>"},
            {"type": "input_text", "text": "Add a test"}]}},
        {"timestamp": "2026-10-02T09:00:02.000Z", "type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1",
                                                                                       "arguments": "{\"cmd\":\"ls\"}"}},
        {"timestamp": "2026-10-02T09:00:02.100Z", "type": "token_usage_record", "payload": {"response_id": "r1", "usage": {
            "input_tokens": 1000, "cached_input_tokens": 600, "cache_write_input_tokens": 100, "output_tokens": 50, "reasoning_output_tokens": 20}}},
        {"timestamp": "2026-10-02T09:00:02.200Z", "type": "token_usage_record", "payload": {"response_id": "r1", "usage": {
            "input_tokens": 1000, "cached_input_tokens": 600, "cache_write_input_tokens": 100, "output_tokens": 50, "reasoning_output_tokens": 20}}},
        {"timestamp": "2026-10-02T09:00:03.000Z", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                                                                       "output": "{\"exit_code\":1,\"output\":\"boom\"}"}},
        {"timestamp": "2026-10-02T09:00:04.000Z", "type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                                                       "content": [{"type": "output_text", "text": "Done"}]}},
        {"timestamp": "2026-10-02T09:00:04.100Z", "type": "event_msg", "payload": {"type": "task_complete", "duration_ms": 4100, "time_to_first_token_ms": 900}},
    ]
    d = Path(root) / "sessions" / "2026" / "10" / "02"
    d.mkdir(parents=True, exist_ok=True)
    raw = ("\n".join(json.dumps(r) for r in recs) + "\n").encode()
    if compress:
        from compression import zstd
        p = d / f"rollout-2026-10-02T09-00-00-{CODEX_ID}.jsonl.zst"
        p.write_bytes(zstd.compress(raw))
    else:
        p = d / f"rollout-2026-10-02T09-00-00-{CODEX_ID}.jsonl"
        p.write_bytes(raw)
    return p


def build_pi(root):
    """Pi v3 session: 2 assistant calls, one failing tool, a compaction, one malformed line."""
    recs = [
        {"type": "session", "version": 3, "id": "pi-0001", "timestamp": "2026-10-03T10:00:00.000Z", "cwd": "/work/pi"},
        {"type": "model_change", "id": "e1", "parentId": None, "timestamp": "2026-10-03T10:00:00.100Z", "provider": "anthropic", "modelId": "claude-sonnet-4-5"},
        {"type": "message", "id": "e2", "parentId": "e1", "timestamp": "2026-10-03T10:00:01.000Z",
         "message": {"role": "user", "content": "Fix the bug", "timestamp": 1790935201000}},
        {"type": "message", "id": "e3", "parentId": "e2", "timestamp": "2026-10-03T10:00:02.000Z",
         "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "look first"},
                                                      {"type": "toolCall", "id": "t1", "name": "bash", "arguments": {"command": "ls"}}],
                     "provider": "anthropic", "model": "claude-sonnet-4-5", "stopReason": "toolUse", "timestamp": 1790935202000,
                     "usage": {"input": 100, "output": 20, "cacheRead": 1000, "cacheWrite": 50, "totalTokens": 1170,
                               "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0.01}}}},
        {"type": "message", "id": "e4", "parentId": "e3", "timestamp": "2026-10-03T10:00:03.000Z",
         "message": {"role": "toolResult", "toolCallId": "t1", "toolName": "bash", "content": [{"type": "text", "text": "boom"}],
                     "isError": True, "timestamp": 1790935203000}},
        {"type": "message", "id": "e5", "parentId": "e4", "timestamp": "2026-10-03T10:00:04.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Fixed"}], "model": "claude-sonnet-4-5",
                     "stopReason": "stop", "timestamp": 1790935204000,
                     "usage": {"input": 10, "output": 5, "cacheRead": 1200, "cacheWrite": 0, "totalTokens": 1215, "cost": {"total": 0.002}}}},
        {"type": "compaction", "id": "e6", "parentId": "e5", "timestamp": "2026-10-03T10:00:05.000Z", "summary": "S" * 40,
         "firstKeptEntryId": "e5", "tokensBefore": 5000},
        {"type": "session_info", "id": "e7", "parentId": "e6", "timestamp": "2026-10-03T10:00:06.000Z", "name": "Bug hunt"},
    ]
    d = Path(root) / "--work-pi--"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "2026-10-03T10-00-00-000Z_pi-0001.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n{not json\n")
    return p


def build_opencode(root):
    """OpenCode v1 DB: main session (2 step-finish calls, 1 tool) + subagent (message-level tokens only)."""
    import sqlite3
    Path(root).mkdir(parents=True, exist_ok=True)
    p = Path(root) / "opencode.db"
    con = sqlite3.connect(p)
    con.executescript("""
      create table session (id text primary key, parent_id text, title text, directory text, version text,
        time_created integer, time_updated integer, cost real, agent text);
      create table message (id text primary key, session_id text, time_created integer, time_updated integer, data text);
      create table part (id text primary key, message_id text, session_id text, time_created integer, time_updated integer, data text);
    """)
    T = 1790935200000
    con.execute("insert into session values ('ses_main', null, 'Refactor', '/work/oc', '1.19.4', ?, ?, 0.05, null)", (T, T + 9000))
    con.execute("insert into session values ('ses_sub', 'ses_main', 'Explore (@explore subagent)', '/work/oc', '1.19.4', ?, ?, 0.01, 'explore')", (T + 3000, T + 4000))
    msgs = [("msg_1", "ses_main", T, {"role": "user", "time": {"created": T}}),
            ("msg_2", "ses_main", T + 1000, {"role": "assistant", "time": {"created": T + 1000, "completed": T + 8000}, "modelID": "claude-sonnet-4-5",
                                             "providerID": "anthropic", "path": {"cwd": "/work/oc", "root": "/work/oc"}, "cost": 0.05,
                                             "tokens": {"input": 105, "output": 27, "reasoning": 5, "cache": {"read": 1900, "write": 10}}}),
            ("msg_3", "ses_sub", T + 3000, {"role": "assistant", "time": {"created": T + 3000, "completed": T + 4000}, "modelID": "claude-haiku-4-5",
                                            "providerID": "anthropic", "cost": 0.01, "tokens": {"input": 50, "output": 10, "reasoning": 0, "cache": {"read": 0, "write": 0}}})]
    for mid, sid, t, d in msgs:
        con.execute("insert into message values (?,?,?,?,?)", (mid, sid, t, t, json.dumps(d)))
    parts = [("prt_1", "msg_1", T, {"type": "text", "text": "Refactor the parser"}),
             ("prt_2", "msg_2", T + 1100, {"type": "reasoning", "text": "plan", "time": {"start": T + 1100}}),
             ("prt_3", "msg_2", T + 1200, {"type": "tool", "callID": "call_1", "tool": "read",
                                           "state": {"status": "completed", "input": {"filePath": "a.py"}, "output": "x" * 100, "title": "a.py",
                                                     "metadata": {}, "time": {"start": T + 1200, "end": T + 1700}}}),
             ("prt_4", "msg_2", T + 2000, {"type": "step-finish", "reason": "tool-calls", "cost": 0.03,
                                           "tokens": {"input": 100, "output": 20, "reasoning": 5, "cache": {"read": 900, "write": 10}}}),
             ("prt_5", "msg_2", T + 7000, {"type": "text", "text": "Done"}),
             ("prt_6", "msg_2", T + 8000, {"type": "step-finish", "reason": "stop", "cost": 0.02,
                                           "tokens": {"input": 5, "output": 7, "reasoning": 0, "cache": {"read": 1000, "write": 0}}})]
    for pid, mid, t, d in parts:
        con.execute("insert into part values (?,?,?,?,?,?)", (pid, mid, "x", t, t, json.dumps(d)))
    con.commit()
    con.close()
    return p


def build_hermes(home):
    """Hermes state.db: main session with 2 usage rows (3 + 2 calls), a tool call, a compression, one subagent."""
    import sqlite3
    Path(home).mkdir(parents=True, exist_ok=True)
    p = Path(home) / "state.db"
    con = sqlite3.connect(p)
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
    T = 1790935200.0
    con.execute("insert into system_prompts values ('h1', 'You are Hermes.')")
    con.execute("insert into sessions values ('s_main','desktop','Plan the release','/work/h','main','claude-sonnet-4-5',null,'h1',null,?,?,0,0,0,0,0,5,null,null,'anthropic')", (T, T + 60))
    con.execute("insert into sessions values ('s_sub','desktop','Check tests','/work/h','main','claude-sonnet-4-5',null,null,'s_main',?,?,40,4,0,0,0,1,null,null,'anthropic')", (T + 10, T + 20))
    con.executemany("insert into messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp, reasoning, _compressed_summary) values (?,?,?,?,?,?,?,?,?)", [
        ("s_main", "user", "Plan the release", None, None, None, T + 1, None, 0),
        ("s_main", "assistant", "", None, json.dumps([{"id": "c1", "type": "function", "function": {"name": "terminal", "arguments": "{\"cmd\":\"ls\"}"}}]), None, T + 2, "think", 0),
        ("s_main", "tool", "file1\nfile2", "c1", None, "terminal", T + 4.5, None, 0),
        ("s_main", "assistant", "Summary of the work so far", None, None, None, T + 30, None, 1),
        ("s_main", "assistant", "Release planned", None, None, None, T + 50, None, 0),
    ])
    con.executemany("insert into session_model_usage values (?,?,?,?,?,?,?,?,?,?,?)", [
        ("s_main", "claude-sonnet-4-5", "", 3, 300, 30, 3000, 100, 0, T + 2, T + 50),
        ("s_main", "claude-haiku-4-5", "title_generation", 2, 20, 5, 0, 0, 0, T + 3, T + 3),
    ])
    con.commit()
    con.close()
    return p
