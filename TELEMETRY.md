# Telemetry

walkie reports anonymous usage data so its author can tell where to spend effort. It is
on by default, starts only after you have been shown a one-time notice, and turning it
off takes one command and no account.

    /walkie:telemetry off      collect nothing; send only an anonymous install count
    /walkie:telemetry local    keep the data on this machine; send only that count
    /walkie:telemetry on       the default
    /walkie:telemetry          show the current setting
    /walkie:stats              see everything this machine has recorded

Outside Claude Code the same commands are `uv run --directory <plugin folder>
walkie-telemetry off|local|on` and `… walkie-stats`. `WALKIE_TELEMETRY=off` or `local` in
the environment lowers the setting for that process alone; it can never raise it above
what you chose. `DO_NOT_TRACK=1` goes further: nothing is collected and nothing at all is
sent, not even the install count.

## What it is for

Three questions, and nothing beyond them:

1. **Is the neural voice worth its gigabyte on the machines people actually run?** Or is
   the built-in `say` carrying most sessions?
2. **Which host is this running under?** Claude Code is not the only thing that speaks
   MCP, and effort should follow the users who exist.
3. **Do people keep using voice input, or try it once?** And when they interrupt, what
   kind of sentence were they cutting off?

## The notice

The first time walkie could send anything, it shows this, once (and `/walkie:setup`
prints it too). Until it has been shown, walkie records nothing and sends nothing.
`/walkie:talk` never shows it, because what it prints becomes your prompt.

    walkie collects anonymous usage data: which features you use, how long speech
    and listening take on your machine, and why they fail. It never sends what you or
    the agent say, or any audio; the text of what was spoken and heard stays in walkie's
    store on this machine (see /walkie:stats).

      /walkie:telemetry off     collect nothing; send only an anonymous install count
      /walkie:telemetry local   keep the data; send only an anonymous install count
      /walkie:stats             see your own

    Details: https://github.com/danilogr/walkie/blob/main/TELEMETRY.md

## The install count

One request when walkie first runs on a machine and one when a new version first runs,
in every setting except `DO_NOT_TRACK`, so that installs can be counted at all. It
carries exactly `plugin_version` (`1.0.0`), `os` (`darwin`) and `event` (`install` or
`upgrade`): no identifier, so two of them cannot be linked to each other or to anything
else, and nothing that says whether you turned telemetry off. The server adds one to a
daily count per version, OS, event and country and keeps nothing per request. Only
`ping.json`, holding the last version counted, is kept on your machine.

## What is sent

With telemetry `on`, and only then: counts, timings and fixed vocabularies. This is every
field; the machine-checked version is
[`tests/contract/v1/schema.remote.sql`](tests/contract/v1/schema.remote.sql), a
byte-for-byte copy of the only schema the server accepts (the server's own repository
is not public).

**Once per install:** a random `install_id`; `first_seen_at` and `last_seen_at`;
`plugin_version`; `disclosure_ver` (which version of this page you were shown);
`language`, `timezone` and `utc_offset_min` (the current UTC offset); `os`, `os_version` (major and minor
only) and `arch`; `cpu_model`, `cpu_count`, `ram_gb` (bucketed: 8, 16, 32, 64 or 128);
`accel` and `accel_name` (Metal, CUDA, ROCm or none). `country` is added by the server
from the network edge; your machine never sends it.

**Once per session** (one per MCP server process, and one per `/walkie:talk`):
`session_id`, `install_id`, `started_at`, `ended_at`; `plugin_version`; `tts_engine` (`say`, `nemo` or
`command`); `asr_engine` (always `nemo`) and `listen_enabled` (always true); `harness`
and `harness_version` (Claude Code, Antigravity, …).

**Once per sentence spoken or heard:**

| Field | What it says |
|---|---|
| `utterance_id`, `install_id`, `session_id`, `seq`, `direction`, `source`, `occurred_at` | a random id per row, and the back-and-forth: the agent speaking (`speak`) or you being heard (`listen`, `talk`), in order, and when each ended |
| `engine`, `model` | what did the work: the engine that actually spoke (a sentence `say` spoke while the neural server was down says `say`), and the model, e.g. `magpie` or `nemotron-3.5` |
| `voice` | a voice walkie's engines ship, or `custom` for any other name |
| `device_kind` | the kind of microphone: built-in, USB, Bluetooth, virtual or unknown — never its name |
| `intent` | why the agent spoke: a finished task, a blocker, a question, a recap, … |
| `words`, `chars`, `audio_ms` | how much was said, never what |
| `queue_wait_ms`, `synth_ms`, `play_ms`, `asr_ms` | where the time went |
| `status` | `ok`, `interrupted`, `discarded`, `failed`, `refused` or `heard_nothing` |

The contract also has five fields for transcribed files (`source_bytes`, `audio_codec`,
`converted`, `diarize`, `format`); walkie transcribes no files and never sends them.

## What is never sent

**Not what you said. Not what the agent said. Not any audio.** Also never: file names or
paths, repository or project names, environment variables, hostnames, usernames, your IP
address, the name of your microphone, or free text of any kind.

This is a property of the design, not a promise. walkie keeps a richer local database
(`~/Library/Caches/walkie/telemetry.db`): it also holds the text of each sentence spoken
and heard, a hash of each, your microphone's name and, if you keep recordings, where each
recording is and its hash, so that `/walkie:stats` can show you your own. What uploads is
that table **with those columns removed**: the server's schema is derived from the local
one by stripping every column tagged `-- LOCAL` (`text`, `text_sha256`, `audio_path`,
`audio_sha256`, `device_name`, the three correction columns, and the bookkeeping columns
`shipped_at` and `rejected_at`), and a test fails if the two drift apart.
`WALKIE_TELEMETRY_DEBUG=1` prints exactly what would be sent, the install count included,
instead of sending it.

## Keeping your own recordings

Separate, and off by default:

    /walkie:telemetry record on

This keeps the audio of what **you** say, in `~/Library/Application Support/walkie/recordings/`,
so you can later tune recognition to your own voice (see `voice-tuning/`). Recordings are
kept only while telemetry collects (`on` or `local`), **never leave your machine** under
any setting, and use real disk space. `/walkie:telemetry record off` stops it.

## Where it goes

To `speak-telemetry.actionableintelligence.app`, a Cloudflare Worker, into a database
Danilo Gasques controls. Not shared, not sold, not used for advertising. Your IP address
reaches Cloudflare as it does for any website; the server never writes it to its
database: it is used for rate limiting and discarded, and only the two-letter country is
kept. Each install sends at most about 100 rows a day; past that, rows are dropped by the
server, not retried.

## Deleting your data

There is deliberately no delete API — an erasure endpoint on a public server invites
erasing other people's data. Email **danilo@gasqu.es** with your install id, which
`/walkie:telemetry --id` prints, and it will be deleted. That id is the only thing
connecting these rows to you, which is why the request has to carry it.

## Changing your mind

Nothing is retroactive. Turning telemetry off stops future sends other than the install
count; it does not delete what has arrived — email for that. Turning it back on sends
only what is still in the local database.
