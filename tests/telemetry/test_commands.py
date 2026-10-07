"""The two console scripts: the consent command (with `notice`) and the stats report."""

import io

import pytest
from speak_core.telemetry import notice as core_notice
from speak_core.telemetry import store

from walkie.telemetry import commands
from walkie.telemetry.contract import IDENTITY, SCHEMA
from walkie.telemetry.notice import TEXT


def test_notice_prints_the_text_and_marks_it_shown(tmp_path):
    env = {"HOME": str(tmp_path)}
    out = io.StringIO()
    assert commands.show_notice(env, host_platform="darwin", out=out) == 0
    assert TEXT in out.getvalue()
    assert core_notice.due(env, IDENTITY, host_platform="darwin") is False


def test_under_do_not_track_the_notice_says_nothing_is_sent_and_marks_nothing(tmp_path):
    env = {"HOME": str(tmp_path), "DO_NOT_TRACK": "1"}
    out = io.StringIO()
    assert commands.show_notice(env, host_platform="darwin", out=out) == 0
    assert "sends nothing" in out.getvalue()
    assert not IDENTITY.config_dir(env, host_platform="darwin").exists()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("WALKIE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    return tmp_path


def test_the_notice_subcommand_runs_from_the_console_script(isolated, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["walkie-telemetry", "notice"])
    with pytest.raises(SystemExit) as stop:
        commands.telemetry_main()
    assert stop.value.code == 0
    assert TEXT in capsys.readouterr().out


def test_the_consent_command_saves_a_mode(isolated, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["walkie-telemetry", "local"])
    with pytest.raises(SystemExit) as stop:
        commands.telemetry_main()
    assert stop.value.code == 0
    assert "walkie telemetry is now local." in capsys.readouterr().out


def test_the_consent_command_keeps_recordings_when_asked(isolated, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["walkie-telemetry", "record", "on"])
    with pytest.raises(SystemExit) as stop:
        commands.telemetry_main()
    assert stop.value.code == 0
    assert "walkie recordings are now on." in capsys.readouterr().out


def test_stats_without_a_store_prints_a_plain_message(isolated, capsys):
    with pytest.raises(SystemExit) as stop:
        commands.stats_main()
    assert stop.value.code == 0
    assert "No telemetry recorded yet." in capsys.readouterr().out


def test_stats_reads_the_store_in_the_state_dir(isolated, capsys):
    store.connect(isolated / "state" / "telemetry.db", SCHEMA).close()
    with pytest.raises(SystemExit) as stop:
        commands.stats_main()
    assert stop.value.code == 0
    assert "No utterances recorded yet." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("make", "says"),
    [
        (lambda db: db.write_bytes(b"this is not a database" * 500), "moves it aside"),
        (lambda db: db.mkdir(), "cannot be read right now"),
    ],
    ids=["corrupt", "unopenable"],
)
def test_stats_on_a_store_it_cannot_read_says_so_plainly(isolated, capsys, make, says):
    state = isolated / "state"
    state.mkdir()
    make(state / "telemetry.db")
    with pytest.raises(SystemExit) as stop:
        commands.stats_main()
    assert stop.value.code == 1
    printed = capsys.readouterr()
    assert printed.out == "" and says in printed.err
    assert str(state / "telemetry.db") in printed.err
