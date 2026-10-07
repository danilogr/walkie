"""walkie's telemetry session for one process: the install brought up to date by
`wiring.start_install`, then walkie's own `sessions` row. Shared by `__main__` and
`talk`, which read the real environment and pass it in. Never raises: telemetry must
not stop walkie."""

import logging
import re
import sqlite3
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path

from speak_core.telemetry import store, wiring

from walkie.config import Settings
from walkie.telemetry.contract import IDENTITY, SCHEMA, db_path
from walkie.telemetry.session import TelemetrySession

logger = logging.getLogger(__name__)

RECORDINGS_DIRNAME = "recordings"
# The contract's lengths for `tts_engine` and `model`.
TTS_ENGINE_MAX_LENGTH = 32
MODEL_MAX_LENGTH = 64
# The contract's release version: the only `plugin_version` its install ping accepts.
RELEASE_VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,6}")

# SQLite's answers for a file that is not, or no longer, a database: the store is
# damaged, not busy or out of reach.
_CORRUPT = frozenset({sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB})
# What a damaged store is renamed to, beside it, with SQLite's own sidecar files.
CORRUPT_SUFFIX = ".corrupt"
_SIDECARS = ("", "-journal", "-wal", "-shm")


def is_corrupt(error: sqlite3.Error) -> bool:
    """Whether `error` says the store's file is damaged."""
    code = getattr(error, "sqlite_errorcode", None)
    # The extended code carries the primary one in its low byte.
    return isinstance(code, int) and code & 0xFF in _CORRUPT


def set_aside(path: Path) -> None:
    """Rename a damaged store and its sidecars to `<name>.corrupt*`, replacing an earlier
    one, so the next connection starts an empty store.

    Raises:
        OSError: a file could not be renamed.
    """
    for sidecar in _SIDECARS:
        found = path.with_name(path.name + sidecar)
        if found.exists():
            found.replace(path.with_name(path.name + CORRUPT_SUFFIX + sidecar))


def is_release(plugin_version: str) -> bool:
    """Whether this build may send anything. A development build (`1.1.0.dev0`)
    collects locally but sends nothing, rather than having every request refused."""
    return RELEASE_VERSION.fullmatch(plugin_version) is not None


def _model(name: str) -> str | None:
    """A model name as a row may carry it: left out, not cut, when it is longer than
    the contract allows, because a cut name is a different and wrong one."""
    return name if len(name) <= MODEL_MAX_LENGTH else None


def build(
    env: Mapping[str, str],
    *,
    settings: Settings,
    plugin_version: str,
    host_platform: str | None = None,
) -> TelemetrySession | None:
    """The telemetry session for one process, or `None` when telemetry does not collect
    or its store cannot be used."""
    platform_name = host_platform if host_platform is not None else sys.platform
    path = db_path(settings.state_dir)

    def start() -> wiring.Install | None:
        return wiring.start_install(
            env,
            IDENTITY,
            SCHEMA,
            db_path=path,
            plugin_version=plugin_version,
            host_platform=platform_name,
        )

    try:
        try:
            install = start()
        except sqlite3.Error as error:
            if not is_corrupt(error):
                raise
            # Damaged for good: left in place, it would stop collection in every session
            # from now on. Its unshipped rows are lost with it.
            set_aside(path)
            logger.warning(
                "telemetry: the local store was damaged (%s); moved to %s%s, starting anew",
                error,
                path.name,
                CORRUPT_SUFFIX,
            )
            install = start()
    except (OSError, sqlite3.Error) as error:
        # A locked or unreachable store must not stop walkie: telemetry is optional.
        logger.warning("telemetry: the local store is unusable; collecting nothing: %s", error)
        return None
    if install is None:
        return None

    harness, harness_version = wiring.detect_harness(env, IDENTITY)
    tts_engine = settings.speech.engine[:TTS_ENGINE_MAX_LENGTH]
    session_id = str(uuid.uuid4())
    try:
        store.insert_session(
            install.conn,
            SCHEMA,
            {
                "session_id": session_id,
                "install_id": install.consent.install_id,
                "started_at": store.now_iso(),
                "plugin_version": plugin_version,
                "tts_engine": tts_engine,
                "asr_engine": "nemo",
                # Always true: listening is part of walkie. The contract requires it.
                "listen_enabled": True,
                "harness": harness,
                "harness_version": harness_version,
            },
        )
    except sqlite3.Error as error:
        logger.warning("telemetry: could not record the session; collecting nothing: %s", error)
        install.conn.close()
        return None
    return TelemetrySession(
        conn=install.conn,
        install_id=install.consent.install_id,
        session_id=session_id,
        tts_engine=tts_engine,
        tts_model=_model(settings.server.tts_model) if settings.speech.engine == "nemo" else None,
        asr_engine="nemo",
        asr_model=_model(settings.server.asr_model),
        record_audio=install.consent.record,
        recordings_dir=IDENTITY.config_dir(env, host_platform=platform_name) / RECORDINGS_DIRNAME,
        db_path=path,
    )
