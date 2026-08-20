"""Tests protecting critical observable strong PREPARED verification contracts."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hsc_match_bridge.matchzy_verifier import (
    inspect_matchzy_prepared,
    parse_matchzy_player_artifact,
)
from hsc_match_bridge.protocol import (
    MatchSpecMap,
    MatchSpecPlayer,
    MatchSpecTeams,
    MatchSpecV1,
)


def _sample_match_spec(runtime_match_id: int = 1000005, map_key: str = "de_mirage") -> MatchSpecV1:
    return MatchSpecV1(
        spec_version=1,
        competitive_match_id="match-uuid-12345",
        runtime_match_id=runtime_match_id,
        map=MatchSpecMap(
            pool_key="pool-active-1",
            pool_version=1,
            key=map_key,
            display_name="Mirage",
        ),
        teams=MatchSpecTeams(
            team_a=tuple(
                MatchSpecPlayer(
                    player_account_id=f"p-a{i}",
                    steamid64=f"7656119800000000{i}",
                    personaname=f"Player A{i}",
                )
                for i in range(1, 6)
            ),
            team_b=tuple(
                MatchSpecPlayer(
                    player_account_id=f"p-b{i}",
                    steamid64=f"7656119800000001{i}",
                    personaname=f"Player B{i}",
                )
                for i in range(1, 6)
            ),
        ),
    )


def _write_player_artifact(csgo_root: Path, runtime_match_id: int, steam_ids: set[str]) -> None:
    names_dir = csgo_root / "MatchZyPlayerNames"
    names_dir.mkdir(parents=True, exist_ok=True)
    artifact_file = names_dir / f"Match_{runtime_match_id}.ini"

    lines = ['"Names"', "{"]
    for sid in sorted(steam_ids):
        lines.append(f'\t"{sid}" "Player_{sid[-2:]}"')
    lines.append("}")
    artifact_file.write_text("\n".join(lines), encoding="utf-8")


def _sample_status_json(map_name: str = "de_mirage") -> str:
    return json.dumps({
        "server": {
            "clients_human": 0,
            "map": map_name,
            "udp_port": 27015,
        }
    })


def _sample_get5_status(
    matchid: int = 1000005,
    loaded_config_file: str = "hsc-match-bridge/1000005.json",
    gamestate: str = "warmup",
    team1_name: str = "Team A",
    team2_name: str = "Team B",
) -> str:
    return json.dumps({
        "plugin_version": "0.15.0",
        "gamestate": gamestate,
        "paused": False,
        "loaded_config_file": loaded_config_file,
        "matchid": matchid,
        "map_number": 0,
        "round_number": -1,
        "round_time": None,
        "team1": {
            "name": team1_name,
            "series_score": 0,
            "current_map_score": 0,
            "connected_clients": -1,
            "ready": True,
            "side": "ct",
        },
        "team2": {
            "name": team2_name,
            "series_score": 0,
            "current_map_score": 0,
            "connected_clients": -1,
            "ready": True,
            "side": "terrorist",
        },
        "maps": None,
    })


class TestMatchZyVerifierContracts(unittest.TestCase):
    """Observable contracts for strong local PREPARED verification."""

    @patch("hsc_match_bridge.matchzy_verifier.execute_rcon_command")
    def test_strong_evidence_succeeds(self, mock_execute_rcon: unittest.mock.MagicMock) -> None:
        """Verifier succeeds when player artifact has exact 10 SteamIDs, status_json map matches, and get5_status matches."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            csgo_root = Path(tmp_dir)
            spec = _sample_match_spec()
            expected_steam_ids = {p.steamid64 for p in spec.teams.team_a + spec.teams.team_b}

            _write_player_artifact(csgo_root, spec.runtime_match_id, expected_steam_ids)

            mock_execute_rcon.side_effect = [
                _sample_status_json("de_mirage"),
                _sample_get5_status(matchid=spec.runtime_match_id),
            ]

            is_prepared = inspect_matchzy_prepared(
                csgo_root=csgo_root,
                rcon_executable=Path("/usr/local/bin/rcon"),
                rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                match_spec=spec,
            )

            self.assertTrue(is_prepared)
            self.assertEqual(mock_execute_rcon.call_count, 2)
            mock_execute_rcon.assert_any_call(
                rcon_executable=Path("/usr/local/bin/rcon"),
                rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                command="status_json",
            )
            mock_execute_rcon.assert_any_call(
                rcon_executable=Path("/usr/local/bin/rcon"),
                rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                command="get5_status",
            )

    @patch("hsc_match_bridge.matchzy_verifier.execute_rcon_command")
    def test_evidence_mismatches_fail_closed(self, mock_execute_rcon: unittest.mock.MagicMock) -> None:
        """Verifier returns False on missing/mismatched artifact, invalid JSON, wrong map, wrong matchid/config/gamestate/teams, or RCON error."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            csgo_root = Path(tmp_dir)
            spec = _sample_match_spec()
            expected_steam_ids = {p.steamid64 for p in spec.teams.team_a + spec.teams.team_b}
            rcon_exe = Path("/usr/local/bin/rcon")
            rcon_cfg = Path("/etc/rcon/srv1.yaml")

            # 1. Missing artifact file
            mock_execute_rcon.side_effect = [
                _sample_status_json("de_mirage"),
                _sample_get5_status(matchid=spec.runtime_match_id),
            ]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 2. Artifact with missing SteamID (9 instead of 10)
            _write_player_artifact(csgo_root, spec.runtime_match_id, set(list(expected_steam_ids)[:9]))
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 3. Artifact with extra/different SteamID
            corrupt_ids = (set(list(expected_steam_ids)[:9])) | {"76561199999999999"}
            _write_player_artifact(csgo_root, spec.runtime_match_id, corrupt_ids)
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # Write valid artifact for subsequent RCON checks
            _write_player_artifact(csgo_root, spec.runtime_match_id, expected_steam_ids)

            # 4. status_json invalid JSON
            mock_execute_rcon.side_effect = ["not a valid json", _sample_get5_status(spec.runtime_match_id)]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 5. status_json reports wrong map
            mock_execute_rcon.side_effect = [_sample_status_json("de_inferno"), _sample_get5_status(spec.runtime_match_id)]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 6. get5_status invalid JSON
            mock_execute_rcon.side_effect = [_sample_status_json("de_mirage"), "{broken json"]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 7. get5_status reports divergent matchid
            mock_execute_rcon.side_effect = [
                _sample_status_json("de_mirage"),
                _sample_get5_status(matchid=9999999),
            ]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 8. get5_status reports divergent loaded_config_file
            mock_execute_rcon.side_effect = [
                _sample_status_json("de_mirage"),
                _sample_get5_status(matchid=spec.runtime_match_id, loaded_config_file="other/config.json"),
            ]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 9. get5_status reports gamestate "none"
            mock_execute_rcon.side_effect = [
                _sample_status_json("de_mirage"),
                _sample_get5_status(matchid=spec.runtime_match_id, gamestate="none"),
            ]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 10. get5_status reports wrong team names
            mock_execute_rcon.side_effect = [
                _sample_status_json("de_mirage"),
                _sample_get5_status(matchid=spec.runtime_match_id, team1_name="Wrong Team A"),
            ]
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))

            # 11. RCON execution error
            mock_execute_rcon.side_effect = RuntimeError("RCON connection dropped")
            self.assertFalse(inspect_matchzy_prepared(csgo_root, rcon_exe, rcon_cfg, spec))


if __name__ == "__main__":
    unittest.main()
