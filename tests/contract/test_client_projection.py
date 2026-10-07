"""What this client stores and ships validates against the vendored contract, read the
way the server's ajv reads it. `jsonschema`, not a hand-rolled check: a partial
validator could pass a payload the server would reject."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import jsonschema
from speak_core.config import ServerSettings, VoiceSettings
from speak_core.queue import UtteranceOutcome
from speak_core.telemetry import ping, ship, store

from walkie.config import Settings
from walkie.telemetry import compose
from walkie.telemetry.contract import IDENTITY, SCHEMA

CONTRACT_DIR = Path(__file__).parent / "v1"


def _javascript_pattern(
    validator: object, pattern: str, instance: object, schema: object
) -> Iterator[jsonschema.ValidationError]:
    """`pattern` as the server's ajv reads it: every contract pattern is `^...$`, and
    JavaScript's `$` does not match before a trailing newline, as Python's does."""
    if isinstance(instance, str) and not re.search(pattern.removesuffix("$") + r"\Z", instance):
        yield jsonschema.ValidationError(f"{instance!r} does not match {pattern!r}")


STRICT = jsonschema.validators.extend(
    jsonschema.Draft202012Validator, {"pattern": _javascript_pattern}
)
REQUEST_SCHEMA = json.loads((CONTRACT_DIR / "schema" / "ingest-request.schema.json").read_text())
REQUEST = STRICT(REQUEST_SCHEMA)
PING = STRICT(json.loads((CONTRACT_DIR / "schema" / "ping-request.schema.json").read_text()))

INSTALL = {
    "install_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "first_seen_at": "2026-10-07T10:00:00.000000Z",
    "last_seen_at": "2026-10-07T10:00:00.000000Z",
    "plugin_version": "1.0.0",
    "disclosure_ver": 1,
    "language": "en-US",
    "timezone": "America/Sao_Paulo",
    "utc_offset_min": -180,
    "os": "darwin",
    "os_version": "15.4",
    "arch": "arm64",
    "cpu_model": "Apple M5",
    "cpu_count": 12,
    "ram_gb": 32,
    "accel": "metal",
    "accel_name": "Apple M5",
    "country": None,  # never populated by the client; must still project away
}

SESSION = {
    "session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "install_id": INSTALL["install_id"],
    "started_at": "2026-10-07T10:00:00.000000Z",
    "ended_at": "2026-10-07T10:20:00.000000Z",
    "plugin_version": "1.0.0",
    "tts_engine": "nemo",
    "asr_engine": "nemo",
    "listen_enabled": True,
    "harness": "claude-code",
    "harness_version": "2.1.0",
}


def out_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "utterance_id": "cccccccc-cccc-4ccc-8ccc-ccccccccccc0",
        "session_id": SESSION["session_id"],
        "install_id": INSTALL["install_id"],
        "seq": 1,
        "direction": "out",
        "source": "speak",
        "occurred_at": "2026-10-07T10:00:01.000000Z",
        "engine": "nemo",
        "model": "magpie",
        "voice": "John",
        "intent": "task_done",
        "words": 42,
        "chars": 231,
        "audio_ms": 8400,
        "queue_wait_ms": 120,
        "synth_ms": 340,
        "play_ms": 8600,
        "status": "ok",
        # local-only, must never survive the projection
        "text": "the actual sentence spoken",
        "text_sha256": "deadbeef",
        "shipped_at": None,
    }
    row.update(overrides)
    return row


def in_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "utterance_id": "cccccccc-cccc-4ccc-8ccc-ccccccccccc1",
        "session_id": SESSION["session_id"],
        "install_id": INSTALL["install_id"],
        "seq": 2,
        "direction": "in",
        "source": "listen",
        "occurred_at": "2026-10-07T10:00:20.000000Z",
        "engine": "nemo",
        "model": "nemotron-3.5",
        "device_kind": "bluetooth",
        "words": 9,
        "chars": 47,
        "audio_ms": 2100,
        "asr_ms": 260,
        "status": "ok",
        # local-only, must never survive the projection
        "text": "run the tests",
        "text_sha256": "cafebabe",
        "device_name": "Danilo's AirPods Pro",
        "shipped_at": None,
    }
    row.update(overrides)
    return row


def _payload(*utterances: dict[str, object]) -> dict[str, object]:
    return {
        "install": ship.project_install(INSTALL),
        "sessions": [ship.project_session(SCHEMA, SESSION)],
        "utterances": [ship.project_row(SCHEMA.rows, u) for u in utterances],
    }


def _stored_payload(conn) -> dict[str, object]:
    """What `ship()` would send from this store: install, the rows' sessions, the rows."""
    install = store.install_row(conn)
    assert install is not None
    rows = store.unshipped_rows(conn, SCHEMA.rows)
    session_ids = sorted({str(row["session_id"]) for row in rows})
    return {
        "install": ship.project_install(install),
        "sessions": [
            ship.project_session(SCHEMA, s) for s in store.sessions_by_id(conn, session_ids)
        ],
        "utterances": [ship.project_row(SCHEMA.rows, row) for row in rows],
    }


def errors_of(payload: dict[str, object]) -> list[str]:
    return [
        f"/{'/'.join(map(str, error.absolute_path))}: {error.message}"
        for error in REQUEST.iter_errors(payload)
    ]


def test_a_full_out_and_in_batch_validates() -> None:
    assert errors_of(_payload(out_row(), in_row())) == []


def test_the_minimal_out_row_validates() -> None:
    minimal = out_row(
        engine=None,
        model=None,
        voice=None,
        intent=None,
        words=None,
        chars=None,
        audio_ms=None,
        queue_wait_ms=None,
        synth_ms=None,
        play_ms=None,
    )
    assert errors_of(_payload(minimal)) == []


def test_the_real_local_store_round_trips_through_a_validating_payload() -> None:
    """The path `ship.py` runs in production: insert into the real schema, read it back,
    project it, validate it - not a hand-assembled dict."""
    conn = store.connect(Path(":memory:"), SCHEMA)
    store.upsert_install(conn, INSTALL)
    store.insert_session(conn, SCHEMA, SESSION)
    store.insert_row(conn, SCHEMA.rows, out_row())
    store.insert_row(conn, SCHEMA.rows, in_row())
    assert errors_of(_stored_payload(conn)) == []


async def test_every_request_ship_sends_validates_including_a_session_alone() -> None:
    """The payloads `ship()` itself builds, captured at the transport: an utterance
    chunk, then a session that ships with no utterances at all."""
    conn = store.connect(Path(":memory:"), SCHEMA)
    store.upsert_install(conn, INSTALL)
    store.insert_session(conn, SCHEMA, SESSION)
    store.insert_row(conn, SCHEMA.rows, out_row(status="interrupted"))
    store.insert_session(
        conn, SCHEMA, {**SESSION, "session_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"}
    )
    sent: list[dict[str, object]] = []

    async def transport(url: str, body: bytes) -> ship.TransportResponse:
        sent.append(json.loads(body))
        return ship.TransportResponse(status=202, body=b'{"accepted": 1}')

    await ship.ship(
        conn,
        schema=SCHEMA,
        install_id=str(INSTALL["install_id"]),
        url="https://x/v1/ingest",
        transport=transport,
    )

    assert [len(p["utterances"]) for p in sent] == [1, 0]
    for payload in sent:
        assert errors_of(payload) == []


def test_the_install_ping_validates_and_goes_to_speak_telemetrys_origin(tmp_path) -> None:
    pending = ping.due(
        {"HOME": str(tmp_path)},
        IDENTITY,
        plugin_version="1.0.0",
        host_platform="linux",
        ingest_url=IDENTITY.ingest_url({}),
    )
    assert pending is not None
    assert list(PING.iter_errors(pending.payload)) == []
    assert pending.url == "https://speak-telemetry.actionableintelligence.app/v1/ping"


def test_the_strict_validator_rejects_what_plain_jsonschema_lets_through() -> None:
    payload = _payload(out_row())
    payload["sessions"][0]["plugin_version"] = "1.0.0\n"  # type: ignore[index]
    assert list(jsonschema.Draft202012Validator(REQUEST_SCHEMA).iter_errors(payload)) == []
    assert errors_of(payload) != []


def test_out_of_contract_settings_still_produce_valid_rows(tmp_path) -> None:
    """Every value a user's settings or an MCP client can push past the contract - long
    model names, a free-text voice, a long client version, absurd timings, long
    transcripts - is clamped, mapped or dropped before it is stored."""
    settings = Settings(
        server=ServerSettings(tts_model="/models/" + "x" * 80, asr_model="y" * 80),
        speech=VoiceSettings(prefix="WALKIE", engine="nemo"),
        state_dir=tmp_path / "state",
    )
    session = compose.build(
        {"HOME": str(tmp_path / "home")},
        settings=settings,
        plugin_version="1.0.0",
        host_platform="darwin",
    )
    assert session is not None
    session.update_harness("other", "v" * 100)
    session.utterance_finished(
        UtteranceOutcome(
            text=" ".join(["word"] * 25_000),
            voice="My Voice\n",
            intent="task_done",
            status="ok",
            queue_wait_ms=10**9,
            synth_ms=10**9,
            play_ms=10**9,
            audio_ms=10**9,
            engine="nemo",
        )
    )
    session.heard(
        source="listen",
        status="ok",
        transcript="run\nthe tests " * 20_000,
        device_name="Danilo's AirPods\n",
        asr_ms=10**9,
    )
    session.heard(source="talk", status="refused")

    payload = _stored_payload(session.conn)
    assert len(payload["utterances"]) == 3  # type: ignore[arg-type]
    assert errors_of(payload) == []
    assert all("model" not in row for row in payload["utterances"])  # type: ignore[union-attr]
