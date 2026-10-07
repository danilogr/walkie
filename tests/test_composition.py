"""What the composition root decides: who gets a speech server, with which models, and
which lock a recording and the speech queue share."""

import asyncio
from pathlib import Path

from speak_core.config import ServerSettings, VoiceSettings
from speak_core.speaker import SpeakerLock

from fakes import FakePlayer, FakeSpeaker
from walkie import __main__ as entry
from walkie.__main__ import build_ears, build_supervisor
from walkie.config import Settings
from walkie.cue import END_SOUND
from walkie.listening import transcription_timeout
from walkie.speakers import holding


def test_every_session_gets_a_speech_server_because_listening_always_needs_one():
    """Even a `say` session: the microphone transcribes against the shared server."""
    assert build_supervisor(Settings()) is not None
    nemo = Settings(speech=VoiceSettings(prefix="WALKIE", engine="nemo"))
    assert build_supervisor(nemo) is not None


def test_autostart_off_leaves_the_speech_server_to_the_user():
    assert build_supervisor(Settings(server=ServerSettings(autostart=False))) is None


def test_every_session_is_served_the_configured_asr_model():
    """Listening is unconditional, so the transcription model is always requested.
    A model that will not load is handled at startup, not by withholding it here."""
    supervisor = build_supervisor(Settings(server=ServerSettings(asr_model="parakeet-tdt")))
    assert supervisor is not None
    args = supervisor._server_args()
    assert args[args.index("--asr-model") + 1] == "parakeet-tdt"


def test_there_are_always_ears():
    """`/walkie:converse` and `/walkie:talk` cannot depend on a switch the user has to find."""
    assert build_ears(Settings(), speaker=FakeSpeaker()) is not None


def test_the_ears_carry_the_configured_capture_limits():
    ears = build_ears(Settings(listen_max_seconds=5.0, listen_timeout=2.0), speaker=FakeSpeaker())
    assert ears.limits.max_ms == 5_000
    assert ears.limits.start_timeout_ms == 2_000


def test_the_transcriber_is_given_a_timeout_the_recording_cap_cannot_outlast():
    """Nothing else sets it, and the default cap is four minutes of audio."""
    settings = Settings(listen_max_seconds=240.0)
    ears = build_ears(settings, speaker=FakeSpeaker())
    assert ears.transcriber._timeout == transcription_timeout(settings)


def test_the_ears_carry_a_cue_that_is_on_by_default():
    assert build_ears(Settings(), speaker=FakeSpeaker()).cue._enabled is True


def test_the_ears_carry_the_configured_cue_sounds():
    """The defaults are macOS paths, so the override is the only way off it."""
    ears = build_ears(
        Settings(listen_cue=False, listen_cue_start=Path("/s/in.wav")), speaker=FakeSpeaker()
    )
    assert ears.cue._enabled is False
    assert (ears.cue._start, ears.cue._end) == (Path("/s/in.wav"), END_SOUND)


def test_listening_and_speaking_share_one_speaker_lock(monkeypatch, tmp_path):
    """One lock, so a recording and this session's own next sentence take turns."""
    served: dict[str, object] = {}

    def create_server(**kwargs: object) -> object:
        served.update(kwargs)
        return object()

    monkeypatch.setattr(entry, "create_server", create_server)
    settings = Settings.from_env(
        {
            "HOME": str(tmp_path),
            "WALKIE_STATE_DIR": str(tmp_path / "state"),
            "SPEAK_CORE_STATE_DIR": str(tmp_path / "core"),
            "NEMO_AUTOSTART": "0",
            "WALKIE_ENGINE": "command",
            "WALKIE_COMMAND": "true",
        }
    )
    entry.build(settings)

    speaker = served["ears"].speaker  # type: ignore[attr-defined]
    assert isinstance(speaker, SpeakerLock)
    assert speaker is served["queue"]._speaker  # type: ignore[attr-defined]


async def test_the_sessions_own_speech_waits_while_a_recording_holds_the_speakers(
    monkeypatch, tmp_path
):
    """The queue and the ears are wired to one lock: with listen holding it, the next
    sentence is not played until the recording gives the speakers back."""
    served: dict[str, object] = {}
    monkeypatch.setattr(entry, "create_server", lambda **kwargs: served.update(kwargs))
    settings = Settings.from_env(
        {
            "HOME": str(tmp_path),
            "WALKIE_STATE_DIR": str(tmp_path / "state"),
            "SPEAK_CORE_STATE_DIR": str(tmp_path / "core"),
            "NEMO_AUTOSTART": "0",
            "WALKIE_ENGINE": "command",
            "WALKIE_COMMAND": "true",
        }
    )
    entry.build(settings)
    queue = served["queue"]
    player = FakePlayer()
    queue._spawn = player.spawn  # type: ignore[attr-defined]
    worker = asyncio.create_task(queue.run())  # type: ignore[attr-defined]
    try:
        async with holding(served["ears"].speaker):  # type: ignore[attr-defined]
            queue.enqueue("hello", voice=None, rate=None)  # type: ignore[attr-defined]
            await asyncio.sleep(0.3)
            assert player.commands == []
        for _ in range(500):
            if player.commands:
                break
            await asyncio.sleep(0.01)
        assert len(player.commands) == 1
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_talk_builds_its_collaborators_the_way_the_server_does(monkeypatch):
    """`/walkie:talk` wires up its own objects, and nothing else exercises that.

    The transcriber block is character-identical to the one in `__main__`, which is the
    risk: `tts_model` and `asr_model` are both `str`, so handing the speech model to the
    transcriber would transcribe against a voice and is caught by neither mypy nor any
    other test. Two call sites, so the answer is to pin it rather than extract a shared
    builder.
    """
    import walkie.talk as talk

    # `_run` also builds a telemetry session from the real environment; forcing it off
    # keeps this test from touching the machine's actual config directory.
    monkeypatch.setenv("WALKIE_TELEMETRY", "off")

    seen: dict[str, object] = {}

    async def capture_arguments(settings, **collaborators: object) -> str:
        seen.update(collaborators)
        return "a transcript"

    monkeypatch.setattr(talk, "dictate", capture_arguments)
    settings = Settings(
        server=ServerSettings(
            url="http://127.0.0.1:9999",
            tts_model="magpie",
            asr_model="parakeet-tdt",
            shared_dir=Path("/tmp/walkie-test-core"),
        ),
        listen_max_seconds=30.0,
        state_dir=Path("/tmp/walkie-test"),
    )

    assert await talk._run(settings) == "a transcript"

    transcriber = seen["transcriber"]
    assert transcriber._base_url == "http://127.0.0.1:9999"
    assert transcriber._model == "parakeet-tdt"
    assert transcriber._timeout == transcription_timeout(settings)

    supervisor = seen["supervisor"]
    assert supervisor._asr_model == "parakeet-tdt"
    assert supervisor._model == "magpie"
    assert supervisor._port == 9999

    assert seen["lock"]._dir == Path("/tmp/walkie-test") / "mic"
    assert seen["speaker"]._shared_dir == Path("/tmp/walkie-test-core")
    assert seen["cue"]._end == END_SOUND
    assert seen["recorder"]._device is None
