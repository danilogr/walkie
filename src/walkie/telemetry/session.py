"""Turns queue outcomes and listen/talk attempts into stored rows, for one session.

Three rules, in priority order: never block or delay speech, never break the plugin,
never send content. The first two are why every public method here is synchronous and
every failure is caught and logged at debug rather than raised - a dead telemetry
backend has to be indistinguishable from a healthy one. The third is enforced in
`ship.py`, by construction: this module freely writes content columns to the local
store, and only the upload projection drops them.
"""

import hashlib
import io
import logging
import sqlite3
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from speak_core.engines import nemo, say
from speak_core.queue import UtteranceOutcome
from speak_core.telemetry import store

from walkie.telemetry.contract import SCHEMA

logger = logging.getLogger(__name__)

_BLUETOOTH_HINTS = ("airpods", "beats", "bluetooth", "headset")
_USB_HINTS = ("usb",)
_VIRTUAL_HINTS = ("loopback", "virtual", "blackhole", "soundflower", "aggregate")
_BUILTIN_HINTS = ("built-in", "macbook", "internal")


def classify_device(name: str | None) -> str:
    """A coarse guess at the input's kind from its free-text name.

    Approximate by construction: the name itself is never uploaded (spec 1, "two
    columns that must not be uploaded"), so this five-value guess is what a
    session's hardware mix looks like from telemetry instead of the name.
    """
    if not name:
        return "unknown"
    lowered = name.lower()
    if any(hint in lowered for hint in _BLUETOOTH_HINTS):
        return "bluetooth"
    if any(hint in lowered for hint in _USB_HINTS):
        return "usb"
    if any(hint in lowered for hint in _VIRTUAL_HINTS):
        return "virtual"
    if any(hint in lowered for hint in _BUILTIN_HINTS):
        return "builtin"
    return "unknown"


# Lower-cased name -> the engine's own spelling, for every voice that may be
# recorded as itself. Keyed by engine because a name is only known for the engine
# that ships it; `command` has none, so every voice it is given is `custom`.
_KNOWN_VOICES: dict[str, dict[str, str]] = {
    engine: {name.lower(): name for name in names}
    for engine, names in (("say", say.KNOWN_VOICES), ("nemo", nemo.KNOWN_VOICES))
}
CUSTOM_VOICE = "custom"


def recorded_voice(engine: str, voice: str | None) -> str | None:
    """The voice as an `out` row may carry it: a known name in the engine's own
    spelling, `custom` for any other name, `None` when the engine's default ran.

    A voice name is free text - `WALKIE_VOICE`, a `speak(voice=...)` argument, a
    third-party voice installed for `say` - and free text never ships.
    """
    if not voice:
        return None
    return _KNOWN_VOICES.get(engine, {}).get(voice.lower(), CUSTOM_VOICE)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wav_duration_ms(wav_bytes: bytes) -> int | None:
    try:
        with wave.open(io.BytesIO(wav_bytes)) as handle:
            frames: int = handle.getnframes()
            rate: int = handle.getframerate()
    except (wave.Error, EOFError) as error:
        logger.debug("could not read WAV duration: %s", error)
        return None
    if rate <= 0:
        return None
    return round(frames / rate * 1000)


# The contract's ceilings on `audio_ms`, `asr_ms`, `words` and `chars` for every source
# walkie sends (`speak`, `listen`, `talk`: the contract's `else` branch, everything but
# `transcribe`). The server answers a value above one with a 400 and the shipper sets
# the whole chunk aside, so a `listen` recording past ten minutes
# (`WALKIE_LISTEN_MAX_SECONDS` above 600) or an outsized `speak` utterance is clamped
# here rather than costing every row shipped beside it.
ROW_MAX_AUDIO_MS = 600_000
ROW_MAX_ASR_MS = 120_000
ROW_MAX_WORDS = 20_000
ROW_MAX_CHARS = 150_000

# The `out` row's timings, from the same contract. A sentence stuck behind a wedged
# queue, or a player that hangs, would otherwise measure past them.
MAX_QUEUE_WAIT_MS = 300_000
MAX_SYNTH_MS = 120_000
MAX_PLAY_MS = 600_000

# `harness_version` is whatever the MCP client declares about itself; the contract
# caps its length, and the session row travels with every chunk.
HARNESS_VERSION_MAX_LENGTH = 64


def _within(value: int | None, ceiling: int) -> int | None:
    """Inside [0, ceiling]: the contract's minimum is as binding as its maximum."""
    if value is None:
        return None
    return min(max(value, 0), ceiling)


@dataclass(slots=True)
class TelemetrySession:
    """One session's write path into the local store.

    `tts_engine`/`tts_model` describe `out` rows; `asr_engine`/`asr_model` describe
    `in` rows - the contract's generic `engine`/`model` columns mean different
    things depending on direction, and this is where that distinction is made.
    """

    conn: sqlite3.Connection
    install_id: str
    session_id: str
    tts_engine: str
    tts_model: str | None
    asr_engine: str | None
    asr_model: str | None
    record_audio: bool = False
    recordings_dir: Path | None = None
    db_path: Path | None = None

    def utterance_finished(self, outcome: UtteranceOutcome) -> None:
        """Record one utterance `speak` produced - the queue's `on_finish` hook."""
        try:
            self._write_utterance(outcome)
        except Exception:
            logger.debug("telemetry: failed to record a spoken utterance", exc_info=True)

    def heard(
        self,
        *,
        source: str,
        status: str,
        transcript: str | None = None,
        device_name: str | None = None,
        asr_ms: int | None = None,
        wav: bytes | None = None,
    ) -> None:
        """Record one `listen` or `/walkie:talk` attempt, however far it got."""
        try:
            self._write_heard(
                source=source,
                status=status,
                transcript=transcript,
                device_name=device_name,
                asr_ms=asr_ms,
                wav=wav,
            )
        except Exception:
            logger.debug("telemetry: failed to record a heard utterance", exc_info=True)

    def close(self) -> None:
        try:
            store.end_session(self.conn, self.session_id, store.now_iso())
        except Exception:
            logger.debug("telemetry: failed to close the session row", exc_info=True)

    def update_harness(self, harness: str, harness_version: str | None) -> None:
        """Correct the harness the session row was opened with, once spec 2's
        better source (MCP `client_info`) is known."""
        if harness_version is not None:
            harness_version = harness_version[:HARNESS_VERSION_MAX_LENGTH]
        try:
            store.update_session_harness(self.conn, self.session_id, harness, harness_version)
        except Exception:
            logger.debug("telemetry: failed to update the session's harness", exc_info=True)

    # -- internals, unguarded: callers above catch everything -----------------

    def _write_utterance(self, outcome: UtteranceOutcome) -> None:
        # A fallback reports the engine that actually spoke; the configured model
        # belongs to the configured engine and says nothing about any other.
        engine = outcome.engine or self.tts_engine
        model = self.tts_model if engine == self.tts_engine else None
        row = {
            "utterance_id": str(uuid.uuid4()),
            "session_id": self.session_id,
            "install_id": self.install_id,
            "direction": "out",
            "source": "speak",
            "occurred_at": store.now_iso(),
            "engine": engine,
            "model": model,
            "voice": recorded_voice(engine, outcome.voice),
            "intent": outcome.intent or "unspecified",
            "words": _within(len(outcome.text.split()), ROW_MAX_WORDS),
            "chars": _within(len(outcome.text), ROW_MAX_CHARS),
            "audio_ms": _within(outcome.audio_ms, ROW_MAX_AUDIO_MS),
            "queue_wait_ms": _within(outcome.queue_wait_ms, MAX_QUEUE_WAIT_MS),
            "synth_ms": _within(outcome.synth_ms, MAX_SYNTH_MS),
            "play_ms": _within(outcome.play_ms, MAX_PLAY_MS),
            "status": outcome.status,
            "text": outcome.text,
            "text_sha256": _sha256_text(outcome.text),
        }
        store.insert_row(self.conn, SCHEMA.rows, row)

    def _write_heard(
        self,
        *,
        source: str,
        status: str,
        transcript: str | None,
        device_name: str | None,
        asr_ms: int | None,
        wav: bytes | None,
    ) -> None:
        audio_ms = wav_duration_ms(wav) if wav else None
        row: dict[str, object] = {
            "utterance_id": str(uuid.uuid4()),
            "session_id": self.session_id,
            "install_id": self.install_id,
            "direction": "in",
            "source": source,
            "occurred_at": store.now_iso(),
            "engine": self.asr_engine,
            "model": self.asr_model,
            "device_kind": classify_device(device_name),
            "words": _within(len(transcript.split()) if transcript else None, ROW_MAX_WORDS),
            "chars": _within(len(transcript) if transcript else None, ROW_MAX_CHARS),
            "audio_ms": _within(audio_ms, ROW_MAX_AUDIO_MS),
            "asr_ms": _within(asr_ms, ROW_MAX_ASR_MS),
            "status": status,
            "text": transcript,
            "text_sha256": _sha256_text(transcript) if transcript else None,
            "device_name": device_name,
        }
        if self.record_audio and wav and self.recordings_dir is not None:
            utterance_id = str(row["utterance_id"])
            path, digest = self._store_recording(self.recordings_dir, utterance_id, wav)
            if path is not None:
                row["audio_path"] = str(path)
                row["audio_sha256"] = digest
        store.insert_row(self.conn, SCHEMA.rows, row)

    def _store_recording(
        self, directory: Path, utterance_id: str, wav_bytes: bytes
    ) -> tuple[Path | None, str | None]:
        """Write one recording to disk when the user opted in. Never uploaded under
        any setting (spec 6); a write failure here must not cost the telemetry row."""
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{utterance_id}.wav"
            path.write_bytes(wav_bytes)
        except OSError as error:
            logger.debug("could not save recording: %s", error)
            return None, None
        return path, _sha256_bytes(wav_bytes)
