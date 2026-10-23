#!/usr/bin/env python3
"""End-to-end evaluations against the real agent logs on this machine (plus the unit suite).

Each check returns (passed, metric, detail). Results go to evals/results/latest.json and are appended to
evals/results/history.jsonl; the run is compared with the previous one so regressions are visible.
Exit code 1 if any check fails.  Usage: python3 evals/run_evals.py [--quick]
"""
import ast
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the repository
SKILL = ROOT / "skills" / "agents-report"  # what ships: the skill / plugin
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
from agentobs.cli import PACKAGE_EXCLUDE  # noqa: E402

from agentobs import analyze, context, pricing  # noqa: E402
from agentobs.store import Store  # noqa: E402

RESULTS = ROOT / "evals" / "results"
checks = []


def check(name):
    def deco(fn):
        checks.append((name, fn))
        return fn
    return deco


STORE = Store()


@check("unit-tests")
def unit_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests")], capture_output=True, text=True, timeout=300)
    last = (r.stderr.strip().splitlines() or ["?"])[-1]
    ran = next((ln for ln in r.stderr.splitlines() if ln.startswith("Ran ")), "")
    return r.returncode == 0, ran, last


@check("parse-all-logs")
def parse_all():
    t = time.time()
    sums = STORE.summaries()
    cold = time.time() - t
    bad = sum(s["stats"].get("bad_lines", 0) for s in sums)
    unreadable = [s["path"] for s in sums if s["stats"].get("error")]
    files = len(STORE.files())
    mains = sum(1 for s in sums if not s["parent_key"])
    ok = not STORE.errors and not unreadable and mains >= files  # a database (Hermes, OpenCode) holds many sessions
    return ok, {"files": files, "sessions": mains, "subagents": len(sums) - mains, "bad_lines": bad, "cold_s": round(cold, 2)}, \
        f"errors={STORE.errors[:3]} unreadable={unreadable[:3]}"


@check("pricing-reproduces-claude-meter")
def pricing_matches_meter():
    """Re-price Claude Code's own per-model token totals with our table; must equal its costUSD."""
    errs, n = [], 0
    for s in STORE.summaries():
        if s["parent_key"] or s["agent"] != "claude-code":
            continue
        full = STORE.session(s["key"], with_api_log=False)
        mu = (full.get("measured") or {}).get("model_usage") or {}
        # the meter has no TTL split: use the logged ratio, per model, across the session and its subagents
        reqs = list(full["requests"]) + [r for c in s["children"] for r in STORE.session(c, with_api_log=False)["requests"]]
        for model, v in mu.items():
            logged_1h = sum(r["usage"]["cache_write_1h"] for r in reqs if r["model"] == model)
            logged_w = logged_1h + sum(r["usage"]["cache_write_5m"] for r in reqs if r["model"] == model)
            share_1h = logged_1h / logged_w if logged_w else 1.0
            if not v.get("costUSD") or pricing.rates(model) is None:
                continue
            w = v["cacheCreationInputTokens"]
            u = {"input": v["inputTokens"], "output": v["outputTokens"], "cache_read": v["cacheReadInputTokens"],
                 "cache_write_1h": round(w * share_1h), "cache_write_5m": w - round(w * share_1h), "reasoning": 0}
            ours = pricing.cost(model, u, web_searches=v.get("webSearchRequests") or 0)
            errs.append(abs(ours - v["costUSD"]) / v["costUSD"])
            n += 1
    if not n:
        return True, "no cost-state records", "skipped"
    worst = max(errs)
    return worst < 0.01, {"model_rows": n, "max_rel_error": round(worst, 5), "median_rel_error": round(statistics.median(errs), 6)}, ""


@check("logged-cost-never-exceeds-meter")
def no_double_counting():
    """If usage were double counted, the logged estimate would exceed Claude Code's meter."""
    sums = STORE.summaries()
    by = {s["key"]: s for s in sums}
    over, ratios = [], []
    for s in sums:
        if s["parent_key"] or s["cost"]["measured"] in (None, 0):
            continue
        est = (s["cost"]["estimated"] or 0) + sum(by[c]["cost"]["estimated"] or 0 for c in s["children"] if c in by)
        ratios.append(est / s["cost"]["measured"])
        if est > s["cost"]["measured"] * 1.02:
            over.append((s["id"][:8], round(est, 3), round(s["cost"]["measured"], 3)))
    return not over, {"sessions": len(ratios), "median_coverage": round(statistics.median(ratios), 4) if ratios else None,
                      "min_coverage": round(min(ratios), 4) if ratios else None}, f"over meter: {over[:5]}"


@check("codex-tokens-match-thread-db")
def codex_tokens():
    rows = []
    for s in STORE.summaries():
        if s["agent"] != "codex" or s["cost"]["measured_tokens"] is None:
            continue
        u = s["usage"]
        logged = u["input"] + u["cache_read"] + u["cache_write_5m"] + u["cache_write_1h"] + u["output"]
        rows.append((s["id"][:8], logged, s["cost"]["measured_tokens"]))
    if not rows:
        return True, "no codex threads", "skipped"
    bad = [r for r in rows if r[1] != r[2]]
    return not bad, {"threads": len(rows), "mismatched": len(bad)}, str(bad[:3])


@check("unavailable-never-zero")
def unavailable():
    bad = []
    for s in STORE.summaries():
        for r in STORE.session(s["key"])["requests"] if s["cost"]["unpriced_models"] else []:
            if pricing.rates(r["model"]) is None and r["cost"] is not None:
                bad.append(s["key"])
        if s["cost"]["unpriced_models"] and not s["cost"]["complete"] and s["cost"]["estimated"] == 0 and s["n_requests"]:
            bad.append(s["key"])
    o = analyze.overview(STORE.summaries())
    for a, v in o["by_agent"].items():
        if v["unpriced"] and v["cost"] == 0:
            bad.append(a)
    return not bad, {"violations": len(bad)}, str(bad[:3])


@check("context-inspector")
def context_eval():
    exact = complete = transcript = 0
    ratios, sum_err, slow = [], 0, 0.0
    for s in STORE.summaries():
        if not s["n_requests"]:
            continue
        full = STORE.session(s["key"], with_api_log=True)
        n = len(full["requests"])
        for i in sorted({0, n // 2, n - 1}):
            t = time.time()
            c = context.inspect(full, i)
            slow = max(slow, time.time() - t)
            if c["basis"] == "exact-request":
                exact += 1
                if c["complete"]:
                    complete += 1
                    ratios.append(c["calibration"])
                    total = sum(g["tokens"] for g in c["groups"])
                    sum_err = max(sum_err, abs(total - c["request"]["measured_prompt_tokens"]) / max(1, c["request"]["measured_prompt_tokens"]))
            else:
                transcript += 1
            assert c["groups"] or c["basis"] == "unavailable", s["key"]
    rate = complete / exact if exact else None
    ok = (rate is None or rate >= 0.8) and (not ratios or 1.0 <= min(ratios) and max(ratios) <= 2.5) and sum_err < 0.01 and slow < 2
    return ok, {"exact": exact, "exact_complete_rate": round(rate, 3) if rate is not None else None, "transcript": transcript,
                "calibration_range": [min(ratios), max(ratios)] if ratios else None, "max_sum_error": round(sum_err, 4),
                "slowest_s": round(slow, 3)}, ""


@check("recommendations-grounded")
def recs_grounded():
    sums = STORE.summaries()
    keys = {s["key"] for s in sums}
    recs = analyze.recommendations(sums)
    problems = []
    for r in recs:
        if not (r["evidence"] and r["action"] and r["why"] and r["savings_basis"]):
            problems.append(r["id"] + ": missing field")
        for e in r["evidence"]:
            if e.get("key") and e["key"] not in keys:
                problems.append(f"{r['id']}: dangling key {e['key']}")
        if r["savings_usd"] is not None and r["savings_usd"] < 0:
            problems.append(r["id"] + ": negative savings")
    return not problems, {"recommendations": len(recs), "ids": [r["id"] for r in recs],
                          "estimated_savings_usd": round(sum(r["savings_usd"] or 0 for r in recs), 2)}, str(problems[:5])


@check("http-e2e-every-session")
def http_e2e():
    from agentobs import server
    server.Handler.store = STORE
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fails, times = [], []

    def get(p):
        t = time.time()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{p}", timeout=30) as r:
                body = r.read()
                times.append(time.time() - t)
                return r.status, body
        except urllib.error.HTTPError as e:
            with e:
                return e.code, b""

    try:
        for p in ("/", "/app.js", "/style.css", "/api/overview", "/api/sessions", "/api/sessions?days=7", "/api/recommendations", "/api/sources"):
            code, _ = get(p)
            if code != 200:
                fails.append((p, code))
        for s in STORE.summaries():
            k = urllib.parse.quote(s["key"])
            for p in (f"/api/session?key={k}", f"/api/context?key={k}"):
                code, body = get(p)
                if code != 200:
                    fails.append((p, code))
                elif p.startswith("/api/session"):
                    d = json.loads(body)
                    if sum(r.get("aggregate") or 1 for r in d["requests"]) != s["n_requests"]:
                        fails.append((p, "request count mismatch"))
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"Host": "attacker.test"})
        try:
            urllib.request.urlopen(req)
            fails.append(("host check", "not rejected"))
        except urllib.error.HTTPError as e:
            e.close()
            if e.code != 403:
                fails.append(("host check", e.code))
    finally:
        srv.shutdown()
        srv.server_close()
    return not fails, {"requests": len(times), "p95_s": round(sorted(times)[int(len(times) * 0.95) - 1], 3) if times else None,
                       "max_s": round(max(times), 3) if times else None}, str(fails[:5])


@check("ui-is-local-only")
def ui_local():
    import re
    ui = SKILL / "assets" / "ui"
    ext = []
    for f in ui.iterdir():
        for m in re.findall(r"""(?:src|href)=["'](https?:)?//[^"']+|fetch\(["']https?://|url\(["']?https?://""", f.read_text()):
            ext.append((f.name, m))
    node = shutil.which("node")
    syntax = subprocess.run([node, "--check", str(ui / "app.js")], capture_output=True, text=True).returncode == 0 if node else None
    return not ext and syntax is not False, {"external_refs": len(ext), "js_syntax": syntax}, str(ext[:3])


@check("deterministic-on-real-logs")
def deterministic_real():
    """Freeze a copy of this machine's logs, pin the clock, run the answer commands twice with different hash seeds:
    the output must be byte-identical. (Live logs keep growing, so they can't be compared in place.)"""
    from agentobs.adapters import claude_code, codex, hermes
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        env = {"AGENTS_REPORT_CLAUDE_PROJECTS": str(d / "claude"), "CODEX_HOME": str(d / "codex"), "HERMES_HOME": str(d / "hermes"),
               "PI_CODING_AGENT_DIR": "/nonexistent", "XDG_DATA_HOME": "/nonexistent", "OPENCODE_DB": "",
               "AGENTS_REPORT_NOW": "2026-10-01T00:00:00", "TZ": "UTC"}
        if claude_code.ROOT.is_dir():
            shutil.copytree(claude_code.ROOT, d / "claude")
        if codex.ROOT.is_dir():
            shutil.copytree(codex.ROOT, d / "codex" / "sessions")
        if hermes.ROOT.is_dir():
            (d / "hermes").mkdir()
            for f in hermes.ROOT.glob("state.db*"):
                shutil.copy2(f, d / "hermes" / f.name)
        run = lambda args, seed: subprocess.run([sys.executable, str(SCRIPTS / "agents_report.py"), *args], capture_output=True, text=True, timeout=300,
                                                env={**__import__("os").environ, **env, "PYTHONHASHSEED": str(seed)})
        top = json.loads(run(["report", "--json"], 0).stdout)["overview"]["top_sessions"]
        cmds = [["report", "--json"], ["brief", "--no-dashboard"], ["sessions", "--json", "--limit", "200"], ["recommend", "--json"]]
        if top:
            cmds += [["explain", top[0]["key"], "--no-dashboard", "--json"], ["show", top[0]["key"], "--json"]]
        diff = []
        for c in cmds:
            r1, r2 = run(c, 1), run(c, 2)
            if r1.returncode or r2.returncode or r1.stdout != r2.stdout:
                diff.append(f"{' '.join(c)}: rc {r1.returncode}/{r2.returncode} {r1.stderr[-200:]}")
    return not diff, {"commands": len(cmds), "differing": len(diff)}, "; ".join(diff)


@check("skill-portable")
def skill_portable():
    """Copy the skill alone to a temp dir and run it isolated (-I) from there; check 3.10 syntax compatibility."""
    bad_syntax = []
    for f in SCRIPTS.rglob("*.py"):
        try:
            ast.parse(f.read_text(), feature_version=(3, 10))
        except SyntaxError as e:
            bad_syntax.append(f"{f.name}:{e.lineno}")
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / "agents-report"
        shutil.copytree(SKILL, dst, ignore=shutil.ignore_patterns(*PACKAGE_EXCLUDE))  # exactly what `package` ships
        r = subprocess.run([sys.executable, "-I", str(dst / "scripts" / "agents_report.py"), "doctor", "--json"], capture_output=True, text=True, cwd=d, timeout=120)
        ok_run = r.returncode == 0 and json.loads(r.stdout)["sessions"] == len(STORE.summaries())
        r2 = subprocess.run([sys.executable, "-I", str(dst / "scripts" / "agents_report.py"), "report", "--days", "3650"], capture_output=True, text=True, cwd=d, timeout=120)
        ok_report = r2.returncode == 0 and "## Recommendations" in r2.stdout
    lines = len((SKILL / "SKILL.md").read_text().splitlines())
    return not bad_syntax and ok_run and ok_report, {"py310_syntax_errors": len(bad_syntax), "isolated_doctor": ok_run,
                                                     "isolated_report": ok_report, "skill_md_lines": lines}, f"{bad_syntax[:3]} {r.stderr[-300:]}"


def main():
    quick = "--quick" in sys.argv
    RESULTS.mkdir(parents=True, exist_ok=True)
    prev = None
    hist = RESULTS / "history.jsonl"
    if hist.exists():
        lines = hist.read_text().splitlines()
        prev = json.loads(lines[-1]) if lines else None
    out = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "checks": {}}
    failed = 0
    for name, fn in checks:
        if quick and name in ("unit-tests", "http-e2e-every-session"):
            continue
        t = time.time()
        try:
            ok, metric, detail = fn()
        except Exception as e:  # a crashing check is a failing check
            ok, metric, detail = False, None, f"{type(e).__name__}: {e}"
        out["checks"][name] = {"pass": ok, "metric": metric, "detail": detail if not ok else "", "s": round(time.time() - t, 2)}
        was = (prev or {}).get("checks", {}).get(name, {}).get("pass")
        flag = " (REGRESSION)" if was and not ok else " (fixed)" if was is False and ok else ""
        print(f"{'PASS' if ok else 'FAIL'}  {name:34} {json.dumps(metric, default=str)[:150]}{flag}")
        if not ok:
            failed += 1
            print(f"      {detail}")
    out["summary"] = {"passed": len(out["checks"]) - failed, "failed": failed}
    (RESULTS / "latest.json").write_text(json.dumps(out, indent=1, default=str))
    with hist.open("a") as f:
        f.write(json.dumps(out, default=str) + "\n")
    print(f"\n{out['summary']['passed']}/{len(out['checks'])} checks passed. Results: evals/results/latest.json")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
