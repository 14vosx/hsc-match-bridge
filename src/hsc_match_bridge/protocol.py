"""Protocol models and strict payload parsing for HSC Match Bridge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from hsc_match_bridge.models import CommandType

STEAMID64_RE = re.compile(r"^\d{17}$")


class ProtocolError(Exception):
    """Raised when an Auth API protocol response or Match Spec is invalid."""


@dataclass(frozen=True)
class MatchSpecPlayer:
    """Player roster identity in Match Spec v1."""

    player_account_id: str
    steamid64: str


@dataclass(frozen=True)
class MatchSpecMap:
    """Map snapshot in Match Spec v1."""

    pool_key: str
    pool_version: int
    key: str
    display_name: str


@dataclass(frozen=True)
class MatchSpecTeams:
    """5v5 team rosters in Match Spec v1."""

    team_a: tuple[MatchSpecPlayer, ...]
    team_b: tuple[MatchSpecPlayer, ...]


@dataclass(frozen=True)
class MatchSpecV1:
    """Authoritative Central Match Spec v1."""

    spec_version: int
    competitive_match_id: str
    runtime_match_id: int
    map: MatchSpecMap
    teams: MatchSpecTeams


@dataclass(frozen=True)
class ClaimedCommandTarget:
    """Target server resource for claimed command."""

    server_key: str


@dataclass(frozen=True)
class ClaimedCommand:
    """Claimed command envelope and authoritative Match Spec."""

    command_id: str
    assignment_id: str
    command_type: CommandType
    attempt: int
    lease_token: str
    lease_expires_at: str
    target: ClaimedCommandTarget
    match_spec: MatchSpecV1


def _parse_roster_team(players_data: Any, team_name: str) -> tuple[MatchSpecPlayer, ...]:
    if not isinstance(players_data, list):
        raise ProtocolError(f"Team {team_name} in matchSpec must be a JSON array.")

    if len(players_data) != 5:
        raise ProtocolError(
            f"Team {team_name} must contain exactly 5 players, got {len(players_data)}."
        )

    parsed_players: list[MatchSpecPlayer] = []
    for idx, p in enumerate(players_data):
        if not isinstance(p, dict):
            raise ProtocolError(f"Player entry {idx} in Team {team_name} must be a JSON object.")

        player_id = p.get("playerAccountId")
        if (
            not isinstance(player_id, str)
            or not player_id.strip()
            or player_id != player_id.strip()
        ):
            raise ProtocolError(
                f"Player entry {idx} in Team {team_name} missing valid 'playerAccountId'."
            )

        steamid64 = p.get("steamid64")
        if not isinstance(steamid64, str) or not STEAMID64_RE.match(steamid64):
            raise ProtocolError(
                f"Player entry {idx} in Team {team_name} has invalid 'steamid64': '{steamid64}'."
            )

        parsed_players.append(
            MatchSpecPlayer(
                player_account_id=player_id,
                steamid64=steamid64,
            )
        )

    return tuple(parsed_players)


def parse_claimed_command_payload(data: Any) -> ClaimedCommand | None:
    """Parse and validate the Auth API claim response payload."""
    if not isinstance(data, dict):
        raise ProtocolError("Claim response root must be a JSON object.")

    if data.get("ok") is not True:
        raise ProtocolError("Claim response 'ok' field must be true.")

    protocol_version = data.get("protocolVersion")
    if isinstance(protocol_version, bool) or protocol_version != 1:
        raise ProtocolError(
            f"Unsupported protocolVersion: {protocol_version}. Expected integer 1."
        )

    command_data = data.get("command")
    if command_data is None:
        return None

    if not isinstance(command_data, dict):
        raise ProtocolError("Field 'command' must be a JSON object or null.")

    # 1. Command envelope fields
    command_id = command_data.get("commandId")
    if (
        not isinstance(command_id, str)
        or not command_id.strip()
        or command_id != command_id.strip()
    ):
        raise ProtocolError("Claimed command missing valid 'commandId'.")

    assignment_id = command_data.get("assignmentId")
    if (
        not isinstance(assignment_id, str)
        or not assignment_id.strip()
        or assignment_id != assignment_id.strip()
    ):
        raise ProtocolError("Claimed command missing valid 'assignmentId'.")

    raw_command_type = command_data.get("commandType")
    if raw_command_type != CommandType.PREPARE_MATCH.value:
        raise ProtocolError(
            f"Unsupported commandType: '{raw_command_type}'. Only PREPARE_MATCH is supported in G1."
        )

    attempt = command_data.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ProtocolError(f"Invalid 'attempt' count: {attempt}. Must be positive integer >= 1.")

    lease_token = command_data.get("leaseToken")
    if (
        not isinstance(lease_token, str)
        or not lease_token.strip()
        or lease_token != lease_token.strip()
    ):
        raise ProtocolError("Claimed command missing valid 'leaseToken'.")

    lease_expires_at = command_data.get("leaseExpiresAt")
    if not isinstance(lease_expires_at, str) or not lease_expires_at.strip():
        raise ProtocolError("Claimed command missing valid 'leaseExpiresAt'.")

    target_data = command_data.get("target")
    if not isinstance(target_data, dict):
        raise ProtocolError("Claimed command 'target' must be a JSON object.")

    server_key = target_data.get("serverKey")
    if not isinstance(server_key, str) or not server_key.strip():
        raise ProtocolError("Target missing valid 'serverKey'.")
    if len(server_key) > 64:
        raise ProtocolError(
            f"Target 'serverKey' exceeds maximum length of 64 characters: '{server_key}'."
        )

    # 2. Match Spec v1
    match_spec_data = command_data.get("matchSpec")
    if not isinstance(match_spec_data, dict):
        raise ProtocolError("Claimed command missing 'matchSpec' object.")

    spec_version = match_spec_data.get("specVersion")
    if isinstance(spec_version, bool) or spec_version != 1:
        raise ProtocolError(f"Unsupported specVersion: {spec_version}. Expected integer 1.")

    competitive_match_id = match_spec_data.get("competitiveMatchId")
    if (
        not isinstance(competitive_match_id, str)
        or not competitive_match_id.strip()
        or competitive_match_id != competitive_match_id.strip()
    ):
        raise ProtocolError("matchSpec missing valid 'competitiveMatchId'.")

    runtime_match_id = match_spec_data.get("runtimeMatchId")
    if (
        isinstance(runtime_match_id, bool)
        or not isinstance(runtime_match_id, int)
        or runtime_match_id < 1_000_000
    ):
        raise ProtocolError(
            f"matchSpec invalid 'runtimeMatchId': {runtime_match_id}. Must be integer >= 1000000."
        )

    map_data = match_spec_data.get("map")
    if not isinstance(map_data, dict):
        raise ProtocolError("matchSpec missing 'map' object.")

    pool_key = map_data.get("poolKey")
    if not isinstance(pool_key, str) or not pool_key.strip():
        raise ProtocolError("matchSpec.map missing valid 'poolKey'.")

    pool_version = map_data.get("poolVersion")
    if isinstance(pool_version, bool) or not isinstance(pool_version, int) or pool_version < 1:
        raise ProtocolError(
            f"matchSpec.map invalid 'poolVersion': {pool_version}. Must be integer >= 1."
        )

    map_key = map_data.get("key")
    if not isinstance(map_key, str) or not map_key.strip():
        raise ProtocolError("matchSpec.map missing valid 'key'.")

    map_display_name = map_data.get("displayName")
    if not isinstance(map_display_name, str) or not map_display_name.strip():
        raise ProtocolError("matchSpec.map missing valid 'displayName'.")

    teams_data = match_spec_data.get("teams")
    if not isinstance(teams_data, dict):
        raise ProtocolError("matchSpec missing 'teams' object.")

    team_a = _parse_roster_team(teams_data.get("A"), "A")
    team_b = _parse_roster_team(teams_data.get("B"), "B")

    # Check uniqueness across all 10 players
    all_player_ids = set()
    all_steam_ids = set()
    for p in team_a + team_b:
        if p.player_account_id in all_player_ids:
            raise ProtocolError(
                f"Duplicate playerAccountId in Match Spec roster: {p.player_account_id}"
            )
        all_player_ids.add(p.player_account_id)

        if p.steamid64 in all_steam_ids:
            raise ProtocolError(f"Duplicate steamid64 in Match Spec roster: {p.steamid64}")
        all_steam_ids.add(p.steamid64)

    return ClaimedCommand(
        command_id=command_id,
        assignment_id=assignment_id,
        command_type=CommandType.PREPARE_MATCH,
        attempt=attempt,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        target=ClaimedCommandTarget(server_key=server_key),
        match_spec=MatchSpecV1(
            spec_version=1,
            competitive_match_id=competitive_match_id,
            runtime_match_id=runtime_match_id,
            map=MatchSpecMap(
                pool_key=pool_key,
                pool_version=pool_version,
                key=map_key,
                display_name=map_display_name,
            ),
            teams=MatchSpecTeams(
                team_a=team_a,
                team_b=team_b,
            ),
        ),
    )
