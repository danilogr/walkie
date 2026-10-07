"""walkie's settings: the shared server's, its voice under WALKIE_, its listening
settings, and its own state directory."""

from pathlib import Path

from walkie.config import DEFAULT_ENGINE, PREFIX, Settings


def test_the_voice_is_read_under_walkie():
    speech = Settings.from_env(
        {"WALKIE_ENGINE": "nemo", "WALKIE_VOICE": "Sofia", "SPEAK_VOICE": "Samantha"}
    ).speech
    assert (speech.prefix, speech.engine, speech.voice) == ("WALKIE", "nemo", "Sofia")


def test_the_engine_defaults_to_say():
    assert Settings.from_env({}).speech.engine == "say"
    assert Settings().speech.prefix == PREFIX == "WALKIE"


def test_the_command_engine_without_a_command_falls_back_to_the_default_engine(caplog):
    with caplog.at_level("WARNING"):
        settings = Settings.from_env({"WALKIE_ENGINE": "command", "WALKIE_COMMAND": "  "})
    assert settings.speech.engine == DEFAULT_ENGINE == "say"
    assert "WALKIE_COMMAND" in caplog.text and "WALKIE_ENGINE=command" in caplog.text
    assert len(caplog.records) == 1


def test_the_command_engine_keeps_its_command():
    settings = Settings.from_env({"WALKIE_ENGINE": "command", "WALKIE_COMMAND": "espeak"})
    assert (settings.speech.engine, settings.speech.command) == ("command", "espeak")


def test_the_server_settings_are_the_shared_ones():
    assert Settings.from_env({"NEMO_BIN": "/opt/nemo"}).server.binary == "/opt/nemo"


def test_the_plugin_and_shared_state_dirs_are_different_directories():
    settings = Settings.from_env({"HOME": "/Users/x"}, platform="darwin")
    assert settings.state_dir == Path("/Users/x/Library/Caches/walkie")
    assert settings.server.shared_dir == Path("/Users/x/Library/Caches/speak-core")


def test_state_dir_follows_xdg_elsewhere():
    settings = Settings.from_env({"XDG_CACHE_HOME": "/cache"}, platform="linux")
    assert settings.state_dir == Path("/cache/walkie")


def test_state_dir_can_be_overridden():
    settings = Settings.from_env({"WALKIE_STATE_DIR": "/tmp/state"}, platform="darwin")
    assert settings.state_dir == Path("/tmp/state")


def test_the_listen_cue_is_on_unless_it_is_turned_off():
    assert Settings.from_env({}).listen_cue is True
    for raw in ("0", "false", "FALSE", "no", "off"):
        assert Settings.from_env({"WALKIE_LISTEN_CUE": raw}).listen_cue is False, raw


def test_anything_else_leaves_the_listen_cue_on():
    for raw in ("1", "true", "on", "", "maybe"):
        assert Settings.from_env({"WALKIE_LISTEN_CUE": raw}).listen_cue is True, raw


def test_the_cue_sounds_can_be_pointed_elsewhere():
    """The defaults are macOS paths, so an override is the only way this works off it."""
    settings = Settings.from_env(
        {"WALKIE_LISTEN_CUE_START": "/sounds/in.wav", "WALKIE_LISTEN_CUE_END": "/sounds/out.wav"}
    )
    assert settings.listen_cue_start == Path("/sounds/in.wav")
    assert settings.listen_cue_end == Path("/sounds/out.wav")


def test_unset_cue_sounds_are_left_to_the_cue_module():
    settings = Settings.from_env({"WALKIE_LISTEN_CUE_START": ""})
    assert settings.listen_cue_start is None
    assert settings.listen_cue_end is None
    assert settings.listen_cue_empty is None


def test_the_empty_capture_sound_can_be_pointed_elsewhere():
    settings = Settings.from_env({"WALKIE_LISTEN_CUE_EMPTY": "/sounds/nothing.wav"})
    assert settings.listen_cue_empty == Path("/sounds/nothing.wav")


def test_an_input_device_can_be_named():
    assert Settings.from_env({"WALKIE_INPUT_DEVICE": "USB Headset"}).input_device == "USB Headset"


def test_no_named_input_device_means_search_from_the_default():
    assert Settings.from_env({}).input_device is None


def test_listen_numbers_have_defaults():
    settings = Settings.from_env({})
    assert settings.listen_silence_ms == 3000
    assert settings.listen_max_seconds == 240
    assert settings.listen_timeout == 10


def test_unparsable_listen_numbers_fall_back_to_the_default():
    assert Settings.from_env({"WALKIE_LISTEN_SILENCE_MS": "soon"}).listen_silence_ms == 3000


def test_non_positive_listen_numbers_fall_back_to_the_default():
    assert Settings.from_env({"WALKIE_LISTEN_MAX_SECONDS": "-5"}).listen_max_seconds == 240


def test_listen_language_is_optional():
    assert Settings.from_env({}).listen_language is None
    assert Settings.from_env({"WALKIE_LISTEN_LANGUAGE": "en"}).listen_language == "en"


def test_a_non_finite_listen_number_falls_back_to_the_default():
    """nan passes every `<= 0` check, and a nan limit records forever."""
    for raw in ("nan", "inf", "-inf"):
        assert Settings.from_env({"WALKIE_LISTEN_MAX_SECONDS": raw}).listen_max_seconds == 240
        assert Settings.from_env({"WALKIE_LISTEN_TIMEOUT": raw}).listen_timeout == 10
