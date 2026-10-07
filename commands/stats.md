---
description: Show what walkie has recorded about your own speech and listening on this machine
allowed-tools: Bash(uv run:*)
---

Run `uv run --directory "${CLAUDE_PLUGIN_ROOT}" --quiet walkie-stats` and show its output
as it stands. If `uv` is not on PATH, use `~/.local/bin/uv`.

It reads the local telemetry database and changes nothing. Do not summarise away rows
the user may want to see; add a short summary after the output only if they ask.
