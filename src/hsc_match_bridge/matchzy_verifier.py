"""Strong PREPARED verification for MatchZy local server execution."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import NamedTuple

from hsc_match_bridge.matchzy_actuator import execute_rcon_command
from hsc_match_bridge.protocol import MatchSpecV1

STEAMID64_KEY_RE = re.compile(r'"(\d{17})"')
STATUS_HOSTNAME_RE = re.compile(r"^\s*hostname\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
STATUS_MAP_RE = re.compile(r"^\s*map\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)

VERIFICATION_TIMEOUT_SECONDS = 12.0
VERIFICATION_POLL_INTERVAL_SECONDS = 0.5


class StatusSnapshot(NamedTuple):
    hostname: str
    map_name: str


def parse_cs2_status(status_output: str) -> StatusSnapshot | None:
    """Extract hostname and map from CS2 status command output."""
    if not isinstance(status_output, str):
        return None

    hostname_match = STATUS_HOSTNAME_RE.search(status_output)
    map_match = STATUS_MAP_RE.search(status_output)

    if not hostname_match or not map_match:
        return None

    return StatusSnapshot(
        hostname=hostname_match.group(1).strip(),
        map_name=map_match.group(1).strip(),
    )


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

    # 2. Query RCON status
    try:
        status_output = execute_rcon_command(
            rcon_executable=rcon_executable,
            rcon_config_path=rcon_config_path,
            command="status",
        )
    except Exception:
        return False

    # 3. Parse status
    status = parse_cs2_status(status_output)
    if status is None:
        return False

    # 4. Exact map check
    if status.map_name != match_spec.map.key:
        return False

    # 5. Team hostname evidence check (Team A and Team B from MatchZy config)
    if "Team A" not in status.hostname or "Team B" not in status.hostname:
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
