"""`__main__.build()` and `talk._run()` decide whether a process collects, pings and
ships: nothing before the first-run notice, nothing under DO_NOT_TRACK, nothing sent by
a build that is not a release, and never a failure because the store is broken."""

import asyncio
import sys
from pathlib import Path

import pytest
from speak_core.telemetry import notice

from walkie import __main__ as entry
from walkie import talk
from walkie.config import Settings
from walkie.telemetry import compose
from walkie.telemetry.contract import IDENTITY
from walkie.telemetry.notice import TEXT


def env_for(tmp_path: Path, **extra: str) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "WALKIE_STATE_DIR": str(tmp_path / "state"),
        "SPEAK_CORE_STATE_DIR": str(tmp_path / "core"),
        "WALKIE_ENGINE": "command",
        "WALKIE_COMMAND": "true",
        "NEMO_AUTOSTART": "0",
        **extra,
    }


def mark_notice_shown(env: dict[str, str]) -> None:
    assert notice.mark_shown(env, IDENTITY, host_platform=sys.platform)


def unopenable_store(tmp_path: Path) -> None:
    """A directory where the store should be: SQLite cannot open it, and it is not damage
    that setting the file aside would cure."""
    (tmp_path / "state" / "telemetry.db").mkdir(parents=True)


def corrupt_store(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "telemetry.db").write_bytes(b"junk" * 1000)


@pytest.fixture
def captured(monkeypatch):
    """What `build` hands the server, and the background tasks it would start."""
    spawned: list[str] = []
    served: dict[str, object] = {}

    def spawn(coroutine) -> None:
        spawned.append(coroutine.cr_code.co_name)
        coroutine.close()

    def create_server(**kwargs: object) -> object:
        served.update(kwargs)
        return object()

    monkeypatch.setattr(entry, "_spawn", spawn)
    monkeypatch.setattr(entry, "create_server", create_server)
    return spawned, served


def run_build(captured, env: dict[str, str]):
    spawned, served = captured
    entry.build(Settings.from_env(env), env)
    served["on_session_start"]()  # type: ignore[operator]
    return spawned, served


def test_a_release_build_after_the_notice_pings_and_ships(tmp_path, captured):
    env = env_for(tmp_path, DO_NOT_TRACK="")
    mark_notice_shown(env)
    spawned, served = run_build(captured, env)
    assert spawned == ["_send_ping", "_ship_backlog"]
    assert served["telemetry"] is not None


def test_nothing_is_collected_pinged_or_shipped_while_the_notice_is_due(tmp_path, captured):
    env = env_for(tmp_path, DO_NOT_TRACK="")
    spawned, served = run_build(captured, env)
    assert spawned == []
    assert served["telemetry"] is None
    assert not (tmp_path / "state" / "telemetry.db").exists()
    shown = served["notice"].take()  # type: ignore[attr-defined]
    assert shown is not None and TEXT in shown


def test_nothing_is_collected_pinged_or_shipped_under_do_not_track(tmp_path, captured):
    spawned, served = run_build(captured, env_for(tmp_path, DO_NOT_TRACK="1"))
    assert spawned == []
    assert served["telemetry"] is None
    assert served["notice"].take() is None  # type: ignore[attr-defined]


def test_a_build_that_is_not_a_release_collects_but_never_sends(tmp_path, captured, monkeypatch):
    monkeypatch.setattr(compose, "is_release", lambda version: False)
    env = env_for(tmp_path, DO_NOT_TRACK="")
    mark_notice_shown(env)
    spawned, served = run_build(captured, env)
    assert spawned == []
    assert served["telemetry"] is not None


def test_a_corrupt_store_does_not_stop_the_server_from_being_built(tmp_path, captured):
    env = env_for(tmp_path, DO_NOT_TRACK="")
    mark_notice_shown(env)
    corrupt_store(tmp_path)
    _, served = run_build(captured, env)
    assert served["telemetry"] is not None  # set aside, collecting again
    assert (tmp_path / "state" / "telemetry.db.corrupt").exists()


def test_an_unopenable_store_does_not_stop_the_server_from_being_built(tmp_path, captured):
    env = env_for(tmp_path, DO_NOT_TRACK="")
    mark_notice_shown(env)
    unopenable_store(tmp_path)
    spawned, served = run_build(captured, env)
    assert served["telemetry"] is None
    assert "_ship_backlog" not in spawned
    assert (tmp_path / "state" / "telemetry.db").is_dir()  # never set aside as damaged


@pytest.fixture
def dictated(monkeypatch):
    """What `_run` hands `dictate`, and the pings it sends, with no microphone."""
    seen: dict[str, object] = {}
    pings: list[dict[str, str]] = []

    async def fake_dictate(settings, **collaborators: object) -> str:
        seen.update(collaborators)
        await asyncio.sleep(0)  # lets the ping task run, as a real recording would
        return "a transcript"

    async def fake_send(ping, **kwargs: object) -> bool:
        pings.append(ping.payload)
        return True

    monkeypatch.setattr(talk, "dictate", fake_dictate)
    monkeypatch.setattr(talk.telemetry_ping, "send", fake_send)
    return seen, pings


async def test_talk_collects_and_pings_nothing_while_the_notice_is_due(tmp_path, dictated):
    """`/walkie:talk` cannot show the notice: its output is read as the user's prompt."""
    seen, pings = dictated
    env = env_for(tmp_path, DO_NOT_TRACK="")
    assert await talk._run(Settings.from_env(env), env) == "a transcript"
    assert seen["telemetry"] is None
    assert pings == []
    assert not (tmp_path / "state" / "telemetry.db").exists()


async def test_talk_collects_and_pings_once_the_notice_is_shown(tmp_path, dictated):
    seen, pings = dictated
    env = env_for(tmp_path, DO_NOT_TRACK="")
    mark_notice_shown(env)
    await talk._run(Settings.from_env(env), env)
    assert seen["telemetry"] is not None
    assert pings == [{"plugin_version": "1.0.0", "os": sys.platform, "event": "install"}]


async def test_talk_under_do_not_track_keeps_and_sends_nothing(tmp_path, dictated):
    seen, pings = dictated
    env = env_for(tmp_path, DO_NOT_TRACK="1")
    await talk._run(Settings.from_env(env), env)
    assert seen["telemetry"] is None
    assert pings == []
    assert not IDENTITY.config_dir(env, host_platform=sys.platform).exists()


async def test_a_corrupt_store_does_not_stop_talk(tmp_path, dictated):
    seen, _ = dictated
    env = env_for(tmp_path, DO_NOT_TRACK="")
    mark_notice_shown(env)
    corrupt_store(tmp_path)
    assert await talk._run(Settings.from_env(env), env) == "a transcript"
    assert seen["telemetry"] is not None  # set aside, collecting again


async def test_an_unopenable_store_does_not_stop_talk(tmp_path, dictated):
    seen, _ = dictated
    env = env_for(tmp_path, DO_NOT_TRACK="")
    mark_notice_shown(env)
    unopenable_store(tmp_path)
    assert await talk._run(Settings.from_env(env), env) == "a transcript"
    assert seen["telemetry"] is None
