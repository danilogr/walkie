"""`walkie.__main__.build()` wires the queue's `on_finish` into a real
`TelemetrySession` and hands it to `create_server`, once the first-run notice has been
shown. A real subprocess is the only way to run its lifespan (which starts the queue's
worker) the way `walkie-mcp` really does, the same reason `tests/test_server.py` uses
one."""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import mcp_types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from speak_core.telemetry import notice, store

from walkie.telemetry.contract import IDENTITY, SCHEMA
from walkie.telemetry.notice import TEXT


def _env(state_dir: Path, home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "WALKIE_ENGINE": "command",
        "WALKIE_COMMAND": "true",  # a no-op binary: silent, and hermetic like test_server.py
        "NEMO_AUTOSTART": "0",
        "WALKIE_STATE_DIR": str(state_dir),
        "SPEAK_CORE_STATE_DIR": str(state_dir),
        "WALKIE_TELEMETRY": "local",
        # Collecting needs DO_NOT_TRACK cleared, which lets the install ping run;
        # debug turns it, and any shipping, into a log line instead of a request.
        "DO_NOT_TRACK": "",
        "WALKIE_TELEMETRY_DEBUG": "1",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }


def _notice_shown(state_dir: Path, home: Path) -> None:
    """What `/walkie:setup` does: show the notice, after which walkie may collect."""
    assert notice.mark_shown(_env(state_dir, home), IDENTITY, host_platform=sys.platform)


@asynccontextmanager
async def connected(
    state_dir: Path, home: Path, client_info: mcp_types.Implementation | None = None
):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "walkie"],
        env=_env(state_dir, home),
        cwd=str(Path.cwd()),
    )
    async with (
        stdio_client(parameters) as (read, write),
        ClientSession(read, write, client_info=client_info) as session,
    ):
        await session.initialize()
        yield session


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    return tmp_path / "state", home


async def test_speaking_through_the_real_server_writes_a_local_row(tmp_path):
    """The MCP SDK's default client_info name is "mcp", which `normalize_harness` calls
    "other": declared, just not one of the named harnesses."""
    state_dir, home = _dirs(tmp_path)
    _notice_shown(state_dir, home)

    async with connected(state_dir, home) as session:
        await session.call_tool("speak", {"text": "hello", "intent": "task_done"})
        await _wait_for_a_row(state_dir)

    conn = store.connect(state_dir / "telemetry.db", SCHEMA)
    try:
        rows = store.unshipped_rows(conn, SCHEMA.rows)
        assert len(rows) == 1
        assert (rows[0]["direction"], rows[0]["source"], rows[0]["intent"]) == (
            "out",
            "speak",
            "task_done",
        )
        assert (rows[0]["engine"], rows[0]["status"]) == ("command", "ok")
        (session_row,) = store.sessions_by_id(conn, [rows[0]["session_id"]])
        assert session_row["harness"] == "other"
    finally:
        conn.close()


async def test_the_clients_own_client_info_overrides_the_environment_fallback(tmp_path):
    state_dir, home = _dirs(tmp_path)
    _notice_shown(state_dir, home)

    async with connected(
        state_dir,
        home,
        client_info=mcp_types.Implementation(name="Gemini CLI", version="1.2.3"),
    ) as session:
        await session.call_tool("speak", {"text": "hello"})
        await _wait_for_a_row(state_dir)

    conn = store.connect(state_dir / "telemetry.db", SCHEMA)
    try:
        (row,) = store.unshipped_rows(conn, SCHEMA.rows)
        (session_row,) = store.sessions_by_id(conn, [row["session_id"]])
        assert (session_row["harness"], session_row["harness_version"]) == (
            "gemini-cli",
            "1.2.3",
        )
    finally:
        conn.close()


async def test_nothing_is_recorded_before_the_notice_and_the_first_reply_carries_it(tmp_path):
    state_dir, home = _dirs(tmp_path)

    async with connected(state_dir, home) as session:
        result = await session.call_tool("speak", {"text": "hello"})
        assert TEXT in result.content[0].text
        again = await session.call_tool("speak", {"text": "again"})
        assert TEXT not in again.content[0].text

    assert not (state_dir / "telemetry.db").exists()
    assert notice.due(_env(state_dir, home), IDENTITY, host_platform=sys.platform) is False


async def _wait_for_a_row(state_dir: Path, timeout: float = 10.0) -> None:
    db_path = state_dir / "telemetry.db"
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if db_path.exists():
            conn = store.connect(db_path, SCHEMA)
            try:
                if store.unshipped_rows(conn, SCHEMA.rows):
                    return
            finally:
                conn.close()
        await asyncio.sleep(0.05)
    raise AssertionError(f"no telemetry row appeared under {db_path} in time")
