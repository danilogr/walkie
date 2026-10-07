import os
import time

import pytest

from walkie.miclock import MicLock, MicrophoneBusy


def build(tmp_path, pid: int = 100, alive: bool = True) -> MicLock:
    return MicLock(state_dir=tmp_path, pid=pid, is_alive=lambda _: alive)


def age(path, seconds: float = 10.0) -> None:
    """Make a lock directory look untouched for `seconds`."""
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_acquire_records_the_owning_pid(tmp_path):
    build(tmp_path, pid=123).acquire()
    assert (tmp_path / "mic" / "owner").read_text() == "123"


def test_a_second_live_session_is_refused(tmp_path):
    build(tmp_path, pid=123).acquire()
    with pytest.raises(MicrophoneBusy) as caught:
        build(tmp_path, pid=456).acquire()
    assert caught.value.owner == 123
    assert "123" in str(caught.value)


def test_a_lock_whose_owner_is_gone_is_reclaimed(tmp_path):
    build(tmp_path, pid=123).acquire()
    build(tmp_path, pid=456, alive=False).acquire()
    assert (tmp_path / "mic" / "owner").read_text() == "456"


def test_reacquiring_from_the_same_process_is_allowed(tmp_path):
    lock = build(tmp_path, pid=123)
    lock.acquire()
    lock.acquire()
    assert lock.owner() == 123


def test_an_ownerless_lock_is_a_claim_in_progress_not_a_free_microphone(tmp_path):
    """Another session is between its `mkdir` and its owner write. Taking the lock now
    would put two recordings on one microphone."""
    (tmp_path / "mic").mkdir(parents=True)
    with pytest.raises(MicrophoneBusy) as caught:
        build(tmp_path, pid=456).acquire()
    assert caught.value.owner is None
    assert str(caught.value) == "another session is listening; only one can use the microphone"


def test_an_ownerless_lock_left_long_enough_is_reclaimed(tmp_path):
    """Only a session that died mid-claim leaves one unchanged for the whole grace."""
    (tmp_path / "mic").mkdir(parents=True)
    age(tmp_path / "mic")
    build(tmp_path, pid=456).acquire()
    assert (tmp_path / "mic" / "owner").read_text() == "456"


def test_an_unreadable_owner_file_is_reclaimed_once_it_is_stale(tmp_path):
    (tmp_path / "mic").mkdir(parents=True)
    (tmp_path / "mic" / "owner").write_text("not a pid")
    age(tmp_path / "mic")
    build(tmp_path, pid=456).acquire()
    assert (tmp_path / "mic" / "owner").read_text() == "456"


def test_release_frees_the_lock_for_the_next_session(tmp_path):
    lock = build(tmp_path, pid=123)
    lock.acquire()
    lock.release()
    assert not (tmp_path / "mic").exists()
    build(tmp_path, pid=456).acquire()


def test_release_by_a_non_owner_leaves_the_lock_alone(tmp_path):
    build(tmp_path, pid=123).acquire()
    build(tmp_path, pid=456).release()
    assert (tmp_path / "mic" / "owner").read_text() == "123"


def test_the_context_manager_releases_even_when_the_body_raises(tmp_path):
    with pytest.raises(RuntimeError), build(tmp_path, pid=123):
        raise RuntimeError("boom")
    assert not (tmp_path / "mic").exists()
