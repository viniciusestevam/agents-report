"""Unit + integration tests on synthetic fixtures with hand-computed answers. Run: python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"  # ROOT is the skill folder
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from agentobs import analyze, context, pricing  # noqa: E402
from agentobs.adapters import claude_code, codex, hermes, opencode, pi  # noqa: E402
from agentobs.store import Store, summarize  # noqa: E402

HAS_ZSTD = True
try:
    from compression import zstd  # noqa: F401
except ImportError:
    HAS_ZSTD = False


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.claude_root = t / "claude" / "projects"
        cls.codex_home = t / "codex"
        cls.claude_file = fixtures.build_claude(cls.claude_root)
        cls.codex_file = fixtures.build_codex(cls.codex_home, compress=HAS_ZSTD)
        cls.sessions = claude_code.parse(cls.claude_file, with_api_log=True)
        cls.main = cls.sessions[0]
        cls.sub = cls.sessions[1]
        cls.cx = codex.parse(cls.codex_file, threads={})[0]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestPricing(unittest.TestCase):
    def test_known_model_rates(self):
        r = pricing.rates("claude-opus-5-5")
        self.assertEqual((r["input"], r["output"], r["cache_read"], r["cache_write_5m"], r["cache_write_1h"]), (4, 20, 0.2, 5.0, 8))

    def test_suffixes_and_prefixes(self):
        self.assertEqual(pricing.rates("claude-haiku-4-5-20251001")["input"], 1)
        self.assertEqual(pricing.rates("us.anthropic.claude-sonnet-4-5-20250929-v1:0")["input"], 3)
        self.assertEqual(pricing.rates("claude-opus-4-1")["input"], 15)  # must not match claude-opus-4
        self.assertEqual(pricing.rates("claude-opus-4")["input"], 15)

    def test_unknown_is_none_not_zero(self):
        self.assertIsNone(pricing.rates("gpt-6-astra"))
        self.assertIsNone(pricing.cost("gpt-6-astra", {"input": 1, "output": 1, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}))
        self.assertIsNone(pricing.rates(None))

    def test_fast_and_haiku_tier(self):
        u = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
        self.assertAlmostEqual(pricing.cost("claude-opus-5-5", u, speed="fast"), 8.0)
        self.assertAlmostEqual(pricing.cost("claude-haiku-5-5", {**u, "input": 50_000}), 0.005)
        self.assertAlmostEqual(pricing.cost("claude-haiku-5-5", {**u, "input": 200_000}), 0.1)  # >100K prompt tier


class TestClaude(Base):
    def test_usage_deduplicated_per_message(self):
        self.assertEqual(len(self.main["requests"]), 4)
        s = summarize(self.main)
        self.assertEqual(s["usage"], {"input": 8, "output": 110, "cache_read": 20_000, "cache_write_5m": 0, "cache_write_1h": 69_100, "reasoning": 0})
        self.assertAlmostEqual(s["cost"]["estimated"], 0.559032, places=6)

    def test_measured_and_title(self):
        s = summarize(self.main)
        self.assertEqual(s["cost"]["measured"], 1.0)
        self.assertEqual(s["title"], "Fix parser bug")
        self.assertEqual(s["project"], "proj")

    def test_bad_line_counted_not_fatal(self):
        self.assertEqual(self.main["stats"]["bad_lines"], 1)

    def test_tool_pairing_errors_and_duration(self):
        calls = {e["id"]: e for e in self.main["events"] if e["kind"] == "tool_call"}
        self.assertEqual(calls["tu1"]["output_chars"], 48_000)
        self.assertTrue(calls["tu2"]["is_error"])
        self.assertEqual(calls["tu2"]["dur_ms"], 2000)
        self.assertFalse(calls["tu3"]["is_error"])

    def test_subagent_linked(self):
        self.assertEqual(self.sub["parent_key"], self.main["key"])
        self.assertEqual(self.sub["subagent"]["type"], "Explore")
        self.assertEqual(self.main["children"], [self.sub["key"]])
        call = next(e for e in self.main["events"] if e.get("id") == "tu3")
        self.assertEqual(call["child_key"], self.sub["key"])
        self.assertAlmostEqual(summarize(self.sub)["cost"]["estimated"], 0.064808, places=6)

    def test_compaction_and_hook(self):
        s = summarize(self.main)
        self.assertEqual(s["n_compactions"], 1)
        self.assertTrue(self.main["requests"][3]["after_compaction_reset"])
        hooks = [i for i in s["signals"]["injections"] if i["kind"] == "hook_success"]
        self.assertEqual(hooks[0]["name"], "SessionStart:startup")

    def test_signals(self):
        sig = summarize(self.main)["signals"]
        self.assertEqual(len(sig["cache_rebuilds"]), 1)
        rb = sig["cache_rebuilds"][0]
        self.assertEqual((rb["req"], rb["cause"], rb["gap_s"]), (2, "idle gap > 60m TTL", 7193))
        self.assertAlmostEqual(rb["waste_usd"], 32_100 * (8 - 0.2) / 1e6)
        self.assertEqual(len(sig["large_outputs"]), 1)
        self.assertEqual(sig["large_outputs"][0]["est_tokens"], 12_000)


class TestContext(Base):
    def test_exact_reconstruction_fills_missing_response(self):
        c = context.inspect(self.main, 1)
        self.assertEqual(c["basis"], "exact-request")
        self.assertTrue(c["complete"], c["notes"])
        self.assertEqual(c["messages"], 3)
        groups = {g["group"] for g in c["groups"]}
        self.assertTrue({"System prompt", "Tools", "MCP tools", "Tool results", "Injected reminders", "User messages"} <= groups, groups)
        self.assertEqual(c["request"]["measured_prompt_tokens"], 32_002)
        self.assertAlmostEqual(sum(g["tokens"] for g in c["groups"]), 32_002, delta=len(c["items"]))  # calibrated to measured

    def test_unrecorded_messages_rebuilt_from_transcript(self):
        c = context.inspect(self.main, 2)
        self.assertEqual(c["basis"], "exact-request")
        self.assertTrue(c["complete"], c["notes"])
        self.assertEqual(c["messages"], 6)
        labels = [x["label"] for x in c["items"]]
        self.assertIn("Now also update the docs", labels)  # typed prompt
        self.assertIn("Agent", labels)  # tool call from the rebuilt assistant response

    def test_full_item_text_and_search(self):
        c = context.inspect(self.main, 2)
        self.assertTrue(all("_text" not in x and "text" not in x for x in c["items"]))  # list stays light
        self.assertEqual([x["i"] for x in c["items"]], list(range(len(c["items"]))))  # request order
        hit = next(x for x in c["items"] if x["label"] == "Now also update the docs")
        self.assertEqual(hit["role"], "user")
        full = context.inspect(self.main, 2, item=hit["i"])["item"]
        self.assertIn("Now also update the docs", full["text"])
        self.assertEqual(len(full["text"]), full["chars"])
        found = context.inspect(self.main, 2, find="UPDATE THE DOCS")
        self.assertIn(hit["i"], [x["i"] for x in found["items"]])
        self.assertEqual(found["groups"], c["groups"])  # search filters items, not the breakdown
        self.assertEqual(sum(x["tokens"] for x in c["categories"]), sum(g["tokens"] for g in c["groups"]))
        self.assertEqual(sorted(g for x in c["categories"] for g in x["groups"]), sorted(g["group"] for g in c["groups"]))

    def test_transcript_fallback(self):
        c = context.inspect(self.main, 3)  # rq3 has no api-request record
        self.assertEqual(c["basis"], "transcript")
        self.assertIn("unattributed", c)
        self.assertTrue(any("compaction" in n for n in c["notes"]))

    def test_harness_message_split_by_contributor(self):
        text = ("SessionStart:startup hook success: HOOK\n# Rules\nbe lazy\n# Environment\ncwd\n"
                "The following skills are available for use with the Skill tool:\n- a: b\n"
                "# MCP Server Instructions\n## x\n<total_tokens>9 left</total_tokens>")
        segs = context._segments("system", text)
        self.assertEqual([g for g, _, _ in segs], ["Hooks", "Environment", "Skills (listing)", "MCP instructions", "Injected reminders"])
        self.assertEqual(sum(len(t) for _, _, t in segs) + len(segs) - 1, len(text))  # nothing lost
        self.assertEqual(len(context._segments("user", "# Heading\n# Environment")), 1)  # user text never split

    def test_empty_session(self):
        self.assertEqual(context.inspect({"requests": [], "events": []})["basis"], "unavailable")


class TestCodex(Base):
    def test_usage_normalized_and_deduplicated(self):
        self.assertEqual(len(self.cx["requests"]), 1)
        self.assertEqual(self.cx["requests"][0]["usage"], {"input": 300, "output": 50, "cache_read": 600, "cache_write_5m": 100, "cache_write_1h": 0, "reasoning": 20})
        self.assertIsNone(self.cx["requests"][0]["cost"])
        s = summarize(self.cx)
        self.assertIsNone(s["cost"]["estimated"])
        self.assertEqual(s["cost"]["unpriced_models"], ["gpt-6-astra"])

    def test_context_vs_prompt(self):
        self.assertEqual(self.cx["first_prompt"], "Add a test")
        names = [c["name"] for c in self.cx["context_sources"]]
        self.assertEqual(names, ["base_instructions", "permissions", "environment_context"])

    def test_tool_error_and_turn(self):
        call = next(e for e in self.cx["events"] if e["kind"] == "tool_call")
        self.assertTrue(call["is_error"])
        self.assertEqual(self.cx["turns"][0]["ttft_ms"], 900)


class TestAnalyze(Base):
    def test_recommendations_have_evidence_and_action(self):
        sums = [summarize(s) for s in self.sessions] + [summarize(self.cx)]
        recs = analyze.recommendations(sums)
        ids = {r["id"] for r in recs}
        self.assertIn("cache-idle-rebuild", ids)
        self.assertIn("large-tool-outputs", ids)
        self.assertIn("hook-injection", ids)
        for r in recs:
            self.assertTrue(r["evidence"] and r["action"] and r["why"], r["id"])
            self.assertIn(r["severity"], ("high", "medium", "low", "info"))

    def test_overview_unavailable_not_zero(self):
        sums = [summarize(s) for s in self.sessions] + [summarize(self.cx)]
        o = analyze.overview(sums)
        self.assertIsNone(o["by_agent"]["codex"]["cost"])
        self.assertEqual(o["reconciliation"]["sessions"], 1)
        self.assertAlmostEqual(o["reconciliation"]["estimated"], 0.559032 + 0.064808, places=6)


class TestServer(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from agentobs import server
        server.Handler.store = Store(roots={"claude-code": cls.claude_root, "codex": cls.codex_home / "sessions"})
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        super().tearDownClass()

    def get(self, path, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Host": host} if host else {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_presence_endpoints(self):
        from agentobs import server
        server.Handler.presence = p = server.Presence(time.time())
        try:
            self.assertEqual(self.get("/api/presence?tab=a1&state=open")[0], 200)
            self.assertIn("a1", p.tabs)
            bye = lambda origin: urllib.request.Request(f"http://127.0.0.1:{self.port}/api/presence?tab=a1&state=closed",
                                                        data=b"", method="POST", headers={"Origin": origin})
            with self.assertRaises(urllib.error.HTTPError) as e:  # another site can't close our tabs
                urllib.request.urlopen(bye("https://evil.test"))
            self.assertEqual(e.exception.code, 403)
            self.assertIn("a1", p.tabs)
            with urllib.request.urlopen(bye(f"http://127.0.0.1:{self.port}")) as r:
                self.assertEqual(r.status, 200)
            self.assertEqual(p.tabs, {})
        finally:
            server.Handler.presence = None

    def test_routes(self):
        key = f"claude-code:{fixtures.SID}"
        for p in ("/api/health", "/api/overview", "/api/sessions", "/api/recommendations", "/api/sources",
                  f"/api/session?key={key}", f"/api/context?key={key}&req=1", f"/api/session?key={key}/abc", "/"):
            code, body = self.get(p)
            self.assertEqual(code, 200, p)
        code, body = self.get(f"/api/session?key={key}")
        d = json.loads(body)
        self.assertEqual(len(d["requests"]), 4)
        self.assertEqual(len(d["children"]), 1)
        self.assertNotIn("api_log", d)

    def test_security(self):
        self.assertEqual(self.get("/api/health", host="evil.example")[0], 403)
        code, body = self.get("/../../agentobs/server.py")
        self.assertNotIn(b"import", body)
        self.assertEqual(self.get("/api/session?key=nope")[0], 404)


class TestCLI(Base):
    def run_cli(self, *args):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.claude_root.parent), CODEX_HOME=str(self.codex_home), HERMES_HOME="/nonexistent", PI_CODING_AGENT_DIR="/nonexistent", XDG_DATA_HOME="/nonexistent", OPENCODE_DB="")
        return subprocess.run([sys.executable, str(SCRIPTS / "agents_report.py"), *args], capture_output=True, text=True, env=env, timeout=60)

    def test_commands(self):
        for args in (["doctor"], ["sessions"], ["show", fixtures.SID[:8]], ["context", fixtures.SID[:8], "--req", "1"],
                     ["report"], ["recommend"], ["report", "--json"]):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 0, (args, r.stderr))
        out = self.run_cli("report").stdout
        self.assertIn("Resuming long contexts", out)
        data = json.loads(self.run_cli("report", "--json").stdout)
        self.assertEqual(data["overview"]["sessions"], 2)

    def test_dashboard_starts_reuses_and_stops(self):
        state = Path(self.tmp.name) / "state" / "server.json"
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.claude_root.parent), CODEX_HOME=str(self.codex_home), HERMES_HOME="/nonexistent", PI_CODING_AGENT_DIR="/nonexistent", XDG_DATA_HOME="/nonexistent", OPENCODE_DB="", AGENTOBS_STATE=str(state))
        run = lambda *a: subprocess.run([sys.executable, str(SCRIPTS / "agents_report.py"), *a], capture_output=True, text=True, env=env, timeout=60)
        first = json.loads(run("dashboard", "--no-open", "--json", "--port", "0").stdout)
        self.assertEqual(first["server"], "started")
        again = json.loads(run("dashboard", "--no-open", "--json", "--session", fixtures.SID[:8], "--req", "1").stdout)
        self.assertEqual(again["server"], "reused")
        self.assertIn("?tab=context&req=1", again["url"])
        with urllib.request.urlopen(again["url"].split("#")[0] + "api/health") as r:
            self.assertEqual(json.loads(r.read())["app"], "agents-report")
        self.assertIn("Stopped", run("stop").stdout)

    def test_bind_falls_back_when_port_taken(self):
        from agentobs import server
        taken = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        try:
            srv = server.bind(taken.server_address[1])
            self.assertNotEqual(srv.server_address[1], taken.server_address[1])
            srv.server_close()
        finally:
            taken.server_close()

    def test_unknown_session(self):
        self.assertEqual(self.run_cli("show", "zzzz").returncode, 2)


class TestDeterminism(Base):
    """Same logs + pinned clock = byte-identical output, whatever the process (hash seed) or day it runs."""
    COMMANDS = (["sessions"], ["show", fixtures.SID[:8]], ["context", fixtures.SID[:8], "--req", "1"], ["report"], ["recommend"],
                ["brief", "--no-dashboard"], ["explain", fixtures.SID[:8], "--no-dashboard"], ["report", "--days", "30"], ["doctor"])

    def run_cli(self, args, seed, now="2026-10-15T12:00:00"):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.claude_root.parent), CODEX_HOME=str(self.codex_home), HERMES_HOME="/nonexistent",
                   PI_CODING_AGENT_DIR="/nonexistent", XDG_DATA_HOME="/nonexistent", OPENCODE_DB="", PYTHONHASHSEED=str(seed), TZ="UTC",
                   AGENTS_REPORT_NOW=now)
        r = subprocess.run([sys.executable, str(SCRIPTS / "agents_report.py"), *args], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, (args, r.stderr))
        return r.stdout

    def test_identical_across_runs(self):
        for args in self.COMMANDS:
            for fmt in ([], ["--json"]):
                with self.subTest(args=args + fmt):
                    self.assertEqual(self.run_cli(args + fmt, 1), self.run_cli(args + fmt, 2))

    def test_clock_is_pinned(self):
        self.assertIn("as of 2026-10-15 12:00", self.run_cli(["brief", "--no-dashboard"], 1))
        self.assertIn("Generated 2026-10-15 12:00", self.run_cli(["report"], 1))
        # the fixtures are from 2026-10-01: a pinned clock decides what --days keeps, not the day the test runs
        inside = json.loads(self.run_cli(["report", "--json", "--days", "60"], 1))["overview"]["sessions"]
        outside = json.loads(self.run_cli(["report", "--json", "--days", "60"], 1, now="2027-06-01"))["overview"]["sessions"]
        before = json.loads(self.run_cli(["report", "--json"], 1, now="2020-01-01"))["overview"]["sessions"]
        self.assertEqual((inside, outside, before), (2, 0, 0))

    def test_explain_ranks_findings_by_cost(self):
        d = json.loads(self.run_cli(["explain", fixtures.SID[:8], "--no-dashboard", "--json"], 1))
        usd = [f["usd"] for f in d["findings"] if f["usd"] is not None]
        self.assertEqual(usd, sorted(usd, reverse=True))
        self.assertIsNotNone(d["costliest_request"])
        self.assertTrue(d["text"].startswith(d["header"][0]))


class TestSkill(unittest.TestCase):
    def test_frontmatter_follows_agentskills_spec(self):
        import re
        skill = ROOT
        text = (skill / "SKILL.md").read_text()
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertTrue(m)
        fm = dict(re.findall(r"^([a-z-]+):\s*(.+)$", m.group(1), re.M))
        self.assertRegex(fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fm["name"]), 64)
        self.assertEqual(fm["name"], skill.name)
        self.assertTrue(0 < len(fm["description"]) <= 1024)
        if "compatibility" in fm:
            self.assertLessEqual(len(fm["compatibility"]), 500)
        self.assertLess(len(text.splitlines()), 500)
        for ref in re.findall(r"\]\(((?:references|scripts|assets)/[^)]+)\)", text):
            self.assertTrue((skill / ref).exists(), ref)


if __name__ == "__main__":
    unittest.main()


class TestNewAdapters(unittest.TestCase):
    """Pi and OpenCode fixtures follow their documented formats; Hermes mirrors the real ~/.hermes/state.db schema."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.pi = pi.parse(fixtures.build_pi(t / "pi"))[0]
        cls.oc = {s["key"]: s for s in opencode.parse(fixtures.build_opencode(t / "oc"))}
        cls.hm = {s["key"]: s for s in hermes.parse(fixtures.build_hermes(t / "hermes"))}

    def test_pi(self):
        s = self.pi
        self.assertEqual(s["key"], "pi:pi-0001")
        self.assertEqual((s["title"], s["cwd"], s["stats"]["bad_lines"]), ("Bug hunt", "/work/pi", 1))
        u = summarize(s)["usage"]
        self.assertEqual((u["input"], u["output"], u["cache_read"], u["cache_write_5m"]), (110, 25, 2200, 50))
        self.assertAlmostEqual(s["measured"]["cost_usd"], 0.012)
        ms = summarize(s)["model_stats"]["claude-sonnet-4-5"]
        self.assertEqual((ms["requests"], ms["tokens"], ms["unpriced"]), (2, 110 + 25 + 2200 + 50, False))
        call = next(e for e in s["events"] if e["kind"] == "tool_call")
        self.assertEqual((call["name"], call["is_error"], call["dur_ms"], call["output"]), ("bash", True, 1000, "boom"))
        self.assertEqual(s["compactions"][0]["pre_tokens"], 5000)

    def test_opencode(self):
        main, sub = self.oc["opencode:ses_main"], self.oc["opencode:ses_sub"]
        self.assertEqual(len(main["requests"]), 2)  # one per step-finish
        u = summarize(main)["usage"]
        self.assertEqual((u["input"], u["output"], u["reasoning"], u["cache_read"], u["cache_write_5m"]), (105, 32, 5, 1900, 10))
        self.assertEqual(main["measured"]["cost_usd"], 0.05)
        self.assertEqual(main["first_prompt"], "Refactor the parser")
        call = next(e for e in main["events"] if e["kind"] == "tool_call")
        self.assertEqual((call["name"], call["dur_ms"], call["output_chars"]), ("read", 500, 100))
        self.assertEqual(main["children"], ["opencode:ses_sub"])
        self.assertEqual(sub["parent_key"], "opencode:ses_main")
        self.assertEqual(len(sub["requests"]), 1)  # no step parts: message tokens are the call

    def test_opencode_unknown_schema_is_reported(self):
        import sqlite3
        d = Path(self.tmp.name) / "oc2"
        d.mkdir()
        con = sqlite3.connect(d / "opencode.db")
        con.execute("create table session_v2 (id text)")
        con.close()
        st = Store(roots={"opencode": str(d), "claude-code": "/nonexistent", "codex": "/nonexistent", "hermes": "/nonexistent", "pi": "/nonexistent"})
        st.summaries()
        self.assertEqual(len(st.errors), 1)
        self.assertIn("not recognised", st.errors[0]["error"])

    def test_hermes_aggregate_usage(self):
        main, sub = self.hm["hermes:s_main"], self.hm["hermes:s_sub"]
        sm = summarize(main)
        self.assertEqual(sm["n_requests"], 5)  # 3 + 2 calls over two usage rows
        self.assertFalse(sm["per_call_usage"])
        self.assertIsNone(sm["peak_context"])  # totals say nothing about one request's context
        u = sm["usage"]
        self.assertEqual((u["input"], u["output"], u["cache_read"], u["cache_write_5m"]), (320, 35, 3000, 100))
        self.assertEqual(sm["models"], {"claude-sonnet-4-5": 3, "claude-haiku-4-5": 2})
        self.assertEqual(main["system_prompt"], ["You are Hermes."])
        self.assertEqual(len(main["compactions"]), 1)
        call = next(e for e in main["events"] if e["kind"] == "tool_call")
        self.assertEqual((call["name"], call["output_chars"], call["dur_ms"]), ("terminal", 11, 2500))
        self.assertEqual(main["children"], ["hermes:s_sub"])
        self.assertEqual(sub["requests"][0]["aggregate"], 1)  # no usage rows: session totals
        c = context.inspect(main)
        self.assertEqual(c["basis"], "transcript")
        self.assertTrue(any("not per call" in n for n in c["notes"]))


class TestPresence(unittest.TestCase):
    """The background dashboard stops itself once no tab is open (fake clock, seconds)."""

    def setUp(self):
        from agentobs.server import Presence
        self.P = Presence

    def test_never_opened(self):
        p = self.P(0)
        self.assertFalse(p.should_stop(self.P.FIRST - 1))
        self.assertTrue(p.should_stop(self.P.FIRST + 1))

    def test_lifecycle(self):
        P = self.P
        p = P(0)
        p.update("a", True, 10)
        p.update("b", True, 11)
        p.update("a", False, 20)
        self.assertFalse(p.should_stop(20 + P.GRACE + 5))  # b still open
        p.update("b", True, 40)
        p.update("b", False, 50)
        self.assertFalse(p.should_stop(50 + P.GRACE - 1))  # a reload re-opens within the grace
        p.update("c", True, 50 + P.GRACE - 1)
        self.assertFalse(p.should_stop(80))
        p.update("c", False, 100)
        self.assertTrue(p.should_stop(100 + P.GRACE + 1))

    def test_tab_that_died_silently(self):
        P = self.P
        p = P(0)
        p.update("a", True, 10)
        self.assertFalse(p.should_stop(10 + P.STALE - 1))  # background tab, slow check-ins
        self.assertFalse(p.should_stop(10 + P.STALE + 1))  # just went stale: grace starts now
        self.assertTrue(p.should_stop(10 + P.STALE + P.GRACE + 1))


class TestActivity(unittest.TestCase):
    def test_activity_and_daily_cost_cover_every_agent(self):
        from datetime import datetime
        t = datetime(2026, 10, 3, 12).timestamp()
        mk = lambda key, agent, parent=None, cost=1.0: {"key": key, "agent": agent, "parent_key": parent, "started": t,
            "daily": {"2026-10-03": {"cost": cost, "tokens": 100, "requests": 4, "models": {f"m-{agent}": {"requests": 4, "cost": cost}}}}}
        sums = [mk("a", "hermes"), mk("b", "pi", cost=2.0), mk("c", "pi", parent="b", cost=0.5)]
        act = analyze.activity(sums)
        self.assertEqual(act["2026-10-03"], {"requests": 12, "sessions": 2, "tokens": 300, "cost": 3.5,  # subagent: no new session
                                             "models": {"m-hermes": 4, "m-pi": 8}})
