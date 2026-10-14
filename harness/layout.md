# <img src="../assets/walkie-detailed.svg" width="28" height="28" alt="" valign="middle" /> Codebase Layout

> Exhaustive guide to the files and directories in this repository.
> For system architecture, component boundaries, and design decisions, see [architecture.md](architecture.md).

## Directory Overview

```
.
├── .claude-plugin/         The plugin manifest
├── assets/                 walkie's art: the pixel icon and the hero image
├── commands/               Claude Code slash commands (/walkie:talk, /walkie:setup, …)
├── harness/                Developer docs: architecture, flows, performance, guidelines
├── scripts/                Launchers, cue sound synthesis, the local install helper
├── src/walkie/             The plugin: MCP server, speech tools, voice input
│   ├── assets/             Synthesized WAV cue sounds
│   └── telemetry/          walkie's telemetry: contract, session, notice, stats and consent commands
├── tests/                  Offline, mocked tests
│   ├── contract/           The vendored speak-telemetry contract v1 and its tests
│   └── telemetry/          Telemetry tests
└── voice-tuning/           Recording a personal dataset and fine-tuning recognition
```

Engines, supervisor, queue, speaker lock and the telemetry mechanism live in speak-core.

---

## Root Files

| File | Purpose |
|---|---|
| [`README.md`](../README.md) | What walkie does, installing it, its tools, commands and settings, and the developer quickstart. |
| [`LICENSE`](../LICENSE) | The MIT license. |
| [`AGENTS.md`](../AGENTS.md) | Operating rules for AI coding agents working on this repository. |
| [`TELEMETRY.md`](../TELEMETRY.md) | Every telemetry field, the notice, the install count, and how to opt out. |
| [`pyproject.toml`](../pyproject.toml) | Package metadata, the speak-core pin, the `walkie-mcp`, `walkie-talk`, `walkie-telemetry` and `walkie-stats` console scripts, and ruff/mypy/pytest settings. |
| [`uv.lock`](../uv.lock) | Pinned dependency lockfile. |

---

## Plugin Manifest & Launchers

| File | Purpose |
|---|---|
| [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json) | The plugin's name, version, description and repository. The marketplace that lists it is voicebox's. |
| [`.mcp.json`](../.mcp.json) | Declares how Claude Code launches the `walkie` MCP server: `/bin/sh scripts/walkie-mcp`. |
| [`scripts/walkie-mcp`](../scripts/walkie-mcp) | Finds `uv` on the host and runs the `walkie-mcp` entry point. |
| [`scripts/walkie-talk`](../scripts/walkie-talk) | Finds `uv`, exports the host it is given as `WALKIE_HARNESS`, and runs `walkie-talk`, which records, transcribes and prints the transcript. |
| [`scripts/install-local.sh`](../scripts/install-local.sh) | Copies this checkout over the installed plugin under `~/.claude/plugins/cache/voicebox-marketplace/walkie/<version>/`. |
| [`scripts/make-cues.py`](../scripts/make-cues.py) | Synthesizes the three shipped 16-bit PCM WAV cue sounds with the standard `wave` and `math` modules. |

---

## Slash Commands (`commands/`)

| File | Command | Description |
|---|---|---|
| [`commands/talk.md`](../commands/talk.md) | `/walkie:talk` | Runs `scripts/walkie-talk`, injects the transcript into the prompt, and tells Claude to confirm destructive actions. |
| [`commands/converse.md`](../commands/converse.md) | `/walkie:converse` | Spoken conversation mode for the rest of the session; also served as the `converse` MCP prompt. |
| [`commands/setup.md`](../commands/setup.md) | `/walkie:setup` | Installs NVIDIA NeMo-Speech.cpp and both models through `speak-core-setup`, and shows the telemetry notice. |
| [`commands/telemetry.md`](../commands/telemetry.md) | `/walkie:telemetry` | Runs `walkie-telemetry` with the user's arguments. |
| [`commands/stats.md`](../commands/stats.md) | `/walkie:stats` | Runs `walkie-stats`. |

---

## Harness (`harness/`)

| File | Description |
|---|---|
| [`harness/architecture.md`](architecture.md) | Component boundaries, state, telemetry, external dependencies, and the rationale for each key decision. |
| [`harness/user-flow.md`](user-flow.md) | Speaking, one recording state by state, choosing an input, `listen`, `/walkie:talk`, telemetry, and the shared speech server. |
| [`harness/performance.md`](performance.md) | Measured latency, memory, disk and microphone figures, and the hardware behind them. |
| [`harness/integration.md`](integration.md) | Building the local speech stack into an agent that is not this plugin. |
| [`harness/design-guidelines.md`](design-guidelines.md) | Environment, naming, layering, errors, logging, comments and tests. |
| [`harness/layout.md`](layout.md) | This file. |

---

## The Plugin (`src/walkie/`)

### Server & Lifecycle

| File | Responsibility |
|---|---|
| [`__main__.py`](../src/walkie/__main__.py) | Composition root: reads the environment, decides what telemetry may do, builds the engine, queue, ears and server, and serves on stdio. |
| [`server.py`](../src/walkie/server.py) | The six tools, the `converse` prompt, `Ears`, and the reply that carries the first-run notice. |
| [`tools.py`](../src/walkie/tools.py) | Tool descriptions, including the when-to-speak policy, and the messages tools answer with. |
| [`config.py`](../src/walkie/config.py) | `Settings`: the shared server settings, a voice under `WALKIE_`, the listening settings and the state directory. |
| [`listening.py`](../src/walkie/listening.py) | Capture limits, microphone, cue and transcription timeout, built the same way by `__main__` and `talk`. |

### Microphone, Speakers & Dictation

| File | Responsibility |
|---|---|
| [`capture.py`](../src/walkie/capture.py) | Records one utterance from the microphone and stops on silence; picks the input device. |
| [`cue.py`](../src/walkie/cue.py) | The chimes that bracket a recording. |
| [`miclock.py`](../src/walkie/miclock.py) | One session records at a time; a claim in progress is busy, not free. |
| [`speakers.py`](../src/walkie/speakers.py) | Holds the shared speaker lock for one recording, waiting up to `SPEAKER_WAIT_S`. |
| [`__init__.py`](../src/walkie/__init__.py) | Marks the package; empty. |
| [`talk.py`](../src/walkie/talk.py) | The `walkie-talk` entry point behind `/walkie:talk`: records, transcribes and prints. |
| [`assets/`](../src/walkie/assets/) | `cue-open.wav`, `cue-close.wav` and `cue-empty.wav`. |

### Telemetry (`src/walkie/telemetry/`)

| File | Responsibility |
|---|---|
| [`__init__.py`](../src/walkie/telemetry/__init__.py) | Marks the package; empty. |
| [`schema.sql`](../src/walkie/telemetry/schema.sql) | speak-telemetry contract v1's local schema, bundled byte for byte. Columns tagged `-- LOCAL` are never sent. |
| [`contract.py`](../src/walkie/telemetry/contract.py) | walkie's `TelemetryIdentity`, the schema's column lists, and the store's path in the state dir. |
| [`session.py`](../src/walkie/telemetry/session.py) | `TelemetrySession`: one row per sentence spoken or heard, clamped to the contract; never raises. |
| [`compose.py`](../src/walkie/telemetry/compose.py) | `build()`: the install, walkie's `sessions` row and the `TelemetrySession`; `is_release`. |
| [`notice.py`](../src/walkie/telemetry/notice.py) | The first-run notice's words, and `Notice`, which hands them out once. |
| [`stats.py`](../src/walkie/telemetry/stats.py) | `walkie-stats`'s rendering: plain SQL over the local tables. |
| [`commands.py`](../src/walkie/telemetry/commands.py) | The `walkie-telemetry` (with `notice`) and `walkie-stats` console scripts. |

---

## Voice Tuning (`voice-tuning/`)

| File | Purpose |
|---|---|
| [`voice-tuning/record.py`](../voice-tuning/record.py) | Interactive recorder for macOS: multi-pass recordings of 70 sentences and NeMo-compatible JSONL manifests. |
| [`voice-tuning/sentences.txt`](../voice-tuning/sentences.txt) | 70 sentences spanning phonetic balance, accent markers, programming jargon and spoken identifiers. |
| [`voice-tuning/.gitignore`](../voice-tuning/.gitignore) | Keeps recorded audio and JSONL manifests out of git. |
| [`voice-tuning/README.md`](../voice-tuning/README.md) | Recording a personal dataset and fine-tuning Nemotron 3.5 with adapters on an NVIDIA GPU. |

---

## Tests (`tests/`)

| Directory / File | What it tests |
|---|---|
| `tests/conftest.py`, `tests/fakes.py` | The autouse fixture that keeps every test off this machine's real state and speech server, and the fakes the server-level tests share. |
| `tests/contract/` | The vendored speak-telemetry contract v1, its fixtures, a freshness check against the sibling repo, and that what this client stores and ships validates as the server reads it. |
| `tests/telemetry/` | walkie's telemetry: schema, session, composition, notice, consent and stats commands, `build()`'s decisions, and a real server over stdio. |
| `tests/test_speakers.py` | Holding the speaker lock for a recording, against fakes and two real locks. |
| `tests/test_listen_tool.py`, `tests/test_talk.py` | `listen` and `/walkie:talk`: drain, server checks, both locks, cues, transcripts, refusals and their telemetry rows. |
| `tests/test_capture.py`, `tests/test_cue.py`, `tests/test_miclock.py`, `tests/test_listening.py` | Silence detection, device choice, cues, the microphone lock and capture limits. |
| `tests/test_server.py`, `tests/test_stop_signals.py` | The real server over stdio, and stop signals unwinding through its shutdown. |
| `tests/test_tools.py`, `tests/test_tool_behaviour.py`, `tests/test_random_voice.py`, `tests/test_harness_detection.py` | Tool schemas and descriptions, replies, voices, and harness detection. |
| `tests/test_composition.py`, `tests/test_shutdown.py`, `tests/test_config.py`, `tests/test_manifests.py` | The composition root, shutdown order, settings, and the plugin's declarations of itself. |
| `tests/test_voice_tuning.py` | The voice-tuning recorder's dataset logic. |
