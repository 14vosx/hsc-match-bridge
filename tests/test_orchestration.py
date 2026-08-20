"""Tests protecting critical observable intake orchestration contracts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from hsc_match_bridge.client import MatchBridgeClient
from hsc_match_bridge.config import BridgeConfig, ServerResourceConfig
from hsc_match_bridge.journal import CommandJournal
from hsc_match_bridge.models import CommandState, CommandType
from hsc_match_bridge.orchestration import IntakeOutcome, intake_one_cycle
from hsc_match_bridge.protocol import (
    ClaimedCommand,
    ClaimedCommandTarget,
    MatchSpecMap,
    MatchSpecPlayer,
    MatchSpecTeams,
    MatchSpecV1,
    ProtocolError,
)


def _sample_claimed_command(server_key: str = "srv-east-1", command_id: str = "cmd-100") -> ClaimedCommand:
    return ClaimedCommand(
        command_id=command_id,
        assignment_id="assign-100",
        command_type=CommandType.PREPARE_MATCH,
        attempt=1,
        lease_token="lease_tok_xyz",
        lease_expires_at="2026-08-18T15:00:30.000Z",
        target=ClaimedCommandTarget(server_key=server_key),
        match_spec=MatchSpecV1(
            spec_version=1,
            competitive_match_id="match-uuid-1",
            runtime_match_id=1000001,
            map=MatchSpecMap(
                pool_key="pool-1",
                pool_version=1,
                key="de_mirage",
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
        ),
    )


class TestOrchestrationContracts(unittest.TestCase):
    """Observable contracts for one-cycle intake orchestration."""

    def test_intake_no_work_does_not_mutate_journal(self) -> None:
        """When client.claim() returns None, intake returns NO_WORK and leaves journal untouched."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = BridgeConfig(
                bridge_node_key="node-01",
                auth_api_base_url="https://auth.example.com",
                bridge_credential="secret_token",
                state_db_path=db_path,
                rcon_executable=Path("/usr/local/bin/rcon"),
                servers=(
                    ServerResourceConfig(
                        server_key="srv-east-1",
                        csgo_root=Path("/opt/cs2/game/csgo"),
                        rcon_config_path=Path("/etc/rcon/srv-east-1.yaml"),
                    ),
                ),
            )

            client = Mock(spec=MatchBridgeClient)
            client.claim.return_value = None

            with CommandJournal(db_path) as journal:
                result = intake_one_cycle(config, client, journal)
                self.assertEqual(result.outcome, IntakeOutcome.NO_WORK)
                self.assertIsNone(journal.get("cmd-100"))

    def test_intake_unmanaged_server_key_fails_closed(self) -> None:
        """When claimed target serverKey is not in local registry, intake raises ProtocolError before observation."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = BridgeConfig(
                bridge_node_key="node-01",
                auth_api_base_url="https://auth.example.com",
                bridge_credential="secret_token",
                state_db_path=db_path,
                rcon_executable=Path("/usr/local/bin/rcon"),
                servers=(
                    ServerResourceConfig(
                        server_key="srv-local-1",
                        csgo_root=Path("/opt/cs2/game/csgo"),
                        rcon_config_path=Path("/etc/rcon/srv-local-1.yaml"),
                    ),
                ),
            )

            # Claim returns a command for unmanaged "srv-other-99"
            client = Mock(spec=MatchBridgeClient)
            client.claim.return_value = _sample_claimed_command(server_key="srv-other-99", command_id="cmd-unmanaged")

            with CommandJournal(db_path) as journal:
                with self.assertRaises(ProtocolError):
                    intake_one_cycle(config, client, journal)

                # Confirm command was not recorded
                self.assertIsNone(journal.get("cmd-unmanaged"))

    def test_intake_valid_command_observes_received_and_never_applying(self) -> None:
        """Valid claimed command is observed into journal as RECEIVED and never marked APPLYING in G1."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = BridgeConfig(
                bridge_node_key="node-01",
                auth_api_base_url="https://auth.example.com",
                bridge_credential="secret_token",
                state_db_path=db_path,
                rcon_executable=Path("/usr/local/bin/rcon"),
                servers=(
                    ServerResourceConfig(
                        server_key="srv-east-1",
                        csgo_root=Path("/opt/cs2/game/csgo"),
                        rcon_config_path=Path("/etc/rcon/srv-east-1.yaml"),
                    ),
                ),
            )

            client = Mock(spec=MatchBridgeClient)
            client.claim.return_value = _sample_claimed_command(server_key="srv-east-1", command_id="cmd-valid-1")

            with CommandJournal(db_path) as journal:
                result = intake_one_cycle(config, client, journal)
                self.assertEqual(result.outcome, IntakeOutcome.OBSERVED)
                self.assertEqual(result.command_id, "cmd-valid-1")

                entry = journal.get("cmd-valid-1")
                self.assertIsNotNone(entry)
                assert entry is not None
                # Must be RECEIVED
                self.assertEqual(entry.state, CommandState.RECEIVED)
                # G1 intake MUST NOT mark execution_started_at
                self.assertIsNone(entry.execution_started_at)

    @unittest.mock.patch("hsc_match_bridge.orchestration.wait_for_matchzy_prepared")
    @unittest.mock.patch("hsc_match_bridge.orchestration.load_matchzy_match")
    @unittest.mock.patch("hsc_match_bridge.orchestration.materialize_matchzy_config")
    def test_prepare_received_happy_path(
        self,
        mock_materialize: unittest.mock.MagicMock,
        mock_load_match: unittest.mock.MagicMock,
        mock_wait_prepared: unittest.mock.MagicMock,
    ) -> None:
        """Newly received command marks APPLYING, executes local side-effects, verifies PREPARED, records SUCCEEDED and submits result."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = BridgeConfig(
                bridge_node_key="node-01",
                auth_api_base_url="https://auth.example.com",
                bridge_credential="secret_token",
                state_db_path=db_path,
                rcon_executable=Path("/usr/local/bin/rcon"),
                servers=(
                    ServerResourceConfig(
                        server_key="srv-east-1",
                        csgo_root=Path("/opt/cs2/game/csgo"),
                        rcon_config_path=Path("/etc/rcon/srv-east-1.yaml"),
                    ),
                ),
            )

            client = Mock(spec=MatchBridgeClient)
            client.claim.return_value = _sample_claimed_command(server_key="srv-east-1", command_id="cmd-prep-1")
            mock_materialize.return_value = "hsc-match-bridge/1000001.json"
            mock_wait_prepared.return_value = True

            with CommandJournal(db_path) as journal:
                from hsc_match_bridge.orchestration import PrepareOutcome, prepare_one_cycle

                result = prepare_one_cycle(config, client, journal)
                self.assertEqual(result.outcome, PrepareOutcome.PREPARED)
                self.assertEqual(result.command_id, "cmd-prep-1")
                self.assertEqual(result.result_code, "PREPARED")

                # Journal entry state must be terminal SUCCEEDED with PREPARED result_code
                entry = journal.get("cmd-prep-1")
                self.assertIsNotNone(entry)
                assert entry is not None
                self.assertEqual(entry.state, CommandState.SUCCEEDED)
                self.assertEqual(entry.result_code, "PREPARED")
                self.assertIsNotNone(entry.execution_started_at)
                self.assertIsNotNone(entry.completed_at)

                # Central client submitted exactly SUCCEEDED / PREPARED with current lease token
                client.submit_result.assert_called_once_with(
                    command_id="cmd-prep-1",
                    lease_token="lease_tok_xyz",
                    outcome="SUCCEEDED",
                    result_code="PREPARED",
                    result=None,
                )

    @unittest.mock.patch("hsc_match_bridge.orchestration.inspect_matchzy_prepared")
    @unittest.mock.patch("hsc_match_bridge.orchestration.load_matchzy_match")
    @unittest.mock.patch("hsc_match_bridge.orchestration.materialize_matchzy_config")
    def test_prepare_applying_replay_uncertainty(
        self,
        mock_materialize: unittest.mock.MagicMock,
        mock_load_match: unittest.mock.MagicMock,
        mock_inspect_prepared: unittest.mock.MagicMock,
    ) -> None:
        """Existing APPLYING command never re-actuates; reconciles to SUCCEEDED if PREPARED or remains UNCERTAIN."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = BridgeConfig(
                bridge_node_key="node-01",
                auth_api_base_url="https://auth.example.com",
                bridge_credential="secret_token",
                state_db_path=db_path,
                rcon_executable=Path("/usr/local/bin/rcon"),
                servers=(
                    ServerResourceConfig(
                        server_key="srv-east-1",
                        csgo_root=Path("/opt/cs2/game/csgo"),
                        rcon_config_path=Path("/etc/rcon/srv-east-1.yaml"),
                    ),
                ),
            )

            client = Mock(spec=MatchBridgeClient)
            claimed = _sample_claimed_command(server_key="srv-east-1", command_id="cmd-applying-1")
            client.claim.return_value = claimed

            with CommandJournal(db_path) as journal:
                from hsc_match_bridge.models import CommandIdentity
                from hsc_match_bridge.orchestration import PrepareOutcome, prepare_one_cycle

                # Seed command in APPLYING state (simulating prior crash after mark_applying)
                identity = CommandIdentity(
                    command_id=claimed.command_id,
                    assignment_id=claimed.assignment_id,
                    server_key=claimed.target.server_key,
                    runtime_match_id=claimed.match_spec.runtime_match_id,
                    command_type=CommandType.PREPARE_MATCH,
                )
                journal.observe(identity)
                journal.mark_applying(claimed.command_id)

                # Case A: inspect_matchzy_prepared returns False -> UNCERTAIN, no re-actuation, remains APPLYING
                mock_inspect_prepared.return_value = False
                result_uncertain = prepare_one_cycle(config, client, journal)

                self.assertEqual(result_uncertain.outcome, PrepareOutcome.UNCERTAIN)
                mock_materialize.assert_not_called()
                mock_load_match.assert_not_called()
                client.submit_result.assert_not_called()
                entry_applying = journal.get("cmd-applying-1")
                assert entry_applying is not None
                self.assertEqual(entry_applying.state, CommandState.APPLYING)

                # Case B: inspect_matchzy_prepared returns True -> transitions to SUCCEEDED and submits PREPARED
                mock_inspect_prepared.return_value = True
                result_prepared = prepare_one_cycle(config, client, journal)

                self.assertEqual(result_prepared.outcome, PrepareOutcome.PREPARED)
                mock_materialize.assert_not_called()
                mock_load_match.assert_not_called()
                entry_succeeded = journal.get("cmd-applying-1")
                assert entry_succeeded is not None
                self.assertEqual(entry_succeeded.state, CommandState.SUCCEEDED)
                self.assertEqual(entry_succeeded.result_code, "PREPARED")
                client.submit_result.assert_called_once_with(
                    command_id="cmd-applying-1",
                    lease_token="lease_tok_xyz",
                    outcome="SUCCEEDED",
                    result_code="PREPARED",
                    result=None,
                )


if __name__ == "__main__":
    unittest.main()


