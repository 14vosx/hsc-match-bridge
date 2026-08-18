"""Tests protecting critical observable local MatchZy filesystem and RCON actuation contracts."""

import json
import tempfile
import unittest
from pathlib import Path

from hsc_match_bridge.matchzy import serialize_matchzy_config
from hsc_match_bridge.matchzy_actuator import (
    MatchZyActuationError,
    materialize_matchzy_config,
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
            display_name="Map Display",
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


class TestMatchZyActuatorContracts(unittest.TestCase):
    """Observable contracts for local MatchZy config materialization."""

    def test_materialize_config_creates_expected_path_and_content(self) -> None:
        """Atomic writer creates <csgoRoot>/hsc-match-bridge/<runtimeMatchId>.json with G2-A serialized content."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            csgo_root = Path(tmp_dir)
            spec = _sample_match_spec(runtime_match_id=1000005)

            rel_path = materialize_matchzy_config(csgo_root, spec)

            self.assertEqual(rel_path, "hsc-match-bridge/1000005.json")
            target_file = csgo_root / rel_path
            self.assertTrue(target_file.is_file())

            written_content = target_file.read_text(encoding="utf-8")
            expected_content = serialize_matchzy_config(spec)
            self.assertEqual(written_content, expected_content)

    def test_materialize_config_idempotent_on_identical_content(self) -> None:
        """Atomic writer succeeds idempotently when target file already exists with identical content."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            csgo_root = Path(tmp_dir)
            spec = _sample_match_spec(runtime_match_id=1000005)

            # First write
            rel_path_1 = materialize_matchzy_config(csgo_root, spec)
            target_file = csgo_root / rel_path_1

            # Modify mtime to detect unnecessary rewrites if needed, or verify content remains exact
            original_content = target_file.read_text(encoding="utf-8")

            # Second write with identical spec
            rel_path_2 = materialize_matchzy_config(csgo_root, spec)

            self.assertEqual(rel_path_1, rel_path_2)
            self.assertEqual(target_file.read_text(encoding="utf-8"), original_content)

    def test_materialize_config_fails_closed_on_divergent_content(self) -> None:
        """Atomic writer raises MatchZyActuationError and preserves original file if target exists with divergent content."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            csgo_root = Path(tmp_dir)
            spec_original = _sample_match_spec(runtime_match_id=1000005, map_key="de_mirage")
            spec_divergent = _sample_match_spec(runtime_match_id=1000005, map_key="de_inferno")

            # First write original
            materialize_matchzy_config(csgo_root, spec_original)
            target_file = csgo_root / "hsc-match-bridge/1000005.json"
            original_content = target_file.read_text(encoding="utf-8")

            # Attempt write divergent spec with same runtimeMatchId
            with self.assertRaises(MatchZyActuationError):
                materialize_matchzy_config(csgo_root, spec_divergent)

            # Confirm original file content was preserved untouched
            self.assertEqual(target_file.read_text(encoding="utf-8"), original_content)


if __name__ == "__main__":
    unittest.main()
