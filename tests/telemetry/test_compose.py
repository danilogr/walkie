"""walkie's telemetry session: the install, then its own `sessions` row - what both
`__main__` and `talk` are handed - built so that nothing in it can stop walkie."""

from pathlib import Path

from speak_core.config import ServerSettings, VoiceSettings
from speak_core.telemetry import store

from walkie.config import Settings
from walkie.server import VERSION
from walkie.telemetry import compose


def built(tmp_path: Path, env: dict[str, str] | None = None, **settings: object):
    return compose.build(
        {"HOME": str(tmp_path / "home"), **(env or {})},
        settings=Settings(state_dir=tmp_path / "state", **settings),
        plugin_version="1.0.0",
        host_platform="linux",
    )


def test_build_returns_none_when_telemetry_is_off(tmp_path):
    assert built(tmp_path, {"WALKIE_TELEMETRY": "off"}) is None
    assert not (tmp_path / "state" / "telemetry.db").exists()


def test_the_store_is_in_the_state_dir(tmp_path):
    session = built(tmp_path)
    assert session is not None
    assert session.db_path == tmp_path / "state" / "telemetry.db"
    assert session.db_path.exists()


def test_build_writes_a_session_row_naming_the_engines(tmp_path):
    session = built(
        tmp_path,
        {"CLAUDE_PLUGIN_ROOT": "/plugin"},
        speech=VoiceSettings(prefix="WALKIE", engine="nemo"),
        server=ServerSettings(tts_model="magpie", asr_model="parakeet"),
    )
    assert session is not None
    (row,) = store.sessions_by_id(session.conn, [session.session_id])
    assert (row["tts_engine"], row["asr_engine"]) == ("nemo", "nemo")
    assert bool(row["listen_enabled"]) is True
    assert row["harness"] == "claude-code"
    assert (session.tts_model, session.asr_model) == ("magpie", "parakeet")


def test_each_session_gets_a_fresh_session_id(tmp_path):
    first, second = built(tmp_path), built(tmp_path)
    assert first is not None and second is not None
    assert first.session_id != second.session_id


def test_an_overlong_engine_name_is_cut_to_the_contract_length(tmp_path):
    session = built(tmp_path, speech=VoiceSettings(prefix="WALKIE", engine="x" * 80))
    assert session is not None
    (row,) = store.sessions_by_id(session.conn, [session.session_id])
    assert row["tts_engine"] == "x" * compose.TTS_ENGINE_MAX_LENGTH == session.tts_engine


def test_a_model_name_the_contract_would_refuse_is_left_out(tmp_path):
    """Cut, it would name a different model; sent whole, the server refuses the chunk."""
    session = built(
        tmp_path,
        speech=VoiceSettings(prefix="WALKIE", engine="nemo"),
        server=ServerSettings(tts_model="/models/" + "x" * 80, asr_model="y" * 65),
    )
    assert session is not None
    assert (session.tts_model, session.asr_model) == (None, None)


def test_a_model_name_at_the_limit_is_kept(tmp_path):
    session = built(tmp_path, server=ServerSettings(asr_model="y" * compose.MODEL_MAX_LENGTH))
    assert session is not None
    assert session.asr_model == "y" * compose.MODEL_MAX_LENGTH


def test_a_corrupt_store_is_moved_aside_and_collection_starts_again(tmp_path, caplog):
    state = tmp_path / "state"
    state.mkdir()
    garbage = b"junk" * 1000
    (state / "telemetry.db").write_bytes(garbage)
    with caplog.at_level("WARNING", logger="walkie.telemetry.compose"):
        session = built(tmp_path)
    assert session is not None
    assert (state / "telemetry.db.corrupt").read_bytes() == garbage
    assert len(store.sessions_by_id(session.conn, [session.session_id])) == 1
    assert "damaged" in caplog.text


def test_a_damaged_store_is_set_aside_with_its_sidecars(tmp_path):
    """A journal left beside a new store under the old name would be replayed into it."""
    db = tmp_path / "telemetry.db"
    for name in ("telemetry.db", "telemetry.db-journal", "telemetry.db.corrupt"):
        (tmp_path / name).write_text(name)
    compose.set_aside(db)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "telemetry.db.corrupt",
        "telemetry.db.corrupt-journal",
    ]
    assert (tmp_path / "telemetry.db.corrupt").read_text() == "telemetry.db"


def test_a_store_that_cannot_be_opened_collects_nothing_and_is_left_alone(tmp_path, caplog):
    unopenable = tmp_path / "state" / "telemetry.db"
    unopenable.mkdir(parents=True)  # a directory: sqlite cannot open it, but it is not corrupt
    with caplog.at_level("WARNING", logger="walkie.telemetry.compose"):
        assert built(tmp_path) is None
    assert "unusable" in caplog.text
    assert unopenable.is_dir() and not (tmp_path / "state" / "telemetry.db.corrupt").exists()


def test_only_release_versions_send():
    assert compose.is_release("1.0.0")
    assert not compose.is_release("1.0.0\n")  # the contract is read as JavaScript reads it
    assert not compose.is_release("1.0.0-dev")
    assert not compose.is_release("1.1.0.dev0")
    assert not compose.is_release("1.0")


def test_this_release_sends():
    """Release-time check: walkie's own version is one the contract's ping accepts."""
    assert compose.is_release(VERSION)
