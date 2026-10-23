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
`python3 .agents/skills/agents-report/scripts/agents_report.py dashboard` (or install your working copy
as the `agents-report` command with `uv tool install --editable .`). A running server restarts itself
when the code changes.

The skill folder is the single source: `pyproject.toml` builds the `agents-report` package from its
`scripts/agentobs/` code and bundles `assets/ui/` into it. The version lives in `agentobs/__init__.py`,
and a test checks that `SKILL.md` and `plugin.json` say the same.

To work without your own logs, generate synthetic ones:

```bash
eval "$(python3 tools/make_demo_data.py /tmp/agents-report-demo --env)"
python3 .agents/skills/agents-report/scripts/agents_report.py serve --port 48799
```

## Pull requests

1. Use [semantic commit messages](#commit-messages), one logical change per commit.
2. Add or update a test for the behavior you change (fixtures live in `tests/fixtures.py`).
3. Run the tests and the evals; both must pass.
4. If you change the UI, check it in light and dark mode and at phone width, and refresh the README
   screenshots if they no longer match (`tools/README.md`).
5. Keep `.agents/skills/agents-report/SKILL.md` short: it is loaded into the agent's context.

## Commit messages

Commits follow [Conventional Commits](https://www.conventionalcommits.org): `<type>(<scope>): <summary>`,
in the imperative, at most 72 characters, with the why in the body when it isn't obvious.

| Type | For |
| --- | --- |
| `feat` | a new capability (command, view, metric, adapter, rule) |
| `fix` | a bug fix |
| `docs` | README, guides, references |
| `style` | visual or formatting changes with no behavior change |
| `refactor` | restructuring with no behavior change |
| `perf` | faster or lighter, same behavior |
| `test` | tests and evals only |
| `build`, `ci`, `chore` | packaging, workflows, tooling and upkeep |

Scopes are optional; the usual ones are `cli`, `ui`, `adapters`, `pricing`, `context`, `plugin`, `package`,
`tools`, `evals` and `github`. Mark a breaking change with `!` (`feat(cli)!: …`) and explain it in the body.

Examples: `feat(adapters): read Gemini CLI sessions`, `fix(ui): keep trace idle-gap marks off tick labels`.

CI checks every commit with `tools/check_commits.py`. Run the same check when you commit by enabling the
hook once:

```bash
git config core.hooksPath .githooks
```

## Adding an agent

Write one adapter module in `.agents/skills/agents-report/scripts/agentobs/adapters/`. The contract is in
[.agents/skills/agents-report/references/adapters.md](.agents/skills/agents-report/references/adapters.md). Add a
fixture builder and tests, and say in the adapter whether it was verified on real logs.
