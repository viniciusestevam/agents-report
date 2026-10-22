# Agents Report

Local-first observability for AI coding agents. It reads the session logs Claude Code, Codex, Hermes, Pi and OpenCode already
write on your machine and shows where tokens, money and time went, what was actually in the model's
context, and what to change. It runs as a web UI and as a portable Agent Skill, using only the Python
standard library. Nothing leaves your machine.

```bash
python3 scripts/agents_report.py dashboard        # opens the web UI (http://127.0.0.1:48765)
python3 scripts/agents_report.py report --days 30 # Markdown report with recommendations
```

Paths below are relative to this folder.

## What it shows

- **Overview**: spend per day, cache hit rate, tokens, top sessions, spend by project, tool usage, and the
  recommendations with the most estimated savings.
- **Sessions**: an interactive timeline (lanes per project, zoom, pan, keyboard, click to open) and a searchable
  list of every session across agents, with subagent cost rolled into the parent.
- **Session detail**:
  - *Context per request*: one column per API call, split into cache read, cache write and uncached
    input, with compactions and cache rebuilds visible at a glance.
  - *Timeline*: prompts, replies, thinking, tool calls with full input/output, hooks, injected
    context, errors, links to subagent sessions.
  - *Cost & latency*: per request and per model, next to Claude Code's own meter.
  - *Tools* and *Subagents* tabs.
- **Context Inspector**: rebuilds the exact API request Claude Code sent (system prompt blocks, every
  tool definition, MCP tools, loaded skills, hook output, skill/agent listings, messages) and splits the
  measured prompt total across them. This goes further than `/context`: it works on any past request,
  and it shows what was injected around your messages.
- **Recommendations**: deterministic rules, each with evidence (session, request, measured values), an
  estimated saving, and a concrete change.

Every number carries its basis: **measured** (read from logs), **estimated** (computed), or
**unavailable** (shown as a dash, never as zero).

## Install

This folder is the whole product: instructions, code, the prebuilt dashboard, tests and evals. Nothing
to install or build; it needs Python 3.10+.

```bash
python3 scripts/agents_report.py package          # writes agents-report.zip (no caches, no eval history)
```

Unzip it into your agent's skills folder:

| Agent | Skills folder |
| --- | --- |
| Claude Code | `~/.claude/skills/` (or `<project>/.claude/skills/`) |
| Codex and other agentskills.io agents | `~/.agents/skills/` (or `<project>/.agents/skills/`) |

```bash
unzip agents-report.zip -d ~/.claude/skills/
```

Keep the folder name `agents-report`: it must match `name` in `SKILL.md`. Then ask your agent things
like "what did my agents cost this week?", "why was yesterday's session expensive?" or "what's filling
my context?".

The dashboard is prebuilt (`assets/ui/`: plain HTML, CSS and JS) and served as-is by the bundled local
server, so nothing is generated or rebuilt when the skill runs. A running server is reused across calls
and restarted only when the skill's code changes.

## CLI

| Command | |
| --- | --- |
| `dashboard [--view V] [--session ID] [--req N]` | Opens the web UI; starts or reuses a background server on 127.0.0.1:48765 (any free port if taken). The server stops itself ~20 s after the last dashboard tab closes |
| `stop` / `serve` | Stop the background server now / run it in the foreground until Ctrl+C |
| `report [--days N] [--out file.md] [--json]` | Summary + recommendations |
| `sessions [--here] [--agent A] [--project P]` | List sessions |
| `show <id-prefix\|latest>` | One session: cost, tokens, context, signals |
| `context <id> [--req N]` | Context breakdown for one request |
| `recommend`, `doctor` | Recommendations only; data-source check |
| `package [--out file.zip]` | Zip this folder for import into another agent |

## Pricing

Claude prices are Anthropic's published rates (`scripts/agentobs/pricing.py`, dated). The evals show
they reproduce Claude Code's own cost meter to within 0.04%. Codex logs no cost and no OpenAI price list
is bundled, so Codex cost (and Hermes cost on OpenAI models) shows as *unavailable* until you add `~/.config/agents-report/prices.json`
(format in `references/metrics.md`).

## Layout

```
agents-report/
  SKILL.md                 agent instructions (agentskills.io format); the only file an agent loads up front
  README.md                this file (for people)
  LICENSE.txt
  scripts/agents_report.py   CLI entry
  scripts/agentobs/        adapters (claude_code, codex, hermes, pi, opencode), store, analyze, context, pricing, server, cli
  assets/ui/               prebuilt dashboard: index.html, style.css, app.js (no build step, no external requests)
  references/              metrics, recommendation rules, adapter contract (loaded by the agent on demand)
  tests/                   unit + integration tests on synthetic fixtures with hand-computed answers
  evals/run_evals.py       end-to-end evals on the real logs of this machine; results/ keeps the latest run
  docs/STATE.md            project state, decisions, limitations, next steps (resume point)
  docs/EVALS.md            evaluation method and results
```

## Verify

```bash
python3 -m unittest discover -s tests  # unit + integration tests, ~1 s
python3 evals/run_evals.py             # 11 checks against the real logs on this machine
```

## Privacy and security

Reads `~/.claude`, `~/.codex`, `~/.hermes/state.db`, `~/.pi/agent/sessions` and `~/.local/share/opencode/opencode*.db` (SQLite stores are opened read-only). The server binds to
127.0.0.1, rejects other Host headers (DNS rebinding), serves only its own UI files, and sets a strict
Content-Security-Policy. The UI loads no external fonts, scripts or images.

## Limits

See `docs/STATE.md` → Known limitations.
