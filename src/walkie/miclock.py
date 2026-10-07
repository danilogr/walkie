"""Exclusive claim on the one microphone the machine has.

Sessions are separate processes with no other way to see each other, so they
coordinate through the filesystem the way the speech server already does: an atomic
`mkdir` elects one holder, a lock whose owner has died is reclaimed, and a lock with no
owner yet is another session's claim in progress until it has gone `OWNERLESS_GRACE_S`
unchanged.
"""

from collections.abc import Callable
from pathlib import Path

from speak_core.exclusive import ClaimInProgressError, ExclusiveLock

# How long a `mic` directory with no owner file must go unchanged before it is taken as
# left by a session that died mid-claim. Until then another session is between its
# `mkdir` and its owner write, and taking it would put two recordings on one microphone.
# speak-core's speaker lock waits the same window for the same reason.
OWNERLESS_GRACE_S = 2.0


class MicrophoneBusy(RuntimeError):  # noqa: N818 - reads as a state, not a failure mode
    """Another live session is recording, or is claiming the microphone right now."""

    def __init__(self, owner: int | None) -> None:
        holder = f"another session (pid {owner})" if owner is not None else "another session"
        super().__init__(f"{holder} is listening; only one can use the microphone")
        self.owner = owner


class MicLock(ExclusiveLock):
    """Exclusive claim on the one microphone the machine has."""

    def __init__(
        self,
        *,
        state_dir: Path,
        is_alive: Callable[[int], bool],
        pid: int | None = None,
    ) -> None:
        super().__init__(
            directory=Path(state_dir) / "mic",
            is_alive=is_alive,
            busy=MicrophoneBusy,
            pid=pid,
            ownerless_grace=OWNERLESS_GRACE_S,
        )

    def acquire(self) -> None:
        """Claim the microphone, or raise `MicrophoneBusy` - for a live holder, and for a
        claim another session has in progress."""
        try:
            super().acquire()
        except ClaimInProgressError as error:
            raise MicrophoneBusy(None) from error
