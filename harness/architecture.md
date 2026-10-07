# <img src="../assets/walkie-detailed.svg" width="28" height="28" alt="" valign="middle" /> Architecture

> System shape and the decisions behind it. Update after an agreed
> architectural change. Keep decisions with their rationale (the "why").

## Overview

walkie is a coding-agent plugin for talking with the agent. It runs as an MCP server over
stdio (`walkie-mcp`) with six tools — `speak`, `listen`, `list_voices`, `set_voice`,
`speech_status`, `stop_speaking` — and one prompt, `converse`, and ships the commands
`/walkie:talk`, `/walkie:converse`, `/walkie:setup`, `/walkie:telemetry` and
`/walkie:stats`. Everything runs on the machine, on NVIDIA NeMo-Speech.cpp.

There are two entry points into the same code: the long-lived MCP server (`__main__`)
and a short-lived one-shot process (`talk`) that `/walkie:talk` runs and whose stdout is
injected into the user's message. Both transcribe against the one shared speech server
that `speak_core.supervisor.NemoSupervisor` manages, which voicebox uses too when it is
installed.

The engines, the supervisor, the playback queue, the speaker lock, the shared settings
and the telemetry mechanism are [speak-core](https://github.com/danilogr/speak-core)'s, a
git dependency pinned by tag; their design and the decisions behind them are in its
`harness/architecture.md`. This document covers what walkie builds on top.

## Components & boundaries

- **`__main__`** — the composition root for the MCP server. Reads the environment,
  builds every other component, and starts the transport. It must not contain speech
  behaviour; the only logic it owns is which components to build and what telemetry may
  do, in `build_ears`, `build_supervisor` and `build`, which `tests/test_composition.py`
  and `tests/telemetry/test_main_build.py` cover. `__main__`, `talk` and
  `telemetry.commands` are the only modules that read `os.environ`, and none installs a
  log handler itself — `__main__` and `talk` call `speak_core.runtime.configure_logging`.
- **`config.Settings`** — walkie's settings: a `ServerSettings`, a `VoiceSettings` read
  under `WALKIE_`, the listening settings and the state directory.
- **`server.create_server`** — the transport layer. Defines the tools inside a factory
  that closes over its dependencies, so there is no module-level mutable state and tests
  can build a server over fakes. It must not contain speech logic; it normalizes,
  delegates, and formats the reply. `listen` is defined only when the factory is given an
  `Ears`, which bundles the recorder, the transcriber, the microphone lock, the speaker
  lock, the capture limits and the recording cue. Every successful reply except
  `listen`'s passes through `reply`, which appends the first-run notice once.
- **`speakers`** — `holding(speaker)`: the shared speaker lock held for one recording,
  waited for up to `SPEAKER_WAIT_S`. It must not know what the recording is for.
- **`cue`** — the three sounds that bracket one recording: open, close, and the error
  tone that replaces the close when nothing was captured. Played through the resolved
  player with the same detached-spawn helper the speech queue uses. It must not know why
  the microphone is opening, and it must never fail a recording: a missing sound file, a
  missing player or a non-zero exit is a debug log and nothing else.
- **`capture`** — the microphone. `SilenceTracker` is a pure state machine fed block
  energies that decides when an utterance has ended; `MicrophoneRecorder` is a thin shell
  that opens a `sounddevice` stream and feeds it. The split is what lets every capture
  path be tested without audio hardware.
- **`miclock`** — one holder at a time for the single microphone, a
  `speak_core.exclusive.ExclusiveLock` with an ownerless grace. It must not know what the
  microphone is for.
- **`listening`** — what both entry points build the same way for listening: the capture
  limits, the microphone, the cue and the transcription timeout.
- **`talk`** — the `/walkie:talk` one-shot: hold the shared server for the life of the
  process, record, transcribe, print. The only module where printing to stdout is the
  point.

## Data model

Almost nothing is persistent.

- **Session state** (in memory, per process): the active voice and rate, whether the
  voice is re-rolled, the warmup task, whether this session has registered with the
  supervisor, and whether the first-run notice is still to be handed out. Claude Code
  runs one server process per session, so this is already isolated from every other
  window. Deliberately never written to disk.
- **Plugin state** (`WALKIE_STATE_DIR`, `<cache>/walkie`):
  - `mic/owner` — the pid of the session currently recording. Its directory is the lock;
    the file says who holds it, so a lock left by a dead session is reclaimed.
  - `telemetry.db` — the local telemetry store.
- **Config** (`<config>/walkie`, the OS's per-user config directory, never a cache):
  `telemetry.json` (the mode, the install id and the machine probe), `notice.json` (the
  disclosure shown), `ping.json` (the last version counted) and, when the user keeps
  them, `recordings/`.
- **Shared state** (`<cache>/speak-core`, speak-core's): the speech server's start lock,
  pid record and client registry, and the speaker lock, which voicebox reads and writes
  too.

Voice input is not persistent by default. A recording lives in memory as WAV bytes for
the length of one transcription and is discarded. It is written to disk only when the
user turns recording on (`/walkie:telemetry record on`) while telemetry collects, in which
case each recording is kept locally beside its row so the user can later train a model on
their own voice. Recordings are never uploaded under any setting — the server schema has
no column for them.

## Telemetry

`walkie/telemetry/` is walkie's part of the telemetry, on top of `speak_core.telemetry`
(identity, consent, the notice marker, the machine probe, the store, shipping and the
install ping). The rest of walkie reaches it through three seams: the queue's
`on_finish` callback (one `UtteranceOutcome` per utterance that leaves it), a
`TelemetrySession` handed to `create_server` and to `talk.dictate`, and a `Notice` handed
to `create_server`. Neither the queue nor the server knows what a `TelemetrySession` does
with what it is given.

- **`contract.py`** — walkie's identity and schema (speak-telemetry contract v1, bundled
  byte for byte); a test checks its column lists against the SQL, including every
  `-- LOCAL` column. The store is `<state>/telemetry.db`.
- **`session.py`** — turns queue outcomes and listen/talk attempts into stored rows,
  clamping every value to the contract. Every public method catches its own failures: a
  dead telemetry backend has to be indistinguishable from a healthy one.
- **`compose.py`** — `build()`: `start_install`, then walkie's own `sessions` row, then
  the `TelemetrySession`; `None` when telemetry does not collect or the store cannot be
  used. Never raises. `is_release` says whether this build may send.
- **`notice.py`** — the first-run notice's words and `Notice`, which hands them out once.
- **`stats.py`** — `walkie-stats`: `stats.render` is plain SQL over walkie's tables, run
  through `speak_core.telemetry.report`.
- **`commands.py`** — the two console scripts (`walkie-telemetry` with `notice`, and
  `walkie-stats`); the only telemetry module that reads `os.environ` and `sys.argv`.

Until the notice has been shown for the current disclosure, neither entry point collects,
pings or ships. Once it has, shipping and the ping run once per MCP session, scheduled
from `create_server`'s lifespan rather than from `__main__.build()` itself: `build()` runs
before the event loop starts, so nothing there can call `asyncio.create_task`.
`/walkie:talk` sends the ping alongside its recording but never ships; the next MCP
session ships its rows. A build whose version is not a release collects and sends
nothing.

The lifespan's shutdown is what closes a session row, so `__main__.serve_stdio` turns
SIGTERM and SIGHUP into a cancellation that unwinds through it, as Ctrl-C does. Left at
their defaults, either signal kills the process before any of it runs. Once that shutdown
has run, `__main__.run` ends the process with `os._exit`: the MCP transport reads stdin on
a non-daemon thread no signal interrupts, and a normal exit would wait for it until the
host closed the pipe.

## External dependencies

- **`mcp`** — the official MCP SDK. Provides the stdio transport, protocol negotiation,
  tool-schema generation from type hints, and the client used by the end-to-end tests.
- **`speak-core`** — the shared speech library,
  `speak-core @ git+https://github.com/danilogr/speak-core@<tag>`, pinned to a release tag.
- **`sounddevice`** — the microphone binding, and the only native-wheel dependency here.
  Imported inside the recorder rather than at module scope, so a machine without a
  working PortAudio still runs the speech half of walkie.
- **`uv`** — environment and dependency management, and the launcher. Must be resolvable
  at startup; `scripts/walkie-mcp` and `scripts/walkie-talk` find it.
- **macOS `say`** — the default engine, and the fallback whenever the speech server
  cannot be reached. macOS-only: on any other platform it is reported once at startup,
  and `WALKIE_ENGINE=nemo` or `WALKIE_ENGINE=command` is the way through.
- **A WAV player** — discovered, not assumed: `afplay`, PowerShell's `SoundPlayer`, or
  one of `paplay`, `aplay`, `ffplay`, `play`, `mpv`. Not a hard dependency; with none
  present the cues are skipped and the `nemo` engine speaks through the fallback rather
  than writing audio nothing can play.
- **The cue sounds** — synthesised by `scripts/make-cues.py` and committed under
  `src/walkie/assets`. Not taken from the host operating system: the paths differ per
  platform, and shipping another vendor's audio is not ours to do.
- **NVIDIA NeMo-Speech.cpp** (https://github.com/NVIDIA/NeMo-Speech.cpp) — the local
  neural speech server and the technology walkie runs on: MagpieTTS for speech, Nemotron
  3.5 for recognition. Installed by `speak-core-setup` (`/walkie:setup`) and managed by
  `speak_core.supervisor.NemoSupervisor`. Not vendored: it is a per-platform binary plus
  both models, which is over a gigabyte of download. Sizes are in `performance.md`.
- **The speak-telemetry Worker** (`https://speak-telemetry.actionableintelligence.app`)
  — receives the install ping and, with telemetry `on`, the rows; contract v1 is vendored
  under `tests/contract/` with a freshness test against the sibling repo.

## Key decisions (with rationale)

- **The wire carries no plugin name.** Contract v1 fixes the ping at three fields
  (`plugin_version`, `os`, `event`) and the transport sends no user agent, so a backend
  cannot tell one plugin's ping from another's. Each plugin has its own telemetry
  Worker (walkie: speak-telemetry; voicebox: voicebox-telemetry), so nothing needs
  splitting by product. A plugin's identity
  (`TelemetryIdentity`) steers only the client: its variables, config directory,
  endpoint and disclosure version.

- **The when-to-speak policy lives in the `speak` tool description.**
  A tool description is always in the model's context at the moment the choice is made.
  Not a hook or a skill, neither of which can add a callable tool or is guaranteed
  to be read at that moment.

  The closing one-line recap is part of that policy and lives in the same place, for the
  same reason plus one more: a `Stop` hook receives a shell command and no view of the
  turn, so it can play a fixed sound but cannot say what changed. The hook types that
  could summarise — `prompt` and `agent` — are restricted to tool events. Only the model
  can write the recap. Nor per-user memory or `AGENTS.md`, which would make
  the plugin's own behaviour depend on machine-local state that does not travel with it.

- **Voice and rate are per connection and never persisted.** One server
  process per session means a plain attribute is already isolated. Not a
  machine-wide voice file, which would leak one window's choice into every other.

- **Dependencies are injected, and the server is built by a factory.**
  `create_server` closes over its engine, queue, and `speak_core.supervisor.NemoSupervisor`; the queue takes its
  process launcher, and `NemoSupervisor` its spawn, liveness, and kill callables. This is
  what lets the suite cover the real code paths with no audio, no sockets, and no
  speech server. Not module-level singletons, which would force monkeypatching.

- **Deliberate tool failures raise `ToolError`.** The SDK withholds a raw
  exception's text from the model and sends a generic message instead, which would turn
  "unknown voice X; available: …" into unusable feedback. `ToolError` carries the
  message through.

- **A random session voice is resolved lazily, not at startup.** A
  speech server reports no voices until it has warmed up, so rolling at construction
  would always fall back to the default. The roll happens on first use and retries
  until the engine can answer. Per engine, the eligible pool differs: `nemo` uses every
  speaker the model reports, while `say` reports mostly novelty and legacy voices and so
  draws from a curated natural-voice list, narrowed to what is actually installed.
  `WALKIE_VOICE_POOL` overrides both and is taken at its word, so it also works with an
  engine that reports no names at all.

- **Shutdown silences the queue before tearing down its worker.** The
  worker task owns the running child process, so cancelling it first drops the handle
  and leaves the machine talking after the session is gone. Stopping the queue first
  terminates the child while it is still tracked.

- **stdout is the protocol channel.** All logging goes to stderr, and the
  log handler is installed in one place. A stray `print` in library code desynchronizes
  the session, so library modules use `logging.getLogger(__name__)` only.

  `/walkie:talk` is the exception that proves it: its stdout is a prompt, not a protocol,
  and a failure there is printed to stdout as well as stderr. `commands/talk.md`
  branches on a line beginning `walkie:`, and only stdout is certainly injected —
  whether a slash command's `!` capture carries stderr from a non-zero exit is not
  this plugin's to guarantee, and if it does not, stderr alone leaves the model an
  empty transcript under an instruction to act on it as the user's request. The
  prefix is what keeps the stdout copy from being read as speech.

- **`.mcp.json` launches `/bin/sh scripts/walkie-mcp` rather than `uv`.**
  `/bin/sh` is an absolute path present on every target system, so the launch has no
  PATH dependency; the shim then finds uv via `$WALKIE_UV`, the PATH, and the locations
  uv's installers use. Not invoking `uv` directly, which fails under any parent
  that does not source the user's shell profile.

- **`listen` drains the speech queue before opening the microphone.**
  `speak` returns immediately by design, so a question is usually still playing when
  the next tool call runs, and without the drain the recording captures the agent's
  own voice. `speak_core.queue.SpeechQueue.drain()` exists for this and waits out synthesis as well as
  playback, and it waits as long as utterances keep finishing: one spoken answer is
  several of them, and each costs its synthesis as well as its audio, so a batch runs
  for minutes of legitimate work. Only a stall - nothing finishing inside a minute -
  ends the wait, and then the call is refused rather than recorded. Our own voice handed
  back as the user's answer is a fabricated request the model acts on, where a refusal
  can simply be retried.
  Not a combined `ask(question)` tool, which duplicates `speak` to buy only the
  ordering the drain already gives.

  `/walkie:talk` cannot drain the session's queue: it is a separate process with no
  handle on it. It holds the speakers for its recording instead, as `listen` does after
  its drain, so a sentence the session is playing finishes before the microphone opens
  and the session's next sentence waits until the recording ends. A sentence the session
  synthesizes during the recording is played after it, not recorded.

- **Recording stops on silence, not on a keypress.** Neither entry point
  has a terminal: the MCP server owns stdin for the protocol, and a slash command's
  bash output is captured. There is no key to press, so silence is the only available
  end-of-turn signal. The gate is calibrated from the room's own ambient level over
  the first 300 ms rather than fixed, because a fixed threshold fails on a quiet
  microphone and in a noisy room alike.

- **The microphone is arbitrated by a lock, and contention fails fast.**
  There is one microphone and any number of sessions; two recordings at once produce
  garbage in both. The election is `speak_core.exclusive.ExclusiveLock`'s, reused: an atomic `mkdir` on
  `mic/`, an owner pid in the file inside it, and a lock left by a dead session
  reclaimed by the next caller. Not queueing on the lock, which is worse than
  refusing — you would start talking and a window you are not looking at would take
  the words.
  A lock directory with no owner file is another session mid-claim, refused as busy
  until it has gone 2 s unchanged (the speaker lock's window), and only then reclaimed
  as left by a session that died mid-claim; reclaiming it at once would let two sessions
  record from one microphone.

- **A second, in-process lock guards `listen` against itself.** The
  microphone lock is re-entrant by pid, which is what makes reclaiming a dead owner's
  lock possible but means it does not separate two calls inside one session: both
  would acquire it, and the first to finish would release the cross-process lock while
  the other was still recording. `listen` therefore also holds an `asyncio.Lock` and
  refuses a concurrent call rather than queueing it, so the answer is immediate.

- **Capture uses the `sounddevice` package rather than an ffmpeg
  subprocess.** It is the first native-wheel dependency here, and it is what makes
  voice input work off macOS; an `avfoundation` command line would not. The import is
  inside the recorder so a machine without a working PortAudio still gets speech.
  Not ffmpeg, which is one more thing to install and macOS-specific in this use.

- **A denied microphone arrives as silence, not as an error.** macOS opens the stream
  and delivers zeroed samples rather than raising, so there is no error to report and
  no way to distinguish a denied input from a muted one at the API. Both read as exact
  digital silence, which the deafness check treats as a muted device and names as such
  — permission is one of the causes that message lists. "Heard nothing" is reserved for
  a live microphone whose gate never opened, so the two remedies stay separate.

- **Whether anyone spoke is recorded by the tracker, not inferred from
  the terminal state.** `SilenceTracker.feed` checks the cap before the start
  timeout, so a recording of an empty room ends CAPPED rather than SILENT whenever
  the cap is the shorter limit — which `listen(max_seconds=8)` produces against the
  default 10 s timeout, and `max_seconds` is a parameter the model chooses. Treating
  CAPPED as speech would send room tone to the transcriber, and a transcription model
  given silence reliably emits a stock phrase: a fabricated answer for `listen`, and an
  injected prompt for `/walkie:talk`, whose command file says to act on it as the user's
  request. `Recording.has_speech` is therefore the fact that the gate opened, carried
  from the tracker. Clamping the start timeout to the cap is not enough: it narrows the
  window but still lands on CAPPED when the two are equal.

- **The microphone gate is clamped from above as well as below.**
  Calibration averages the first 300 ms, and nothing cues the user to wait, so
  talking straight away is the ordinary first run rather than a corner case. Without an
  upper clamp the gate lands near three times speech level, above anything a microphone
  produces, and the recording ends SILENT at the start timeout with nothing to show for
  it. A gate that is too low costs a longer recording; one that is too high loses the
  utterance and misdirects the user.

- **The default input is tried first, and a silent device is stepped
  over.** A stream of exact zeros is not a quiet room: a live microphone always carries
  a noise floor, so digital silence means a muted or disabled input. The OS default
  leads the search, so the device chosen in system settings wins on the first recording
  of every session; whatever answers is kept for the rest of the session, in memory
  only. Not persisting the choice, which would let a remembered device silently
  override the setting the user can see. A device is skipped only for exact silence,
  never for being quiet, or a pause would cascade through every input at ten seconds
  each.

- **Deafness is judged on its own window, not the calibration window.**
  CoreAudio hands over exact zeros while an input primes, and a Bluetooth microphone
  can take most of a second, so a 300 ms verdict rejects a working device that is
  merely slow. A device gets 1.5 s to produce anything; calibration then runs from its
  first real sample, which also keeps priming silence out of the ambient average — a
  gate diluted by zeros lands at the floor, and in a noisy room a floor-level gate
  opens on the room and never closes.

- **A word spoken before the gate arms starts the utterance.** Calibration runs for
  300 ms from the first real sample, and a one-word answer can be over before it ends.
  Averaging that voice into the ambient puts the gate above the speech it exists to
  detect, and the blocks are already buffered, so a block at or above the ceiling ends
  calibration instead: the gate takes the floor and the utterance begins there. The
  ceiling is the dividing line because no room delivers a block that loud, while a noisy
  room can still push the computed gate above it.

- **An empty capture ends on a different sound.** Recording stops on
  silence whether or not anyone spoke, so without a distinct tone the two are
  indistinguishable until the transcript fails to arrive. It replaces the closing cue
  rather than following it: "got it" then "that failed" is worse than only the second.

- **The cue sounds ship with the plugin, and the player is resolved.** A path into a
  system sound directory or a fixed player binary would tie playback to one operating
  system, while the microphone half is portable. Generated sounds are reproducible and
  carry no one else's assets; a resolved player keeps playback a subprocess, which the
  queue needs because it stops an utterance by terminating it.

- **Conversation mode is served as an MCP prompt, from its command file.** Claude Code
  reads `commands/*.md` itself; every other MCP client sees only what the server
  offers. The `converse` prompt serves that same file with its frontmatter removed, and
  takes its description from the frontmatter, so both have one copy whichever app asks.
  It is read once at startup, like the tool descriptions, and a checkout without the
  file loses the prompt and nothing else. It is offered only when `listen` is
  registered, because its instruction is to call it. `/walkie:talk` stays a slash command: it
  records before the user's message exists, and a prompt handler blocked on a
  microphone for seconds is what a client's timeout cuts off.

- **The microphone is cued open and cued shut, and the opening cue is
  awaited.** Nothing else told the user the microphone was open; `/walkie:talk` is the acute
  case, where you press enter and have no way to tell whether to talk now or in two
  seconds. The closing cue is not decoration either: recording ends on silence rather
  than on a keypress, so without it you never learn when the gate decided you had
  finished. Both are awaited to completion. That is a correctness requirement for the
  opening one and not merely tidiness: `SilenceTracker` calibrates its gate from the
  first 300 ms of audio, so a chime still sounding when the stream opens is averaged
  into the ambient level, sets the gate above what a voice reaches, and ends the
  recording in silence — the failure the upper clamp was added to survive. The clamp
  stays as the backstop; the cue is not allowed to lean on it. The end cue is awaited
  too, because the latency costs nothing next to the transcription that follows.

  The cues bracket the recording alone: they sound after the microphone lock and the speakers are held
  and the speech server has answered, so a refused or unserviceable `listen` stays
  silent, and the closing one sounds when recording stops rather than when the
  transcript arrives. A cue is a convenience and a recording is not, so a missing
  sound file, a missing player, or a player that exits non-zero degrades to a debug
  log. Not playing the cue without awaiting it, which is exactly the
  calibration bug above; and a cue on only one end, which leaves the more useful half
  of the question — am I still being recorded? — unanswered.

- **A recording holds the speakers.** voicebox reads long texts aloud through its own
  queue in its own process, and nothing in walkie's queue can see it. Every queue already
  takes speak-core's cross-process speaker lock around each utterance, so `listen` and
  `/walkie:talk` take the same lock from just before the opening cue to just after the
  closing one: a sentence already playing finishes, no other starts while the microphone
  is open, and the transcription runs with the speakers free again. The microphone lock
  is claimed first, so a busy microphone is refused at once rather than after a wait. A
  lock still held after `SPEAKER_WAIT_S` (60 s) is a player that is not going to stop; the
  recording is refused with a `refused` row and no cue, rather than waiting without end.
  In the MCP server the queue and `listen` share one `SpeakerLock`, which is what makes
  this session's own next sentence wait for the recording. Rejected: draining voicebox's
  queue, which walkie cannot see, and pausing it through a new signal, which the lock
  already is.

- **Nothing is collected before the first-run notice is shown.** "Shown once before
  anything is sent" stays literal: until `notice.json` records disclosure 1, neither the
  server nor `/walkie:talk` opens the store, pings or ships. The notice rides the first
  reply of a session from any tool but `listen` — a tool reply reaches the model, so it
  carries an instruction to show it word for word — and `/walkie:setup` prints it.
  `listen`'s reply is the user's own words and is never mixed with anything, and
  `/walkie:talk` never shows it because its output becomes the user's prompt. Cost: a
  session that never sees a tool reply is not counted.

- **The telemetry store lives in the state dir; consent and recordings in the config
  dir.** The store is walkie's own bookkeeping, and losing it to a cache clean loses
  nothing that matters. Consent must survive one — a cleared cache must not silently
  re-enable telemetry someone switched off — and so must the user's own recordings.

- **A corrupt store, or a value the contract would refuse, costs telemetry, not walkie.**
  `compose.build` catches `OSError` and `sqlite3.Error` and collects nothing; a model
  name longer than the contract's 64 characters is left out rather than cut, because a
  cut name is a different, wrong one. The contract tests read every pattern the way the
  server's ajv does, where `$` does not match before a trailing newline.

- **walkie has no marketplace of its own.** It is listed second in voicebox's
  `voicebox-marketplace` as a GitHub source, so Claude Code runs it from a clone in its
  plugin cache; `scripts/install-local.sh` copies a working tree over that clone for
  development.
