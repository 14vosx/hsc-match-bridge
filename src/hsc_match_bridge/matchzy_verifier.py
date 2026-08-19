"""Strong PREPARED verification for MatchZy local server execution."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from hsc_match_bridge.matchzy_actuator import execute_rcon_command
from hsc_match_bridge.protocol import MatchSpecV1

STEAMID64_KEY_RE = re.compile(r'"(\d{17})"')

VERIFICATION_TIMEOUT_SECONDS = 12.0
VERIFICATION_POLL_INTERVAL_SECONDS = 0.5


def parse_matchzy_player_artifact(artifact_path: Path) -> set[str] | None:
    """Read MatchZyPlayerNames/Match_<runtimeMatchId>.ini and extract SteamID64 set."""
    if not artifact_path.is_file():
        return None

    try:
        content = artifact_path.read_text(encoding="utf-8")
    except Exception:
        return None

    found_ids = set(STEAMID64_KEY_RE.findall(content))
    return found_ids


def inspect_matchzy_prepared(
    csgo_root: Path,
    rcon_executable: Path,
    rcon_config_path: Path,
    match_spec: MatchSpecV1,
) -> bool:
    """Perform a single deterministic check of local PREPARED evidence."""
    # 1. Verify MatchZy player names artifact
    artifact_path = (
        csgo_root / "MatchZyPlayerNames" / f"Match_{match_spec.runtime_match_id}.ini"
    )
    artifact_steam_ids = parse_matchzy_player_artifact(artifact_path)
    if artifact_steam_ids is None:
        return False

    expected_steam_ids = {
        p.steamid64 for p in match_spec.teams.team_a + match_spec.teams.team_b
    }
    if len(expected_steam_ids) != 10 or artifact_steam_ids != expected_steam_ids:
        return False

    # 2. Query and validate status_json (server.map)
    try:
        status_json_raw = execute_rcon_command(
            rcon_executable=rcon_executable,
            rcon_config_path=rcon_config_path,
            command="status_json",
        )
    except Exception:
        return False

    try:
        status_data = json.loads(status_json_raw)
    except Exception:
        return False

    if not isinstance(status_data, dict):
        return False

    server_obj = status_data.get("server")
    if not isinstance(server_obj, dict):
        return False

    current_map = server_obj.get("map")
    if not isinstance(current_map, str) or current_map != match_spec.map.key:
        return False

    # 3. Query and validate get5_status
    try:
        get5_status_raw = execute_rcon_command(
            rcon_executable=rcon_executable,
            rcon_config_path=rcon_config_path,
            command="get5_status",
        )
    except Exception:
        return False

    try:
        get5_data = json.loads(get5_status_raw)
    except Exception:
        return False

    if not isinstance(get5_data, dict):
        return False

    if get5_data.get("matchid") != match_spec.runtime_match_id:
        return False

    expected_config_file = f"hsc-match-bridge/{match_spec.runtime_match_id}.json"
    if get5_data.get("loaded_config_file") != expected_config_file:
        return False

    gamestate = get5_data.get("gamestate")
    if not isinstance(gamestate, str) or not gamestate or gamestate == "none":
        return False

    team1 = get5_data.get("team1")
    if not isinstance(team1, dict) or team1.get("name") != "Team A":
        return False

    team2 = get5_data.get("team2")
    if not isinstance(team2, dict) or team2.get("name") != "Team B":
        return False

    return True


def wait_for_matchzy_prepared(
    csgo_root: Path,
    rcon_executable: Path,
    rcon_config_path: Path,
    match_spec: MatchSpecV1,
    timeout_seconds: float = VERIFICATION_TIMEOUT_SECONDS,
    poll_interval_seconds: float = VERIFICATION_POLL_INTERVAL_SECONDS,
) -> bool:
    """Bounded wait for strong PREPARED evidence."""
    deadline = time.monotonic() + timeout_seconds

    while True:
        if inspect_matchzy_prepared(
            csgo_root=csgo_root,
            rcon_executable=rcon_executable,
            rcon_config_path=rcon_config_path,
            match_spec=match_spec,
        ):
            return True

        if time.monotonic() >= deadline:
            break

        time.sleep(poll_interval_seconds)

    return False
