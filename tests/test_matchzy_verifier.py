"""Tests protecting critical observable strong PREPARED verification contracts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hsc_match_bridge.matchzy_verifier import (
    inspect_matchzy_prepared,
    parse_cs2_status,
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
                MatchSpecPlayer(player_account_id=f"p-a{i}", steamid64=f"7656119800000000{i}")
                for i in range(1, 6)
            ),
            team_b=tuple(
                MatchSpecPlayer(player_account_id=f"p-b{i}", steamid64=f"7656119800000001{i}")
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


SAMPLE_VALID_STATUS = """
hostname: HSC Match Server - Team A vs Team B
version : 1.40.1.0/14010 9999/9999 insecure
os      : Linux
type    : dedicated
map     : de_mirage
players : 0 humans, 0 bots (10 max)
"""


class TestMatchZyVerifierContracts(unittest.TestCase):
    """Observable contracts for strong local PREPARED verification."""

    @patch("hsc_match_bridge.matchzy_verifier.execute_rcon_command")
    def test_strong_evidence_succeeds(self, mock_execute_rcon: unittest.mock.MagicMock) -> None:
        """Verifier succeeds when player artifact contains exact 10 SteamIDs, map matches, and hostname contains both team names."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            csgo_root = Path(tmp_dir)
            spec = _sample_match_spec()
            expected_steam_ids = {p.steamid64 for p in spec.teams.team_a + spec.teams.team_b}

            _write_player_artifact(csgo_root, spec.runtime_match_id, expected_steam_ids)
            mock_execute_rcon.return_value = SAMPLE_VALID_STATUS

            is_prepared = inspect_matchzy_prepared(
                csgo_root=csgo_root,
                rcon_executable=Path("/usr/local/bin/rcon"),
                rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                match_spec=spec,
            )

            self.assertTrue(is_prepared)
            mock_execute_rcon.assert_called_once_with(
                rcon_executable=Path("/usr/local/bin/rcon"),
                rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                command="status",
            )

    @patch("hsc_match_bridge.matchzy_verifier.execute_rcon_command")
    def test_evidence_mismatches_fail_closed(self, mock_execute_rcon: unittest.mock.MagicMock) -> None:
        """Verifier returns False when artifact is missing/corrupted/mismatched, map is wrong, or team hostname evidence is missing."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            csgo_root = Path(tmp_dir)
            spec = _sample_match_spec()
            expected_steam_ids = {p.steamid64 for p in spec.teams.team_a + spec.teams.team_b}

            # 1. Missing artifact file
            mock_execute_rcon.return_value = SAMPLE_VALID_STATUS
            self.assertFalse(
                inspect_matchzy_prepared(
                    csgo_root=csgo_root,
                    rcon_executable=Path("/usr/local/bin/rcon"),
                    rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                    match_spec=spec,
                )
            )

            # 2. Artifact with missing SteamID (9 instead of 10)
            _write_player_artifact(csgo_root, spec.runtime_match_id, set(list(expected_steam_ids)[:9]))
            self.assertFalse(
                inspect_matchzy_prepared(
                    csgo_root=csgo_root,
                    rcon_executable=Path("/usr/local/bin/rcon"),
                    rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                    match_spec=spec,
                )
            )

            # 3. Artifact with extra/different SteamID
            corrupt_ids = (set(list(expected_steam_ids)[:9])) | {"76561199999999999"}
            _write_player_artifact(csgo_root, spec.runtime_match_id, corrupt_ids)
            self.assertFalse(
                inspect_matchzy_prepared(
                    csgo_root=csgo_root,
                    rcon_executable=Path("/usr/local/bin/rcon"),
                    rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                    match_spec=spec,
                )
            )

            # Now write valid artifact and test RCON status mismatches
            _write_player_artifact(csgo_root, spec.runtime_match_id, expected_steam_ids)

            # 4. Status reports wrong map
            wrong_map_status = SAMPLE_VALID_STATUS.replace("map     : de_mirage", "map     : de_inferno")
            mock_execute_rcon.return_value = wrong_map_status
            self.assertFalse(
                inspect_matchzy_prepared(
                    csgo_root=csgo_root,
                    rcon_executable=Path("/usr/local/bin/rcon"),
                    rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                    match_spec=spec,
                )
            )

            # 5. Status missing MatchZy team hostname evidence
            wrong_hostname_status = SAMPLE_VALID_STATUS.replace("Team A vs Team B", "Default CS2 Server")
            mock_execute_rcon.return_value = wrong_hostname_status
            self.assertFalse(
                inspect_matchzy_prepared(
                    csgo_root=csgo_root,
                    rcon_executable=Path("/usr/local/bin/rcon"),
                    rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                    match_spec=spec,
                )
            )

            # 6. RCON execution error
            mock_execute_rcon.side_effect = RuntimeError("RCON connection dropped")
            self.assertFalse(
                inspect_matchzy_prepared(
                    csgo_root=csgo_root,
                    rcon_executable=Path("/usr/local/bin/rcon"),
                    rcon_config_path=Path("/etc/rcon/srv1.yaml"),
                    match_spec=spec,
                )
            )


if __name__ == "__main__":
    unittest.main()
