"""Tests protecting critical observable MatchZy configuration rendering contracts."""

import json
import unittest

from hsc_match_bridge.matchzy import render_matchzy_config, serialize_matchzy_config
from hsc_match_bridge.protocol import (
    MatchSpecMap,
    MatchSpecPlayer,
    MatchSpecTeams,
    MatchSpecV1,
)


def _sample_match_spec() -> MatchSpecV1:
    return MatchSpecV1(
        spec_version=1,
        competitive_match_id="match-uuid-12345",
        runtime_match_id=1000005,
        map=MatchSpecMap(
            pool_key="pool-active-1",
            pool_version=1,
            key="de_mirage",
            display_name="Mirage",
        ),
        teams=MatchSpecTeams(
            team_a=(
                MatchSpecPlayer(player_account_id="p-a1", steamid64="76561198000000001"),
                MatchSpecPlayer(player_account_id="p-a2", steamid64="76561198000000002"),
                MatchSpecPlayer(player_account_id="p-a3", steamid64="76561198000000003"),
                MatchSpecPlayer(player_account_id="p-a4", steamid64="76561198000000004"),
                MatchSpecPlayer(player_account_id="p-a5", steamid64="76561198000000005"),
            ),
            team_b=(
                MatchSpecPlayer(player_account_id="p-b1", steamid64="76561198000000011"),
                MatchSpecPlayer(player_account_id="p-b2", steamid64="76561198000000012"),
                MatchSpecPlayer(player_account_id="p-b3", steamid64="76561198000000013"),
                MatchSpecPlayer(player_account_id="p-b4", steamid64="76561198000000014"),
                MatchSpecPlayer(player_account_id="p-b5", steamid64="76561198000000015"),
            ),
        ),
    )


class TestMatchZyRendererContracts(unittest.TestCase):
    """Observable contracts for MatchSpecV1 → MatchZy JSON translation."""

    def test_render_exact_matchzy_structure(self) -> None:
        """A valid MatchSpecV1 renders the exact essential MatchZy structure."""
        spec = _sample_match_spec()
        config = render_matchzy_config(spec)

        expected = {
            "matchid": 1000005,
            "num_maps": 1,
            "players_per_team": 5,
            "min_players_to_ready": 5,
            "min_spectators_to_ready": 0,
            "skip_veto": True,
            "maplist": ["de_mirage"],
            "map_sides": ["knife"],
            "team1": {
                "id": "A",
                "name": "Team A",
                "players": {
                    "76561198000000001": "p-a1",
                    "76561198000000002": "p-a2",
                    "76561198000000003": "p-a3",
                    "76561198000000004": "p-a4",
                    "76561198000000005": "p-a5",
                },
            },
            "team2": {
                "id": "B",
                "name": "Team B",
                "players": {
                    "76561198000000011": "p-b1",
                    "76561198000000012": "p-b2",
                    "76561198000000013": "p-b3",
                    "76561198000000014": "p-b4",
                    "76561198000000015": "p-b5",
                },
            },
        }
        self.assertEqual(config, expected)

    def test_team_and_player_mappings(self) -> None:
        """Team A maps to team1 and Team B maps to team2 with exact SteamID64 -> playerAccountId mappings."""
        spec = _sample_match_spec()
        config = render_matchzy_config(spec)

        self.assertEqual(config["team1"]["id"], "A")
        self.assertEqual(config["team1"]["name"], "Team A")
        self.assertEqual(
            config["team1"]["players"],
            {p.steamid64: p.player_account_id for p in spec.teams.team_a},
        )

        self.assertEqual(config["team2"]["id"], "B")
        self.assertEqual(config["team2"]["name"], "Team B")
        self.assertEqual(
            config["team2"]["players"],
            {p.steamid64: p.player_account_id for p in spec.teams.team_b},
        )

    def test_runtime_match_id_and_map_propagation(self) -> None:
        """runtimeMatchId and selected map key are propagated exactly without transformation."""
        spec = _sample_match_spec()
        config = render_matchzy_config(spec)

        self.assertEqual(config["matchid"], 1000005)
        self.assertEqual(config["maplist"], ["de_mirage"])

    def test_knife_skip_veto_and_format_constants(self) -> None:
        """Knife, skip-veto, and BO1 5v5 values are fixed as approved."""
        spec = _sample_match_spec()
        config = render_matchzy_config(spec)

        self.assertEqual(config["num_maps"], 1)
        self.assertEqual(config["players_per_team"], 5)
        self.assertEqual(config["min_players_to_ready"], 5)
        self.assertEqual(config["min_spectators_to_ready"], 0)
        self.assertIs(config["skip_veto"], True)
        self.assertEqual(config["map_sides"], ["knife"])

    def test_deterministic_serialization(self) -> None:
        """Serialization produces valid, deterministic UTF-8 JSON identical across calls."""
        spec = _sample_match_spec()
        serialized_1 = serialize_matchzy_config(spec)
        serialized_2 = serialize_matchzy_config(spec)

        self.assertEqual(serialized_1, serialized_2)
        self.assertTrue(serialized_1.endswith("\n"))
        parsed = json.loads(serialized_1)
        self.assertEqual(parsed, render_matchzy_config(spec))


if __name__ == "__main__":
    unittest.main()
