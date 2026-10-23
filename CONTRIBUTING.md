# Contributing

Thanks for helping. Bug reports, new agent adapters, recommendation rules and UI fixes are all welcome.

## Ground rules

- **No dependencies.** Everything runs on the Python 3.10+ standard library, and the dashboard is plain
  HTML, CSS and JavaScript with no build step and no external requests.
- **Never show an unknown value as zero.** Missing prices and data are `null` / "unavailable", and every
  number keeps its basis: *measured* (from logs) or *estimated* (computed).
- **Deterministic output.** The same logs must give the same text. Don't add randomness, wall-clock
  dependence (use `util.now()`), or unordered iteration to anything the CLI prints.
- **Ship only what users need.** `.agents/skills/agents-report/` is what gets installed; tests, evals, tools and
  docs stay at the repository root.

## Develop

```bash
python3 -m unittest discover -s tests     # unit and integration tests on synthetic fixtures (~3 s)
python3 evals/run_evals.py                # end-to-end checks against the real logs on your machine
claude plugin validate .                  # plugin and marketplace manifests (needs Claude Code)
```

Run the dashboard against your own logs with
`python3 .agents/skills/agents-report/scripts/agents_report.py dashboard`. A running server restarts itself
when the code changes.

To work without your own logs, generate synthetic ones:

```bash
eval "$(python3 tools/make_demo_data.py /tmp/agents-report-demo --env)"
python3 .agents/skills/agents-report/scripts/agents_report.py serve --port 48799
```

## Pull requests

1. Add or update a test for the behavior you change (fixtures live in `tests/fixtures.py`).
2. Run the tests and the evals; both must pass.
3. If you change the UI, check it in light and dark mode and at phone width, and refresh the README
   screenshots if they no longer match (`tools/README.md`).
4. Keep `.agents/skills/agents-report/SKILL.md` short: it is loaded into the agent's context.

## Adding an agent

Write one adapter module in `.agents/skills/agents-report/scripts/agentobs/adapters/`. The contract is in
[.agents/skills/agents-report/references/adapters.md](.agents/skills/agents-report/references/adapters.md). Add a
fixture builder and tests, and say in the adapter whether it was verified on real logs.
