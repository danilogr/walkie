---
description: Install NVIDIA NeMo-Speech.cpp and the models walkie needs for a neural voice and for listening
---

# Set up walkie

walkie runs entirely on this machine, powered by NVIDIA NeMo-Speech.cpp
(https://github.com/NVIDIA/NeMo-Speech.cpp): MagpieTTS for speech and Nemotron 3.5 for
recognition. Explain the cost before you start: about 1.4 GB of models on disk, and while
the speech server runs, roughly 1.75 GB of resident memory. The server is shared with
voicebox when both are installed.

1. Run `uv run --directory "${CLAUDE_PLUGIN_ROOT}" --quiet speak-core-setup` and show the
   output. It installs `nemo-speech` if it is missing or older than 0.2.0, pulls both
   models, and runs `nemo-speech doctor`. It is idempotent. If `uv` is not on PATH, use
   `~/.local/bin/uv`.
2. If it fails, report the failure verbatim rather than working around it. A partial
   install is worse than none.
3. On success, tell the user to set `WALKIE_ENGINE=nemo` in their environment for the
   neural voice, and that the plugin starts and stops the speech server on its own.
4. Listening needs nothing else switched on. Mention that the speech server starts when
   the session opens rather than on first use, so `/walkie:talk` does not pay a cold
   start, and that this costs memory from session start.
5. On macOS the first recording asks for microphone access for the app running
   Claude Code — the terminal, not Claude Code itself. The switch is in System
   Settings > Privacy & Security > Microphone. Warn that a denied microphone opens
   the stream and delivers silence rather than failing, so it reads the same as a
   muted input: walkie reports that no microphone is delivering audio and lists the
   devices it tried, with permission among the causes to check. Say that "heard
   nothing" means something different — a live microphone whose gate never opened,
   so either nothing was said or the recording ran out first.
6. Mention that the first sentence after a cold start is spoken by the macOS `say`
   voice while the server warms up (about 7 seconds), and every sentence after that
   uses the neural voice.
7. Offer to list the available voices with the `list_voices` tool and to set one
   with `set_voice`.
8. Run `uv run --directory "${CLAUDE_PLUGIN_ROOT}" --quiet walkie-telemetry notice` and
   show its output word for word: it is walkie's one-time telemetry notice.

Do not start the server yourself and do not edit the user's shell profile without asking.
