"""The plugin's declarations of itself agree, name walkie, and pin an immutable core."""

import json
import re
import tomllib
from pathlib import Path

from walkie.server import VERSION

ROOT = Path(__file__).resolve().parents[1]


def project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_plugin_json_pyproject_and_the_server_agree_on_1_0_0():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["name"] == project()["project"]["name"] == "walkie"
    assert plugin["version"] == project()["project"]["version"] == VERSION == "1.0.0"


def test_the_marketplace_lives_in_voicebox_not_here():
    assert not (ROOT / ".claude-plugin" / "marketplace.json").exists()


def test_the_mcp_server_is_named_walkie_and_launched_by_its_script():
    servers = json.loads((ROOT / ".mcp.json").read_text())
    assert list(servers) == ["walkie"]
    assert servers["walkie"]["args"] == ["${CLAUDE_PLUGIN_ROOT}/scripts/walkie-mcp"]
    for launcher in ("walkie-mcp", "walkie-talk"):
        assert (ROOT / "scripts" / launcher).stat().st_mode & 0o111


def test_the_commands_are_exactly_walkies():
    names = {path.stem for path in (ROOT / "commands").glob("*.md")}
    assert names == {"talk", "converse", "setup", "telemetry", "stats"}


def test_the_console_scripts_are_walkies():
    assert set(project()["project"]["scripts"]) == {
        "walkie-mcp",
        "walkie-talk",
        "walkie-telemetry",
        "walkie-stats",
    }


def test_speak_core_is_pinned_to_a_tag_or_a_commit_and_never_a_path():
    (pin,) = [d for d in project()["project"]["dependencies"] if d.startswith("speak-core")]
    assert re.fullmatch(
        r"speak-core @ git\+https://github\.com/danilogr/speak-core@(v\d+\.\d+\.\d+|[0-9a-f]{40})",
        pin,
    )
    assert "sources" not in project().get("tool", {}).get("uv", {})
