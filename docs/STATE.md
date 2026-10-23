# Agents Report — project state

Resume point for any agent picking this up. Update **Progress**, **Known limitations** and **Next steps**
at every milestone. Verify with `python3 evals/run_evals.py` before and after any change.

## Objective
Local-first observability for AI coding agents (Claude Code, Codex, Hermes, Pi, OpenCode; others via adapters): Agents View,
Context Inspector, Cost & Performance analytics, evidence-based Recommendations, packaged as a portable
Agent Skill (agentskills.io spec) that also serves the web UI.

## Acceptance criteria — status (evidence: docs/EVALS.md, evals/results/latest.json)
1. ✅ Parses 100% of local Claude Code + Codex transcripts; malformed lines counted, not fatal.
2. ✅ Usage deduplicated per API response (eval: logged estimate never exceeds Claude's meter).
3. ✅ Pricing reproduces Claude Code's measured cost (max error 0.04% over 53 model rows).
4. ✅ Unknown prices/data are `null` + reason, never 0.
5. ✅ Context Inspector rebuilds the exact request (100% complete on sampled exact requests); transcript fallback labelled.
   Layout: 400-square grid = the whole context window (like Claude Code's /context): colored = used, by 7 categories; rest = free (`context.CATEGORIES`), legend nests groups; below, every item
   as a one-line row that opens to its full content (`/api/context?item=N`), grouped per message as sent or ranked by size, full-text search (`find=`).
   Thinking blocks with no logged text show as "Hidden thinking" (only the encrypted signature is logged; its chars are what's counted).
6. ✅ Every recommendation carries evidence, an action and a savings basis.
7. ✅ Web UI (overview with a GitHub-style activity heatmap (whole history) and spend per day stacked by agent, sessions with an interactive timeline (lanes per project labelled with sessions · cost and a link that filters to it, sortable Recent/Cost, bars packed ≤ 3 rows a lane with titles when wide, spend-per-day minimap with a draggable/resizable window, zoom/pan/keys, click to open) and a List / By project table (collapsible project rows with totals, same sort as the timeline), agent icons, session detail opening on Trace, then timeline/context/cost/tools/subagents (trace = span tree like an APM waterfall: session → prompts → model calls / tools / subagents (lazy-loaded inline), tinted bars with duration · cost, SLOWEST/PRICIEST/ERROR badges, KPI strip incl. subagents, hover clock cursor, drag-to-zoom, double-click to zoom to a span, details side panel (bottom sheet ≤1100 px), search, arrow keys, active-time vs wall-clock axis (active cuts idle gaps > 20 s), Live badge + 5 s refresh while the log was written < 2 min ago), recommendations, data sources) on 127.0.0.1, no network, no build; verified in browser light/dark, desktop/390 px.
8. ✅ Skill passes the frontmatter rules and runs copied alone under `python3 -I`; used successfully by Claude Code (headless) and Codex (exec).
9. ✅ 41 fixture tests + 12 end-to-end evals pass (incl. output determinism).
10. ✅ Visual-first: `dashboard` opens the UI on a dedicated port (48765, any free port if taken), reuses a healthy dashboard server, refuses to reuse a foreign one, restarts when code changes; the skill opens it in every workflow. Auto-stop: each tab checks in every 15 s and sends a goodbye beacon on close; the background server exits 20 s after the last tab is gone (150 s if a tab dies silently, 10 min if none ever opens), and the page shows a restart hint if the server is gone.

## Decisions
- **Installable command (2026-10-22).** `pyproject.toml` (hatchling) builds the `agents-report` package straight from
  the skill's `scripts/agentobs/` and bundles `assets/ui/` as `agentobs/ui`, so `uv tool install` / `pipx install`
  give an `agents-report` command with no copy of the code in the repo. The server finds the UI in either place and
  starts its background copy with `python -c` from the same code. `__version__` in `agentobs/__init__.py` is the
  version; a test keeps SKILL.md and plugin.json equal to it. CI installs with uv and pipx on Linux and macOS.
- **Deterministic answers (2026-10-22).** The scripts gather data, rank findings and write the reply; the agent picks one
  command per question (`brief`, `explain`, `context`, `show`, `report`) and relays it. Same logs → byte-identical output:
  tested across processes with different hash seeds (unit test on fixtures, eval on a frozen copy of the real logs).
  `--now`/`AGENTS_REPORT_NOW` pins the clock; reports leave out sessions that started after it.
- **Python stdlib only.** Zero deps = portable skill. Codex `.jsonl.zst` via `compression.zstd` (3.14+) or the `zstd` CLI.
- **Repository layout (2026-10-22, modeled on plannotator).** `.agents/skills/agents-report/` is the product: the skill (SKILL.md,
  scripts, prebuilt UI, references) and the Claude Code plugin (`.claude-plugin/plugin.json`); `package` zips it. The
  repository root holds the README, `.claude-plugin/marketplace.json` (lists the plugin), `.github/` (README images,
  CI, issue templates), `tests/`, `evals/`, `tools/` (synthetic demo data, screenshot recorder) and these docs.
  Paths in this file are relative to `.agents/skills/agents-report/` unless they start with tests/, evals/, tools/ or docs/.
- **Vanilla HTML/CSS/JS UI**, own SVG charts, system fonts (no font downloads), serif only for titles. Design follows the design-taste-frontend app-screen rules, except one deliberate deviation: a warm neutral ground with a clay data hue (that skill bans cream+terracotta; the user asked for an Anthropic-like warmth). Accent used on data only.
- **Facts vs estimates:** every number labelled measured / estimated / unavailable.
- **Pricing:** Claude rates from Anthropic's claude-api skill (cached 2026-10-06). No verified OpenAI prices → Codex cost unavailable unless `~/.config/agents-report/prices.json`.
- **Codex token semantics:** cached and cache-write tokens are subsets of input; reasoning subset of output. Verified exactly against Codex's thread DB.
- **Recommendations are deterministic rules**; interpretation is left to the agent using the skill, which is told to quote only tool output.
- **"Armis" was a misspelling of "Hermes"** (now supported); removed.
- **"Pice Tech" patterns:** no verifiable source found (web search 2026-10-22); not applied. Applied: agentskills.io spec, Anthropic prompt-caching/cost guidance, Matt Pocock's skills (feedback loops, small composable skills, verification before done).

## Data sources (verified)
- Claude Code: `~/.claude/projects/<proj>/<session>.jsonl` + `<session>/subagents/agent-*.jsonl` + `.meta.json`.
  `assistant` (usage once per message.id), `user` (tool_result), `attachment.rendered` (exact injected text),
  `system` (compact_boundary, turn_duration), `cost-state` (meter), `api-request`/`-shape`/`-blob`
  (messages = base.messages[:keep] + tail; unstored: previous response, some tool results, typed prompts → rebuilt from transcript).
- Hermes (verified on real data, 39 sessions): `~/.hermes/state.db` read-only. `sessions` (parent_session_id = subagent),
  `messages` (user/assistant/tool, tool_calls JSON, reasoning), `session_model_usage` = token totals per (session, model, task)
  with api_call_count: no per-call usage, so each row is an aggregate request (`aggregate=N`); per-request views (context
  chart, peak context, cache-rebuild signals) skip aggregates; the session page shows a per-model totals table instead.
- Pi (from pi.dev session-format docs v3, fixture-tested, no local data): `~/.pi/agent/sessions/--<cwd>--/*.jsonl`;
  assistant `usage` per call (input/output/cacheRead/cacheWrite, cost.total → measured).
- OpenCode (from source v1.19.4, fixture-tested, no local data): `~/.local/share/opencode/opencode*.db` (`OPENCODE_DB`);
  tables session/message/part; `step-finish` part = one call. The dev-branch `session_v2` schema is reported as unrecognised.
- Claude Code logs can be read from another folder with `AGENTS_REPORT_CLAUDE_PROJECTS` (used for demo data; unlike `CLAUDE_CONFIG_DIR` it doesn't move Claude Code's own config).
- Codex: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.zst`; `token_usage_record` per response (dedupe by response_id);
  `task_complete` duration + TTFT; titles/tokens from `state_*.sqlite` (read-only).

## Known limitations
- Claude Code's meter includes calls not in transcripts (titles, classifiers, background work): per-request analysis is a lower bound (median 97% coverage, min 70%).
- Sessions from Claude Code versions before `api-request` logging (and all Codex sessions) use the transcript basis: approximate, tool definitions unknown for Codex.
- Transcript-basis sessions show item text as clipped at parse time (1.5–4k chars); exact-request sessions show it in full.
- Whether old thinking signatures cost input tokens is unverified; their share is a char-based estimate.
- Context tab at 390 px width not re-checked after the grid redesign (CSS rules added, not viewed).
- Pi and OpenCode adapters are untested on real files; OpenCode reasoning tokens are added to output (unverified).
- Hermes token buckets assumed disjoint (cache_read ≫ input in real data); reasoning treated as part of output.
- Agent icons are original glyphs, not vendor logos.
- Image/document token cost is not derivable from logs (shown as 0 chars, falls into unattributed/calibration).
- Latency per request is estimated from log timestamps; Codex TTFT is measured per turn only.
- No price data for OpenAI models is bundled.
- Python 3.10 compatibility is checked by syntax only (no 3.10 interpreter on this machine).
- Browser and agent-CLI checks are manual (documented in EVALS.md), not in the eval script.
- Trace: model-call start is estimated (end of the previous logged event); Hermes has no per-call timing, so its trace shows tools only. Unpriced spans show no cost (never $0).
- Timeline shows the first 300 events with "show more"; very large sessions load the whole event list (~0.8 MB JSON for 290 requests).

## Next steps (ranked)
1. Price file for OpenAI models once a verified source is available; then Codex cost becomes estimated.
2. Rule: MCP servers whose tools are listed but never called (needs per-request tool list → exact basis only).
3. Persist summaries to a disk cache if cold parse exceeds ~5 s (currently 1.0 s for 250 MB).
4. Additional adapters (Cursor, Gemini CLI) when their local formats are available.
