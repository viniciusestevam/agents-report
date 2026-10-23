# Tools

Developer tools for screenshots and demos. Nothing here ships with the skill, and everything uses
**synthetic data** from `make_demo_data.py`: fake projects, sessions for Claude Code, Codex and Hermes, no
real transcript.

| File | What |
| --- | --- |
| `make_demo_data.py` | Writes synthetic agent logs and prints the environment variables that point Agents Report at them |
| `record.mjs` | Drives headless Chrome over the DevTools protocol (no npm dependencies): README screenshots, or a demo video |
| `replay.html`, `claude_run_steps.json` | A replay of a real Claude Code run of the skill on the demo data, used by the video |

## README screenshots

```bash
D=/tmp/agents-report-demo
python3 tools/make_demo_data.py $D
eval "$(python3 tools/make_demo_data.py $D --env)"
python3 skills/agents-report/scripts/agents_report.py serve --port 48799 &

node tools/record.mjs shots .github/assets/screenshots http://127.0.0.1:48799/
```

This writes `overview.png`, `sessions.png`, `trace.png`, `context.png`, `recommendations.png` and
`trace-dark.png` at 1440×900, 2× scale.

## Demo video

```bash
python3 -c "import sys; t=open('tools/replay.html').read(); open(sys.argv[2],'w').write(t.replace('/*STEPS*/[]', open(sys.argv[1]).read()))" tools/claude_run_steps.json $D/replay.html
node tools/record.mjs video $D/video http://127.0.0.1:48799/ $D/replay.html
ffmpeg -f concat -safe 0 -i $D/video/frames.ffconcat -vf "fps=30,format=yuv420p" -c:v libx264 -crf 20 -movflags +faststart demo.mp4
```

To capture a new Claude Code run, pass the demo paths to its tools only
(`claude -p "/agents-report …" --settings '{"env": {…}}'` with the variables from `--env`). Don't set
`CLAUDE_CONFIG_DIR`: Claude Code would then write its own transcripts, with your real paths, into the demo
folder. `AGENTS_REPORT_CLAUDE_PROJECTS` points the skill at the demo logs instead.

Needs Google Chrome, Node 22+ and, for the video, ffmpeg.
