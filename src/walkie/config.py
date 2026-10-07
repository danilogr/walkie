"""walkie's settings, read once from the environment and validated there.

It embeds the settings every plugin reads the same way - the shared speech server's,
and a voice read under `WALKIE_` - and adds its own listening settings and state
directory. Like `speak_core.config`, it never reads `os.environ` itself.
"""

import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from speak_core.config import (
    ServerSettings,
    VoiceSettings,
    env_flag,
    env_path,
    env_positive,
    env_text,
    plugin_state_dir,
)

logger = logging.getLogger(__name__)

PLUGIN = "walkie"
PREFIX = "WALKIE"

# walkie speaks with no setup: `say` is on every Mac. `WALKIE_ENGINE=nemo` asks for the
# neural voice once `/walkie:setup` has installed it.
DEFAULT_ENGINE = "say"


def _default_speech() -> VoiceSettings:
    return VoiceSettings(prefix=PREFIX, engine=DEFAULT_ENGINE)


def _speech(env: Mapping[str, str]) -> VoiceSettings:
    """The voice settings, with a `command` engine that names no command replaced by the
    default: speak-core refuses to build it, and the server would never start."""
    speech = VoiceSettings.from_env(env, prefix=PREFIX, default_engine=DEFAULT_ENGINE)
    if speech.engine == "command" and not (speech.command or "").split():
        logger.warning(
            "%s=command needs %s; speaking with %s instead",
            speech.key("ENGINE"),
            speech.key("COMMAND"),
            DEFAULT_ENGINE,
        )
        return replace(speech, engine=DEFAULT_ENGINE)
    return speech


@dataclass(frozen=True, slots=True)
class Settings:
    server: ServerSettings = field(default_factory=ServerSettings)
    speech: VoiceSettings = field(default_factory=_default_speech)
    listen_silence_ms: float = 3000.0
    listen_max_seconds: float = 240.0
    listen_timeout: float = 10.0
    listen_language: str | None = None
    listen_cue: bool = True
    # None means the sound `cue` picks for itself; only an override lands here.
    listen_cue_start: Path | None = None
    listen_cue_end: Path | None = None
    listen_cue_empty: Path | None = None
    # A named input is never fallen back off; unset means search from the OS default.
    input_device: str | None = None
    state_dir: Path = Path()

    @classmethod
    def from_env(cls, env: Mapping[str, str], *, platform: str | None = None) -> "Settings":
        platform = platform if platform is not None else sys.platform
        return cls(
            server=ServerSettings.from_env(env, platform=platform),
            speech=_speech(env),
            listen_silence_ms=env_positive(env, "WALKIE_LISTEN_SILENCE_MS", 3000.0),
            listen_max_seconds=env_positive(env, "WALKIE_LISTEN_MAX_SECONDS", 240.0),
            listen_timeout=env_positive(env, "WALKIE_LISTEN_TIMEOUT", 10.0),
            listen_language=env_text(env, "WALKIE_LISTEN_LANGUAGE"),
            listen_cue=env_flag(env, "WALKIE_LISTEN_CUE", default=True),
            listen_cue_start=env_path(env, "WALKIE_LISTEN_CUE_START"),
            listen_cue_end=env_path(env, "WALKIE_LISTEN_CUE_END"),
            listen_cue_empty=env_path(env, "WALKIE_LISTEN_CUE_EMPTY"),
            input_device=env_text(env, "WALKIE_INPUT_DEVICE"),
            state_dir=plugin_state_dir(
                env, name=PLUGIN, override="WALKIE_STATE_DIR", platform=platform
            ),
        )
