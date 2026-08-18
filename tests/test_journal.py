"""Tests protecting critical observable command journal invariants and contracts."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hsc_match_bridge.journal import CommandJournal
from hsc_match_bridge.models import (
    CommandConflictError,
    CommandIdentity,
    CommandState,
    CommandType,
    InvalidStateTransitionError,
    SchemaVersionError,
)


class TestJournalContracts(unittest.TestCase):
    """Observable contracts for the durable SQLite command journal."""

    def _sample_command(
        self,
        command_id: str = "cmd-001",
        assignment_id: str = "assign-100",
        server_key: str = "srv-east-1",
        runtime_match_id: int = 1_000_001,
        command_type: CommandType = CommandType.PREPARE_MATCH,
    ) -> CommandIdentity:
        return CommandIdentity(
            command_id=command_id,
            assignment_id=assignment_id,
            server_key=server_key,
            runtime_match_id=runtime_match_id,
            command_type=command_type,
        )

    def test_observe_creates_received_and_is_idempotent_or_fails_on_conflict(self) -> None:
        """Observing records RECEIVED, replay is idempotent, and conflicting identity fails closed."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            with CommandJournal(db_path) as journal:
                cmd = self._sample_command("cmd-obs-1")

                # New command -> RECEIVED
                entry = journal.observe(cmd)
                self.assertEqual(entry.command_id, "cmd-obs-1")
                self.assertEqual(entry.state, CommandState.RECEIVED)
                self.assertIsNotNone(entry.first_seen_at)

                # Replay identical command identity -> Idempotent
                replayed = journal.observe(cmd)
                self.assertEqual(replayed.command_id, entry.command_id)
                self.assertEqual(replayed.state, CommandState.RECEIVED)
                self.assertEqual(replayed.first_seen_at, entry.first_seen_at)

                # Conflicting immutable field with same command_id -> Fail closed
                conflicting_cmd = self._sample_command("cmd-obs-1", server_key="srv-other-2")
                with self.assertRaises(CommandConflictError):
                    journal.observe(conflicting_cmd)

    def test_lifecycle_transitions_and_terminal_immutability(self) -> None:
        """Lifecycle enforces RECEIVED -> APPLYING -> SUCCEEDED/FAILED, prevents regression and conflicting replay."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            with CommandJournal(db_path) as journal:
                # 1. Test direct terminal transition rejection from RECEIVED
                cmd1 = self._sample_command("cmd-life-1")
                journal.observe(cmd1)
                with self.assertRaises(InvalidStateTransitionError):
                    journal.mark_succeeded("cmd-life-1", result_code="SUCCESS")
                with self.assertRaises(InvalidStateTransitionError):
                    journal.mark_failed("cmd-life-1", result_code="ERROR_ERR")

                # 2. Transition RECEIVED -> APPLYING
                applying_entry = journal.mark_applying("cmd-life-1")
                self.assertEqual(applying_entry.state, CommandState.APPLYING)
                started_at = applying_entry.execution_started_at
                self.assertIsNotNone(started_at)

                # Repeated mark_applying is idempotent and preserves execution_started_at
                repeated_applying = journal.mark_applying("cmd-life-1")
                self.assertEqual(repeated_applying.state, CommandState.APPLYING)
                self.assertEqual(repeated_applying.execution_started_at, started_at)

                # 3. Transition APPLYING -> SUCCEEDED
                succeeded_entry = journal.mark_succeeded(
                    "cmd-life-1", result_code="MATCH_PREPARED", result={"port": 27015}
                )
                self.assertEqual(succeeded_entry.state, CommandState.SUCCEEDED)
                self.assertEqual(succeeded_entry.result_code, "MATCH_PREPARED")

                # Terminal state cannot regress to APPLYING
                with self.assertRaises(InvalidStateTransitionError):
                    journal.mark_applying("cmd-life-1")

                # Terminal replay with identical result is idempotent
                terminal_replay = journal.mark_succeeded(
                    "cmd-life-1", result_code="MATCH_PREPARED", result={"port": 27015}
                )
                self.assertEqual(terminal_replay.state, CommandState.SUCCEEDED)

                # Terminal replay with conflicting result fails closed
                with self.assertRaises(CommandConflictError):
                    journal.mark_succeeded(
                        "cmd-life-1", result_code="DIFFERENT_CODE", result={"port": 27015}
                    )

                # 4. Verify FAILED lifecycle on separate command
                cmd2 = self._sample_command("cmd-life-2")
                journal.observe(cmd2)
                journal.mark_applying("cmd-life-2")
                failed_entry = journal.mark_failed("cmd-life-2", result_code="PORT_BUSY")
                self.assertEqual(failed_entry.state, CommandState.FAILED)
                self.assertEqual(failed_entry.result_code, "PORT_BUSY")

                with self.assertRaises(InvalidStateTransitionError):
                    journal.mark_succeeded("cmd-life-2", result_code="MATCH_PREPARED")

    def test_reopen_preserves_applying_execution_uncertainty(self) -> None:
        """A command persisted as APPLYING remains APPLYING after DB close/reopen without auto-reset or auto-retry."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"

            # 1. Open journal, observe and start execution
            with CommandJournal(db_path) as journal:
                cmd = self._sample_command("cmd-crash-1")
                journal.observe(cmd)
                applying_entry = journal.mark_applying("cmd-crash-1")
                self.assertEqual(applying_entry.state, CommandState.APPLYING)
                original_started_at = applying_entry.execution_started_at

            # 2. Reopen SQLite database fresh from disk
            with CommandJournal(db_path) as reopened_journal:
                reopened_entry = reopened_journal.get("cmd-crash-1")
                self.assertIsNotNone(reopened_entry)
                assert reopened_entry is not None
                # Must remain APPLYING (representing crash uncertainty)
                self.assertEqual(reopened_entry.state, CommandState.APPLYING)
                self.assertEqual(reopened_entry.execution_started_at, original_started_at)

    def test_unsupported_schema_version_fails_closed(self) -> None:
        """Initializing CommandJournal on a database with unsupported user_version raises SchemaVersionError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "journal.db"
            # Set up a database with unsupported user_version = 2 directly
            conn = sqlite3.connect(str(db_path))
            conn.execute("PRAGMA user_version = 2")
            conn.close()

            with self.assertRaises(SchemaVersionError):
                CommandJournal(db_path)


if __name__ == "__main__":
    unittest.main()
