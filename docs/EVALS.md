# Evaluations

Run `python3 evals/run_evals.py` (add `--quick` to skip the unit suite and HTTP sweep). Each run is
written to `evals/results/latest.json` and appended to `evals/results/history.jsonl`; a check that
passed last run and fails now prints `REGRESSION`.

## Checks

| Check | What it proves | Pass condition |
| --- | --- | --- |
| unit-tests | Parsers, pricing, context rebuild, signals, rules, server security, CLI, skill spec — on fixtures with hand-computed answers | all pass |
| parse-all-logs | Every local transcript parses; malformed lines are counted, not fatal | 0 errors, sessions = files |
| pricing-reproduces-claude-meter | Our price table × Claude Code's own per-model token totals = its own costUSD | max relative error < 1% |
| logged-cost-never-exceeds-meter | No double counting (Claude logs repeat usage per content block) | estimate ≤ meter × 1.02 for every session |
| codex-tokens-match-thread-db | Codex normalization (cached ⊂ input) loses nothing | logged total = thread `tokens_used`, exactly |
| unavailable-never-zero | Unpriced models are `null`, never $0 | 0 violations |
| context-inspector | Exact request reconstruction is complete; calibrated split sums to the measured total | ≥80% complete, ratio in [1.0, 2.5], sum error < 1%, < 2 s |
| recommendations-grounded | Every rule has why/action/basis; every evidence key resolves to a real session | 0 problems |
| http-e2e-every-session | Every session's detail and context endpoints return 200 with consistent request counts; foreign Host rejected | 0 failures |
| ui-is-local-only | No external URLs in the UI; JS parses | 0 refs |
| skill-portable | The skill folder copied alone runs under `python3 -I`; code parses as Python 3.10 | all true |

## History (this machine, 2026-10-22)

| Run | Result | Change that moved it |
| --- | --- | --- |
| Baseline | 9/11 | — |
| 2 | 10/11 | `pricing` max error 29.8% → 0.04%: the eval assumed the main thread's cache TTL for subagents (they use 5 min). Pricing code was correct. |
| 3 | 11/11 | `context` complete rate 78.8% → 100%: unstored messages (previous response, tool results, typed prompts) rebuilt from the transcript. |
| 4 | 11/11 | Harness system messages split into contributors. One block had been labelled "Hooks" though 25k of its 30k chars were the skills/agents/MCP listings. Added `harness-listings` rule. |

Latest measured values: 53 model rows reproduce the meter with max error 0.038%; 9/9 Codex threads match
to the token; 36/36 sampled exact requests rebuilt completely (calibration 1.34–1.89 tokens per chars/4);
106 HTTP requests, p95 0.10 s; cold parse of ~250 MB of logs 1.0 s.

## Manual / agent-driven checks (not in the script)

- **Browser** (Claude in Chrome, 1440×900 and 390-wide frames, light and dark): all eight views render with
  no console errors and no horizontal scroll at 390 px. Clicking a context-strip column opens that
  request's context; group filter, tool-call expand, timeline search and period toggle work.
- **Skill in Claude Code**: `claude -p "What did my coding agents cost over the last 7 days…" --model haiku`
  from this repo found the project-local skill and quoted numbers that match `report --days 7 --json`
  ($38.23, 12 sessions, 96% cache hits). One slip by the model: it said 6 sessions log the meter (the
  report says 7). Cost $0.0056.
- **Skill in Codex**: `codex exec -s read-only "Using the agents-report skill…"` found
  `.agents/skills/agents-report` and answered from `context latest`.

These need a live browser or agent CLI, so they are re-run by hand (or by an agent) after UI or SKILL.md
changes.
