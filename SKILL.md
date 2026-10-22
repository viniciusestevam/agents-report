---
name: agents-report
description: Analyze local AI coding agent sessions (Claude Code, Codex, Hermes, Pi, OpenCode) for cost, token usage, prompt-cache efficiency, context contents, tool calls, subagents and compaction, and recommend evidence-backed improvements. Use when the user asks what their agent usage costs, why a session was expensive or slow, what is filling the context window, how to cut token spend, to debug or review a past session, or to open the agent observability dashboard.
license: MIT (see LICENSE.txt)
compatibility: Python 3.10+ standard library only (3.14+ or the zstd CLI to read Codex logs). Reads ~/.claude, ~/.codex, ~/.hermes, ~/.pi and ~/.local/share/opencode on the local machine; makes no network calls.
metadata:
  version: "0.1.0"
---

# Agents Report

Deterministic analysis of the agent transcripts already on this machine, with a local visual
dashboard. The script does the counting; your job is to open the right view, read the output, and
explain it.

All commands: `python3 scripts/agents_report.py <command>` (run from this skill's directory, or use the
script's absolute path). Every command accepts `--json`. Filters: `--days N`, `--agent claude-code|codex|hermes|pi|opencode`,
`--project NAME`, `--here` (sessions started in the current directory). A session can be named by
its id prefix (`693b1d8d`) or `latest`.

## Show it visually first

The dashboard is the main way to read the results. **Every workflow starts by opening it** on the
view that answers the question:

```bash
python3 scripts/agents_report.py dashboard                                # overview
python3 scripts/agents_report.py dashboard --view recommendations
python3 scripts/agents_report.py dashboard --session latest               # one session: timeline, context, cost
python3 scripts/agents_report.py dashboard --session <id> --req N         # context inspector at request N
```

`dashboard` reuses the running dashboard server or starts one in the background (port 48765, or
any free port if that one is taken), opens the browser, and prints the URL. Always give the user that
URL. It returns immediately; don't wrap it in `&`. Use `--no-open` only when there is no browser (SSH, CI).

The server stops itself about 20 s after the user closes the last dashboard tab (10 min if no tab is
ever opened), so you don't need to clean up. Run `stop` only when the user asks to stop it now. To show
the dashboard again later, run `dashboard` again; it starts a new server if the old one has stopped.

| Command | Answers |
| --- | --- |
| `dashboard [--view …] [--session …] [--req N]` | Opens the visual view (starts the server if needed) |
| `report [--days 30] [--out report.md]` | Overall spend, cache efficiency, ranked recommendations with evidence |
| `sessions [--limit 30]` | Which sessions exist, their cost and context size |
| `show <session>` | One session: models, tokens, cost (estimated vs measured), cache rebuilds, large outputs |
| `context <session> [--req N] [--top 15]` | What one API request put in the context window, by contributor |
| `recommend` | Just the recommendations |
| `doctor` | Which agents were found, parse errors, zstd support |
| `package [--out file.zip]` | Zip this skill to install it in another agent |
| `stop` | Stop the dashboard now (it also stops itself once its last tab closes) |

## Workflows

**Invoked with no question, or "show me my usage"**: `dashboard`, then `report --days 30`. Reply with
the URL, the total, and the top three recommendations in a few lines; the page holds the detail.

**"What does my agent usage cost / how can I spend less?"**
1. `dashboard --view recommendations`, then `report --days 30` (or the period the user names).
2. Lead with the URL and the total, then the top two or three recommendations with evidence and savings.
3. Offer the specific change for each (see [references/recommendations.md](references/recommendations.md)).

**"Why was this session expensive / slow?"**
1. `sessions --here` or `sessions` to find it; `show <id>`.
2. `dashboard --session <id>`. If the context is large, `dashboard --session <id> --req N` on the
   request before the cost jumped (N from `show`), and `context <id> --req N` for the numbers.
3. Explain the cause in one sentence per finding, citing request numbers and token counts.

**"What is in my context?"** `dashboard --session latest --req <last>` and `context latest --here`.
Name the three largest contributors and what each one is (loaded skills, hook output, skills listing,
tool results, tool definitions, MCP tools).

## Rules

- **Quote numbers from the output; never compute or invent your own.** If a figure is not in the
  output, say it is unavailable.
- **Keep the basis.** Say "measured" for values read from logs (tokens, Claude Code's cost meter,
  timestamps) and "estimated" for computed ones (cost from list prices, context shares, savings).
  A dash or `null` means unavailable, not zero. Codex costs are unavailable unless the user adds a
  price file (see [references/metrics.md](references/metrics.md)).
- **Use the shipped dashboard.** `assets/ui/` is prebuilt and served as-is by `dashboard`. Never
  write your own HTML, charts or report page; link the user to the right dashboard view instead.
- **Recommendations are proposals.** Before editing the user's config (CLAUDE.md, AGENTS.md,
  settings.json hooks, MCP servers, subagent definitions), show the change and ask.
- Transcripts can contain secrets and personal data. Summarize; don't paste large raw excerpts,
  and never send them anywhere.

## More

- Metric definitions, cost method and data sources: [references/metrics.md](references/metrics.md)
- Every recommendation rule, its threshold, and the concrete fix: [references/recommendations.md](references/recommendations.md)
- Adding another agent (log format adapter): [references/adapters.md](references/adapters.md)
