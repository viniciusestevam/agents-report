"""Command line: the interface the Agent Skill uses. Every command supports --json."""
import argparse
import json
import os
import sys
import time
from datetime import datetime

from . import analyze, context, pricing
from .store import Store, tree_cost
from .util import prompt_tokens


def _usd(x):
    return "—" if x is None else f"${x:,.2f}"


def _pct(x):
    return "—" if x is None else f"{x:.0%}"


def _models(models, n=1):
    """Most-used model(s) of a session, '+k' when there are more."""
    ms = sorted((models or {}).items(), key=lambda kv: -kv[1])
    return (", ".join(m for m, _ in ms[:n]) + (f" +{len(ms) - n}" if len(ms) > n else "")) if ms else "—"


def _when(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "—"


def _filter(sums, a):
    if getattr(a, "days", None):
        cutoff = time.time() - a.days * 86400
        sums = [s for s in sums if (s["started"] or 0) >= cutoff]
    if getattr(a, "agent", None):
        sums = [s for s in sums if s["agent"] == a.agent]
    if getattr(a, "here", False):
        cwd = os.path.realpath(os.getcwd())
        sums = [s for s in sums if s["cwd"] and os.path.realpath(s["cwd"]) == cwd]
    if getattr(a, "project", None):
        sums = [s for s in sums if s["project"] == a.project]
    # keep subagents of surviving parents
    keep = {s["key"] for s in sums if not s["parent_key"]}
    return [s for s in sums if not s["parent_key"] or s["parent_key"] in keep]


def resolve(store, ref):
    """Session key from a full key, an id prefix, or 'latest' (most recent; respects cwd with --here)."""
    sums = store.summaries()
    if ref in ("latest", "current"):
        cwd = os.path.realpath(os.getcwd())
        here = [s for s in sums if not s["parent_key"] and s["cwd"] and os.path.realpath(s["cwd"]) == cwd]
        pool = here or [s for s in sums if not s["parent_key"]]
        return max(pool, key=lambda s: s["ended"] or 0)["key"] if pool else None
    exact = [s["key"] for s in sums if s["key"] == ref]
    if exact:
        return exact[0]
    hits = [s["key"] for s in sums if s["id"].startswith(ref) or s["key"].split(":", 1)[1].startswith(ref)]
    if len(hits) > 1:
        hits = [h for h in hits if "/" not in h] or hits  # prefer the main session over its subagents
    return hits[0] if len(hits) == 1 else None


def cmd_sessions(st, a):
    sums = [s for s in _filter(st.summaries(), a) if not s["parent_key"]]
    sums.sort(key=lambda s: -(s["started"] or 0))
    sums = sums[: a.limit]
    if a.json:
        return print(json.dumps([{k: s[k] for k in ("key", "agent", "title", "project", "started", "models", "n_requests", "cost", "cache_hit_rate", "peak_context", "n_subagents")} for s in sums], default=str))
    print(f"{'started':16}  {'agent':11}  {'project':18}  {'model':20}  {'reqs':>5}  {'cost':>9}  {'cache':>5}  title")
    for s in sums:
        print(f"{_when(s['started']):16}  {s['agent']:11}  {(s['project'] or '—')[:18]:18}  {_models(s['models'])[:20]:20}  {s['n_requests']:>5}  "
              f"{_usd(s['cost']['estimated']):>9}  {_pct(s['cache_hit_rate']):>5}  {s['title'][:60]}  [{s['id'][:8]}]")


def cmd_show(st, a):
    key = resolve(st, a.session)
    if not key:
        print(f"No unique session matches {a.session!r}.", file=sys.stderr)
        return 2
    s = next(x for x in st.summaries() if x["key"] == key)
    if a.json:
        return print(json.dumps(s, default=str))
    c = s["cost"]
    print(f"{s['title']}\n{s['key']}\n")
    print(f"  agent        {s['agent']} {s['version'] or ''}   project {s['project'] or '—'}   branch {s['branch'] or '—'}")
    print(f"  when         {_when(s['started'])} → {_when(s['ended'])}  (active {round((s['active_ms'] or 0) / 60000)} min measured)")
    print(f"  models       {', '.join(f'{m} ×{n}' for m, n in s['models'].items()) or '—'}")
    print(f"  cost         estimated {_usd(c['estimated'])}  (+subagents {_usd(tree_cost(st.summaries(), key))})  measured {_usd(c['measured'])}"
          + (f"  unpriced: {', '.join(c['unpriced_models'])}" if c["unpriced_models"] else ""))
    u = s["usage"]
    print(f"  tokens       input {u['input']:,}  cache read {u['cache_read']:,}  cache write {u['cache_write_5m'] + u['cache_write_1h']:,}  output {u['output']:,}")
    print(f"  context      baseline {s['baseline_context'] or 0:,}  peak {s['peak_context'] or 0:,}  cache hit {_pct(s['cache_hit_rate'])}  compactions {s['n_compactions']}")
    print(f"  activity     {s['n_requests']} requests  {s['n_tool_calls']} tool calls ({s['n_tool_errors']} errors)  {s['n_subagents']} subagents")
    top = sorted(s["tools"].items(), key=lambda kv: -kv[1]["calls"])[:8]
    if top:
        print("  top tools    " + ", ".join(f"{n} ×{t['calls']}" for n, t in top))
    sig = s["signals"]
    for r in sig["cache_rebuilds"][:5]:
        print(f"  ! cache rebuild at request #{r['req']}: {r['write_tokens']:,} tokens ({r['cause']}) ≈ {_usd(r['waste_usd'])}")
    for x in sig["large_outputs"][:5]:
        print(f"  ! large {x['tool']} output {x['chars']:,} chars, carried ≈ {_usd(x['carry_usd'])}")


def cmd_context(st, a):
    key = resolve(st, a.session)
    if not key:
        print(f"No unique session matches {a.session!r}.", file=sys.stderr)
        return 2
    c = context.inspect(st.session(key, with_api_log=True), a.req)
    if a.json:
        return print(json.dumps(c if a.items else {k: v for k, v in c.items() if k != "items"}, default=str))
    r = c.get("request") or {}
    print(f"Context of request #{r.get('index')} of {c['requests']} ({r.get('model')}), basis: {c['basis']}")
    print(f"Measured prompt: {r.get('measured_prompt_tokens', 0):,} tokens" + (f" of {c['context_window']:,} window" if c.get("context_window") else ""))
    for g in c.get("groups", []):
        share = g["tokens"] / max(r.get("measured_prompt_tokens") or 1, 1)
        print(f"  {g['group']:22} {g['tokens']:>9,} tok  {share:>5.1%}  ({g['count']} items)")
    if c.get("unattributed"):
        print(f"  {'Unattributed':22} {c['unattributed']:>9,} tok")
    print("\nLargest items:")
    for x in sorted(c["items"], key=lambda x: -x["tokens"])[: a.top]:
        print(f"  {x['tokens']:>8,}  {x['group'][:18]:18}  {str(x['label'])[:80]}")
    for n in c.get("notes", []):
        print(f"note: {n}")


def report_md(sums, recs, title="Agent usage report"):
    o = analyze.overview(sums)
    lines = [f"# {title}", "", f"Generated {datetime.now():%Y-%m-%d %H:%M} from local transcripts. "
             "Values marked *measured* come from the agents' own logs; *estimated* values are computed (price × tokens).", ""]
    lines += ["## Summary", "", "| | Value |", "|---|---:|",
              f"| Sessions (+subagents) | {o['sessions']} (+{o['subagents']}) |",
              f"| API requests | {o['requests']:,} |",
              f"| Estimated cost | {_usd(o['cost_estimated'])} |",
              f"| Measured cost, {o['reconciliation']['sessions']} sessions that record it | {_usd(o['reconciliation']['measured'])} (estimate for the same sessions: {_usd(o['reconciliation']['estimated'])}) |",
              f"| Requests with no known price (excluded from cost) | {o['unpriced_requests']:,} |",
              f"| Cache hit rate (cache read ÷ prompt tokens) | {_pct(o['cache_hit_rate'])} |", ""]
    lines += ["| Agent | Sessions | Requests | Estimated | Measured | Unpriced models |", "|---|---:|---:|---:|---:|---|"]
    for ag, v in o["by_agent"].items():
        lines.append(f"| {ag} | {v['sessions']} | {v['requests']:,} | {_usd(v['cost']) + (' (partial)' if v['unpriced'] and v['cost'] else '')} | "
                     f"{_usd(v['measured']) if v['measured_sessions'] else '—'} | {', '.join(v['unpriced']) or '—'} |")
    lines += ["", "## Recommendations", ""]
    if not recs:
        lines.append("No issues detected by the deterministic rules.")
    for r in recs:
        sav = f" — potential saving {_usd(r['savings_usd'])} ({r['savings_basis']})" if r["savings_usd"] else ""
        lines += [f"### [{r['severity']}] {r['title']}{sav}", "", f"**Why:** {r['why']}", "", f"**Do:** {r['action']}", "", "Evidence:"]
        for e in r["evidence"][:5]:
            lines.append(f"- {e['title'][:60]} — {e['detail']}" + (f" (≈{_usd(e['usd'])})" if e.get("usd") else "") + (f" `{e['key']}`" if e.get("key") else ""))
        lines.append("")
    lines += ["## Most expensive sessions", "", "| Session | Agent | Model | Project | Estimated |", "|---|---|---|---|---:|"]
    for t in o["top_sessions"][:8]:
        lines.append(f"| {t['title'][:60]} | {t['agent']} | {_models(t.get('models'))} | {t['project'] or '—'} | {_usd(t['cost'])} |")
    lines += ["", "## By model", "", "| Model | Sessions | Requests | Tokens | Estimated |", "|---|---:|---:|---:|---:|"]
    for m, v in o["by_model"].items():
        lines.append(f"| {m} | {v['sessions']} | {v['requests']:,} | {v['tokens']:,} | {_usd(v['cost'])} |")
    lines += ["", "## Method & limits", "",
              f"- Prices: {pricing.SOURCE}. Unknown models are reported as unpriced, never $0.",
              "- Claude Code writes several log lines per API response; usage is counted once per response.",
              "- Savings are estimates from logged tokens and current prices; quality impact is not measured.", ""]
    return "\n".join(lines)


def cmd_report(st, a):
    sums = _filter(st.summaries(), a)
    recs = analyze.recommendations(sums)
    if a.json:
        return print(json.dumps({"overview": analyze.overview(sums), "recommendations": recs}, default=str))
    out = report_md(sums, recs)
    if a.out:
        open(a.out, "w").write(out)
        print(f"Wrote {a.out}")
    else:
        print(out)


def cmd_recommend(st, a):
    recs = analyze.recommendations(_filter(st.summaries(), a))
    if a.json:
        return print(json.dumps(recs, default=str))
    for r in recs:
        print(f"[{r['severity']}] {r['title']}" + (f"  (≈{_usd(r['savings_usd'])})" if r["savings_usd"] else ""))
        print(f"    do: {r['action']}")


def cmd_doctor(st, a):
    info = {"agents": st.detected_agents(), "python": sys.version.split()[0], "parse_errors": st.errors}
    try:
        from compression import zstd  # noqa: F401
        info["zstd"] = "stdlib"
    except ImportError:
        import shutil
        info["zstd"] = "cli" if shutil.which("zstd") else "missing (Codex .zst sessions unreadable)"
    sums = st.summaries()
    info["sessions"] = len(sums)
    info["bad_lines"] = sum(s["stats"].get("bad_lines", 0) for s in sums)
    info["unreadable"] = [s["path"] for s in sums if s["stats"].get("error")]
    if a.json:
        return print(json.dumps(info, default=str))
    for ag in info["agents"]:
        print(f"{ag['agent']:12} {'found' if ag['present'] else 'not detected':13} {ag['files']:>4} files  {ag['root'] or ''}  {ag.get('note', '')}")
    print(f"python {info['python']}, zstd: {info['zstd']}, sessions parsed: {info['sessions']}, malformed lines skipped: {info['bad_lines']}")
    for e in info["parse_errors"] + [{"path": p, "error": "unreadable"} for p in info["unreadable"]]:
        print(f"  error: {e['path']}: {e['error']}")


def _health(url):
    import urllib.request
    try:
        with urllib.request.urlopen(url + "api/health", timeout=2) as r:
            d = json.loads(r.read())
            return d if d.get("app") == "agents-report" else None
    except (OSError, ValueError):
        return None


def ensure_server(port=None, restart=False):
    """URL of a running, up-to-date dashboard; starts one in the background if needed."""
    import signal
    import subprocess
    from . import server
    try:
        st = json.loads(server.STATE.read_text())
    except (OSError, ValueError):
        st = None
    if st:
        h = _health(st["url"])
        if h and h["fingerprint"] == server.fingerprint() and not restart and (not port or st["port"] == port):
            return st["url"], "reused"
        if h and h.get("pid") == st.get("pid"):  # ours, but stale code or restart requested
            try:
                os.kill(st["pid"], signal.SIGTERM)
            except OSError:
                pass
            for _ in range(50):
                if not _health(st["url"]):
                    break
                time.sleep(0.1)
    log = server.STATE.with_name("server.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents_report.py")
    cmd = [sys.executable, entry, "serve", "--auto-stop"] + (["--port", str(port)] if port else [])
    old_pid = (st or {}).get("pid")
    with open(log, "ab") as lf:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=lf, stderr=lf, start_new_session=True)
    for _ in range(300):  # up to 30 s: the server parses all logs before it binds
        try:
            new = json.loads(server.STATE.read_text())
            if new.get("pid") == proc.pid and new.get("pid") != old_pid and _health(new["url"]):
                return new["url"], "started"
        except (OSError, ValueError):
            pass
        if proc.poll() is not None:
            raise SystemExit(f"Dashboard failed to start; see {log}")
        time.sleep(0.1)
    raise SystemExit(f"Dashboard did not come up in 30 s; see {log}")


def cmd_dashboard(st, a):
    from urllib.parse import quote
    url, how = ensure_server(a.port, a.restart)
    view = "#/" if a.view == "overview" else f"#/{a.view}"
    if a.session:
        key = resolve(st, a.session)
        if not key:
            print(f"No unique session matches {a.session!r}.", file=sys.stderr)
            return 2
        view = f"#/session/{quote(key, safe='')}" + (f"?tab=context&req={a.req}" if a.req is not None else "")
    target = url + view
    if a.json:
        print(json.dumps({"url": target, "server": how}))
    else:
        print(f"Dashboard {'running' if how == 'reused' else 'started'}: {target}")
    if not a.no_open:
        import webbrowser
        webbrowser.open(target)


def cmd_stop(st, a):
    import signal
    from . import server
    try:
        info = json.loads(server.STATE.read_text())
    except (OSError, ValueError):
        print("No dashboard is running.")
        return 0
    h = _health(info["url"])
    if h and h.get("pid") == info["pid"]:
        os.kill(info["pid"], signal.SIGTERM)
        print(f"Stopped dashboard at {info['url']}")
    else:
        server.STATE.unlink(missing_ok=True)
        print("No dashboard is running (cleared stale state).")


# Left out of the zip: caches, OS junk, the eval run history (dev noise), and zips.
PACKAGE_EXCLUDE = ("__pycache__", "*.pyc", ".DS_Store", "history.jsonl", "*.zip")


def cmd_package(st, a):
    """Zip this skill folder (scripts, prebuilt UI, references, tests, evals, docs) for import into any agent."""
    import fnmatch
    import zipfile
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    out = Path(a.out or f"{root.name}.zip").resolve()
    files = [f for f in sorted(root.rglob("*")) if f.is_file()
             and not any(fnmatch.fnmatch(part, pat) for part in f.relative_to(root).parts for pat in PACKAGE_EXCLUDE)]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, Path(root.name) / f.relative_to(root))
    print(f"Wrote {out} ({len(files)} files, {out.stat().st_size / 1024:.0f} KB). Unzip it into the agent's skills folder.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="agents-report", description="Local observability for AI coding agents.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, filters=True):
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        if filters:
            sp.add_argument("--days", type=float, help="only sessions started in the last N days")
            sp.add_argument("--agent", help="claude-code | codex | hermes | pi | opencode")
            sp.add_argument("--project", help="project directory name")
            sp.add_argument("--here", action="store_true", help="only sessions whose cwd is the current directory")
        return sp

    sp = sub.add_parser("serve", help="run the web UI in the foreground on 127.0.0.1")
    sp.add_argument("--port", type=int, help="preferred port (default 48765; any free port if taken)")
    sp.add_argument("--open", action="store_true", help="open the browser")
    sp.add_argument("--auto-stop", action="store_true", help="exit once no dashboard tab is open (used by `dashboard`)")
    sp = sub.add_parser("dashboard", help="open the visual dashboard (starts or reuses a background server)")
    sp.add_argument("--view", default="overview", choices=["overview", "sessions", "recommendations", "sources"])
    sp.add_argument("--session", help="open one session (id prefix or 'latest')")
    sp.add_argument("--req", type=int, help="with --session: open the context inspector at this request")
    sp.add_argument("--port", type=int, help="preferred port (default 48765; any free port if taken)")
    sp.add_argument("--restart", action="store_true", help="restart the background server")
    sp.add_argument("--no-open", action="store_true", help="print the URL without opening a browser")
    sp.add_argument("--json", action="store_true")
    sub.add_parser("stop", help="stop the background dashboard server")
    common(sub.add_parser("sessions", help="list sessions")).add_argument("--limit", type=int, default=30)
    sp = common(sub.add_parser("show", help="one session's summary and signals"), filters=False)
    sp.add_argument("session", help="key, id prefix, or 'latest'")
    sp = common(sub.add_parser("context", help="what one request put in the model's context"), filters=False)
    sp.add_argument("session")
    sp.add_argument("--req", type=int, help="request index (default: last)")
    sp.add_argument("--top", type=int, default=15)
    sp.add_argument("--items", action="store_true", help="include every item in --json output")
    sp = common(sub.add_parser("report", help="Markdown report with recommendations"))
    sp.add_argument("--out", help="write to file")
    common(sub.add_parser("recommend", help="evidence-backed recommendations"))
    common(sub.add_parser("doctor", help="check data sources and parsing"), filters=False)
    sub.add_parser("package", help="zip this skill for import into another agent").add_argument("--out", help="zip path (default ./agents-report.zip)")
    a = p.parse_args(argv)

    st = Store()
    if a.cmd == "serve":
        from .server import serve
        serve(a.port, st, a.open, auto_stop=a.auto_stop)
        return 0
    return {"dashboard": cmd_dashboard, "stop": cmd_stop, "sessions": cmd_sessions, "show": cmd_show, "context": cmd_context, "report": cmd_report,
            "recommend": cmd_recommend, "doctor": cmd_doctor, "package": cmd_package}[a.cmd](st, a) or 0
