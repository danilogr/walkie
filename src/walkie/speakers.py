"""Holding the machine's speakers for one recording.

Every process that plays speech takes speak-core's speaker lock around each utterance.
A recording takes the same lock for as long as the microphone is open, so another
plugin reading aloud pauses between two of its sentences instead of being recorded,
and this plugin's own next sentence waits for the recording to end.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from speak_core.queue import Speaker

# One sentence another process is playing finishes well inside this. A lock still held
# after it is a player that is not going to stop, and the recording is refused rather
# than left waiting with no end.
SPEAKER_WAIT_S = 60.0


class SpeakersBusyError(RuntimeError):
    """The speakers were held, by another process or this session's own speech, for longer
    than a recording may wait."""

    def __init__(self, waited: float) -> None:
        super().__init__(
            f"the speakers stayed busy for {waited:g} s, so the microphone was not "
            "opened. Try again, or stop the speech that is playing."
        )
        self.waited = waited


@asynccontextmanager
async def holding(speaker: Speaker, *, wait: float | None = None) -> AsyncIterator[None]:
    """Hold the speakers for the body, after waiting up to `wait` seconds for them
    (`SPEAKER_WAIT_S` when not given).

    Raises:
        SpeakersBusyError: when they did not come free in time. Nothing is held then.
    """
    limit = SPEAKER_WAIT_S if wait is None else wait
    gave_up = asyncio.Event()
    timer = asyncio.get_running_loop().call_later(limit, gave_up.set)
    try:
        held = await speaker.acquire(gave_up)
    finally:
        timer.cancel()
    if not held:
        raise SpeakersBusyError(limit)
    try:
        yield
    finally:
        speaker.release()
