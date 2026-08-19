"""MatchZy configuration rendering from Central Match Spec v1."""

from __future__ import annotations

import json
from typing import Any

from hsc_match_bridge.protocol import MatchSpecPlayer, MatchSpecV1


def _render_players_map(players: tuple[MatchSpecPlayer, ...]) -> dict[str, str]:
    return {player.steamid64: player.player_account_id for player in players}


def render_matchzy_config(match_spec: MatchSpecV1) -> dict[str, Any]:
    """Render a deterministic MatchZy config dictionary from MatchSpecV1."""
    if not isinstance(match_spec, MatchSpecV1):
        raise TypeError(f"Expected MatchSpecV1, got {type(match_spec).__name__}")

    return {
        "matchid": match_spec.runtime_match_id,
        "num_maps": 1,
        "players_per_team": 5,
        "min_players_to_ready": 5,
        "min_spectators_to_ready": 0,
        "skip_veto": True,
        "maplist": [match_spec.map.key],
        "map_sides": ["knife"],
        "team1": {
            "id": "A",
            "name": "Team A",
            "players": _render_players_map(match_spec.teams.team_a),
        },
        "team2": {
            "id": "B",
            "name": "Team B",
            "players": _render_players_map(match_spec.teams.team_b),
        },
    }


def serialize_matchzy_config(match_spec: MatchSpecV1) -> str:
    """Serialize MatchSpecV1 to deterministic UTF-8 formatted MatchZy JSON string."""
    config_dict = render_matchzy_config(match_spec)
    return json.dumps(config_dict, indent=2) + "\n"
