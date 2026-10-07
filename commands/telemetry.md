---
description: Show or change walkie's telemetry setting, print this install's id, or keep your own recordings
argument-hint: "[on | local | off | --id | record on | record off]"
allowed-tools: Bash(uv run:*)
---

Run `uv run --directory "${CLAUDE_PLUGIN_ROOT}" --quiet walkie-telemetry $ARGUMENTS` and
show its output as it stands. If `uv` is not on PATH, use `~/.local/bin/uv`.

With no arguments it reports the saved mode. `on`, `local` and `off` change it, `--id`
prints this install's id, and `record on` or `record off` keeps or stops keeping the
user's own recordings on this machine. Run only what the arguments say; do not change a
setting the user did not name.

If the user asks to send nothing at all, say that `off` still sends the anonymous
install count, and that setting `DO_NOT_TRACK=1` in their environment is what stops it
too. Do not edit their shell profile or settings without asking. `TELEMETRY.md` in the
plugin root says what is collected and why.
