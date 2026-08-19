"""Tests protecting observable contracts of the persistent bridge runtime loop."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from hsc_match_bridge.client import MatchBridgeClient
from hsc_match_bridge.config import BridgeConfig, ServerResourceConfig
from hsc_match_bridge.journal import CommandJournal
from hsc_match_bridge.main import build_parser
from hsc_match_bridge.orchestration import PrepareOutcome, PrepareResult
from hsc_match_bridge.runtime import (
    BACKOFF_INITIAL_SECONDS,
    BACKOFF_MAX_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    IDLE_POLL_INTERVAL_SECONDS,
    run_bridge_loop,
)


def _make_config(state_db_path: Path) -> BridgeConfig:
    return BridgeConfig(
        bridge_node_key="node-01",
        auth_api_base_url="https://auth.example.com",
        bridge_credential="secret_token",
        state_db_path=state_db_path,
        rcon_executable=Path("/usr/local/bin/rcon"),
        servers=(
            ServerResourceConfig(
                server_key="srv-east-1",
                csgo_root=Path("/opt/cs2/game/csgo"),
                rcon_config_path=Path("/etc/rcon/srv-east-1.yaml"),
            ),
        ),
    )


class TestRuntimeContracts(unittest.TestCase):
    """Observable contracts for persistent daemon loop (G3-A)."""

    def test_runtime_heartbeat_at_startup_and_polling_cadence(self) -> None:
        """Runtime sends heartbeat immediately on startup and polls for prepare work."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = _make_config(db_path)
            client = Mock(spec=MatchBridgeClient)
            client.heartbeat.return_value = True

            fake_time = 100.0

            def time_fn() -> float:
                return fake_time

            stop_event = Mock(spec=threading.Event)
            # Iteration 1: heartbeat sent, prepare called -> NO_WORK -> stop_event.wait(1.0) -> stop
            stop_event.is_set.side_effect = [False, False, True]

            with CommandJournal(db_path) as journal:
                with patch("hsc_match_bridge.runtime.prepare_one_cycle") as mock_prepare:
                    mock_prepare.return_value = PrepareResult(outcome=PrepareOutcome.NO_WORK)

                    run_bridge_loop(
                        config=config,
                        client=client,
                        journal=journal,
                        stop_event=stop_event,
                        time_fn=time_fn,
                    )

            client.heartbeat.assert_called_once()
            mock_prepare.assert_called_once_with(config, client, journal)
            stop_event.wait.assert_called_once_with(IDLE_POLL_INTERVAL_SECONDS)

    def test_runtime_idle_poll_uses_interruptible_wait(self) -> None:
        """When NO_WORK is returned, runtime waits for IDLE_POLL_INTERVAL_SECONDS via stop_event."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = _make_config(db_path)
            client = Mock(spec=MatchBridgeClient)
            client.heartbeat.return_value = True

            stop_event = Mock(spec=threading.Event)
            # Loop once and stop
            stop_event.is_set.side_effect = [False, False, True]

            with CommandJournal(db_path) as journal:
                with patch("hsc_match_bridge.runtime.prepare_one_cycle") as mock_prepare:
                    mock_prepare.return_value = PrepareResult(outcome=PrepareOutcome.NO_WORK)

                    run_bridge_loop(
                        config=config,
                        client=client,
                        journal=journal,
                        stop_event=stop_event,
                        time_fn=lambda: 0.0,
                    )

            stop_event.wait.assert_called_once_with(1.0)

    def test_runtime_connection_error_applies_bounded_backoff_and_resets(self) -> None:
        """ConnectionError triggers exponential backoff capped at max, and resets on success."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = _make_config(db_path)
            client = Mock(spec=MatchBridgeClient)
            client.heartbeat.return_value = True

            stop_event = Mock(spec=threading.Event)
            # 7 iterations before stop
            stop_event.is_set.side_effect = [
                False, False,  # iter 1 (fail 1s)
                False, False,  # iter 2 (fail 2s)
                False, False,  # iter 3 (fail 4s)
                False, False,  # iter 4 (fail 8s)
                False, False,  # iter 5 (fail 15s - capped)
                False, False,  # iter 6 (success non-NO_WORK -> reset backoff -> no wait)
                False, False,  # iter 7 (fail after recovery -> backoff resets to 1s)
                True,
            ]

            with CommandJournal(db_path) as journal:
                with patch("hsc_match_bridge.runtime.prepare_one_cycle") as mock_prepare:
                    mock_prepare.side_effect = [
                        ConnectionError("network down"),
                        ConnectionError("network down"),
                        ConnectionError("network down"),
                        ConnectionError("network down"),
                        ConnectionError("network down"),
                        PrepareResult(
                            outcome=PrepareOutcome.PREPARED,
                            command_id="cmd-recovered",
                            result_code="PREPARED",
                        ),
                        ConnectionError("network down again"),
                    ]

                    run_bridge_loop(
                        config=config,
                        client=client,
                        journal=journal,
                        stop_event=stop_event,
                        time_fn=lambda: 0.0,
                    )

            expected_waits = [
                call(1.0),   # 1s backoff
                call(2.0),   # 2s backoff
                call(4.0),   # 4s backoff
                call(8.0),   # 8s backoff
                call(15.0),  # 15s backoff (capped at BACKOFF_MAX_SECONDS)
                call(1.0),   # backoff resets to initial 1s after recovery
            ]
            self.assertEqual(stop_event.wait.call_args_list, expected_waits)

    def test_runtime_stop_event_terminates_cleanly_without_processing(self) -> None:
        """Setting stop_event before or during loop exits gracefully without starting new cycles."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            config = _make_config(db_path)
            client = Mock(spec=MatchBridgeClient)

            stop_event = threading.Event()
            stop_event.set()

            with CommandJournal(db_path) as journal:
                with patch("hsc_match_bridge.runtime.prepare_one_cycle") as mock_prepare:
                    run_bridge_loop(
                        config=config,
                        client=client,
                        journal=journal,
                        stop_event=stop_event,
                    )

            client.heartbeat.assert_not_called()
            mock_prepare.assert_not_called()

    def test_cli_parser_supports_both_check_and_run_subcommands(self) -> None:
        """CLI parser accepts 'check' and 'run' subcommands."""
        parser = build_parser()

        args_check = parser.parse_args(["check"])
        self.assertEqual(args_check.subcommand, "check")

        args_run = parser.parse_args(["run"])
        self.assertEqual(args_run.subcommand, "run")
