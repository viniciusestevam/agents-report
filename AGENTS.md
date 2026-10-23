# Working on Agents Report

Instructions for coding agents contributing to this repository. Users of the tool don't need this
file; the skill's own instructions are in `.agents/skills/agents-report/SKILL.md`.

- Start from `docs/STATE.md`: objective, decisions, known limitations and next steps. Update it at
  every milestone.
- `.agents/skills/agents-report/` is the shipped plugin/skill. Keep tests, evals, tools and docs out of it.
- Python standard library only; the UI is vanilla HTML/CSS/JS with no build step and no network access.
- Run `python3 -m unittest discover -s tests` and `python3 evals/run_evals.py` before and after a change;
  all checks must pass. Run `claude plugin validate .` after touching a manifest.
- Unknown prices or data are `null`, never 0. Every number keeps its basis (measured or estimated).
- CLI output must stay deterministic (see the determinism test and eval).
- Never commit transcripts or screenshots of real sessions; use `tools/make_demo_data.py`.
- Never commit the zip that `agents_report.py package` writes.
