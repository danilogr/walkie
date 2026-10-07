"""A recording holds the machine's speakers for as long as the microphone is open."""

import asyncio

import pytest
from speak_core.speaker import SpeakerLock

from fakes import FakeSpeaker
from walkie import speakers
from walkie.speakers import SpeakersBusyError, holding


async def test_the_speakers_are_held_for_the_body_and_given_back():
    speaker = FakeSpeaker()
    async with holding(speaker):
        assert speaker.held
    assert not speaker.held
    assert (speaker.acquires, speaker.releases) == (1, 1)


async def test_they_are_given_back_when_the_body_raises():
    speaker = FakeSpeaker()
    with pytest.raises(RuntimeError, match="microphone"):
        async with holding(speaker):
            raise RuntimeError("the microphone failed")
    assert (speaker.held, speaker.releases) == (False, 1)


async def test_speakers_that_never_come_free_refuse_without_holding_anything():
    speaker = FakeSpeaker(busy=True)
    with pytest.raises(SpeakersBusyError, match="the speakers stayed busy"):
        async with holding(speaker, wait=0.05):
            raise AssertionError("the body must not run")
    assert speaker.releases == 0


async def test_the_wait_is_the_module_limit_unless_given(monkeypatch):
    monkeypatch.setattr(speakers, "SPEAKER_WAIT_S", 0.05)
    with pytest.raises(SpeakersBusyError) as refused:
        async with holding(FakeSpeaker(busy=True)):
            pass
    assert refused.value.waited == 0.05


async def test_another_process_cannot_play_while_a_recording_holds_the_speakers(tmp_path):
    """Two real locks over one shared directory, as two processes have them: one held
    for a recording, one standing in for voicebox reading aloud."""
    recording = SpeakerLock(shared_dir=tmp_path, pid=111, is_alive=lambda pid: True, poll=0.01)
    reader = SpeakerLock(shared_dir=tmp_path, pid=222, is_alive=lambda pid: True, poll=0.01)

    async with holding(recording):
        gave_up = asyncio.Event()
        asyncio.get_running_loop().call_later(0.2, gave_up.set)
        assert await reader.acquire(gave_up) is False

    assert await asyncio.wait_for(reader.acquire(asyncio.Event()), timeout=5) is True
    reader.release()


async def test_a_recording_waits_for_a_sentence_another_process_is_playing(tmp_path):
    reader = SpeakerLock(shared_dir=tmp_path, pid=222, is_alive=lambda pid: True, poll=0.01)
    recording = SpeakerLock(shared_dir=tmp_path, pid=111, is_alive=lambda pid: True, poll=0.01)
    assert await reader.acquire(asyncio.Event()) is True
    entered = asyncio.Event()

    async def record() -> None:
        async with holding(recording, wait=5):
            entered.set()

    task = asyncio.create_task(record())
    await asyncio.sleep(0.1)
    assert not entered.is_set()

    reader.release()
    await asyncio.wait_for(task, timeout=5)
    assert entered.is_set()
