"""Durable local SQLite command journal for HSC Match Bridge."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hsc_match_bridge.models import (
    CommandConflictError,
    CommandIdentity,
    CommandState,
    CommandType,
    CommandValidationError,
    InvalidStateTransitionError,
    JournalEntry,
    JournalError,
    SchemaVersionError,
)

CURRENT_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    """Return current UTC timestamp formatted as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _serialize_result(result: dict[str, Any] | None) -> str | None:
    """Serialize optional structured result deterministically to JSON."""
    if result is None:
        return None
    try:
        return json.dumps(result, sort_keys=True, separators=(",", ":"))
    except Exception as e:
        raise CommandValidationError(f"Result payload cannot be serialized to JSON: {e}") from e


class CommandJournal:
    """Durable SQLite-backed command journal."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._open_and_initialize()

    def _open_and_initialize(self) -> None:
        """Open SQLite database connection, apply durability PRAGMAs and initialize/verify schema."""
        parent = self._db_path.parent
        if not parent.exists() or not parent.is_dir():
            raise JournalError(
                f"Cannot open journal: parent directory does not exist or is not a directory: {parent}"
            )

        try:
            self._conn = sqlite3.connect(
                str(self._db_path),
                timeout=30.0,
                isolation_level=None,  # Manual transaction management
            )
            self._conn.row_factory = sqlite3.Row

            # Apply durability-oriented settings
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = FULL")
            self._conn.execute("PRAGMA foreign_keys = ON")

            self._initialize_and_check_schema()
        except JournalError:
            self.close()
            raise
        except Exception as e:
            self.close()
            raise JournalError(f"Failed to initialize journal database at '{self._db_path}': {e}") from e

    def _initialize_and_check_schema(self) -> None:
        """Create schema tables if new, or verify supported schema version using PRAGMA user_version."""
        assert self._conn is not None

        cur = self._conn.execute("PRAGMA user_version")
        row = cur.fetchone()
        current_version = int(row[0]) if row is not None else 0

        if current_version == 0:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS command_journal (
                        command_id TEXT PRIMARY KEY,
                        assignment_id TEXT NOT NULL,
                        server_key TEXT NOT NULL,
                        runtime_match_id INTEGER NOT NULL,
                        command_type TEXT NOT NULL,
                        state TEXT NOT NULL,
                        result_code TEXT,
                        result_json TEXT,
                        first_seen_at TEXT NOT NULL,
                        execution_started_at TEXT,
                        completed_at TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        elif current_version == CURRENT_SCHEMA_VERSION:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS command_journal (
                        command_id TEXT PRIMARY KEY,
                        assignment_id TEXT NOT NULL,
                        server_key TEXT NOT NULL,
                        runtime_match_id INTEGER NOT NULL,
                        command_type TEXT NOT NULL,
                        state TEXT NOT NULL,
                        result_code TEXT,
                        result_json TEXT,
                        first_seen_at TEXT NOT NULL,
                        execution_started_at TEXT,
                        completed_at TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        else:
            raise SchemaVersionError(
                f"Unsupported journal schema version: {current_version}. "
                f"Expected version {CURRENT_SCHEMA_VERSION}."
            )

    def _row_to_entry(self, row: sqlite3.Row) -> JournalEntry:
        """Convert a database row into an immutable JournalEntry dataclass."""
        return JournalEntry(
            command_id=row["command_id"],
            assignment_id=row["assignment_id"],
            server_key=row["server_key"],
            runtime_match_id=row["runtime_match_id"],
            command_type=CommandType(row["command_type"]),
            state=CommandState(row["state"]),
            result_code=row["result_code"],
            result_json=row["result_json"],
            first_seen_at=row["first_seen_at"],
            execution_started_at=row["execution_started_at"],
            completed_at=row["completed_at"],
            updated_at=row["updated_at"],
        )

    def observe(self, command: CommandIdentity) -> JournalEntry:
        """Durably observe a command. Idempotent on identical match; fails closed on conflicting identity."""
        if self._conn is None:
            raise JournalError("Journal is closed.")

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self._conn.execute(
                """
                SELECT * FROM command_journal WHERE command_id = ?
                """,
                (command.command_id,),
            )
            row = cur.fetchone()

            if row is not None:
                # Check for conflicting immutable identity
                if (
                    row["assignment_id"] != command.assignment_id
                    or row["server_key"] != command.server_key
                    or row["runtime_match_id"] != command.runtime_match_id
                    or row["command_type"] != command.command_type.value
                ):
                    raise CommandConflictError(
                        f"Command '{command.command_id}' already exists with conflicting immutable identity."
                    )
                self._conn.execute("COMMIT")
                return self._row_to_entry(row)

            # Insert new command in RECEIVED state
            now_iso = _utc_now_iso()
            self._conn.execute(
                """
                INSERT INTO command_journal (
                    command_id, assignment_id, server_key, runtime_match_id,
                    command_type, state, result_code, result_json,
                    first_seen_at, execution_started_at, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, ?)
                """,
                (
                    command.command_id,
                    command.assignment_id,
                    command.server_key,
                    command.runtime_match_id,
                    command.command_type.value,
                    CommandState.RECEIVED.value,
                    now_iso,
                    now_iso,
                ),
            )
            self._conn.execute("COMMIT")
            return self.get(command.command_id)  # type: ignore[return-value]
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def mark_applying(self, command_id: str) -> JournalEntry:
        """Mark command execution as started before local side effect. Idempotent if already APPLYING."""
        if self._conn is None:
            raise JournalError("Journal is closed.")

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self._conn.execute(
                "SELECT * FROM command_journal WHERE command_id = ?",
                (command_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise JournalError(f"Command '{command_id}' not found in journal.")

            current_state = row["state"]
            if current_state == CommandState.APPLYING.value:
                # Idempotent: preserve original execution_started_at and state
                self._conn.execute("COMMIT")
                return self._row_to_entry(row)

            if current_state in (CommandState.SUCCEEDED.value, CommandState.FAILED.value):
                raise InvalidStateTransitionError(
                    f"Cannot transition terminal command '{command_id}' from {current_state} to APPLYING."
                )

            if current_state != CommandState.RECEIVED.value:
                raise InvalidStateTransitionError(
                    f"Invalid state transition for command '{command_id}': {current_state} -> APPLYING."
                )

            now_iso = _utc_now_iso()
            self._conn.execute(
                """
                UPDATE command_journal
                SET state = ?, execution_started_at = ?, updated_at = ?
                WHERE command_id = ?
                """,
                (CommandState.APPLYING.value, now_iso, now_iso, command_id),
            )
            self._conn.execute("COMMIT")
            return self.get(command_id)  # type: ignore[return-value]
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def mark_succeeded(
        self,
        command_id: str,
        result_code: str,
        result: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Record successful terminal command execution. Requires prior APPLYING state."""
        if self._conn is None:
            raise JournalError("Journal is closed.")

        if not isinstance(result_code, str) or not result_code.strip():
            raise CommandValidationError("result_code must be a non-empty string.")
        trimmed_result_code = result_code.strip()
        result_json = _serialize_result(result)

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self._conn.execute(
                "SELECT * FROM command_journal WHERE command_id = ?",
                (command_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise JournalError(f"Command '{command_id}' not found in journal.")

            current_state = row["state"]
            if current_state == CommandState.RECEIVED.value:
                raise InvalidStateTransitionError(
                    f"Cannot transition command '{command_id}' directly from RECEIVED to SUCCEEDED. "
                    "Execution must first be durably marked APPLYING."
                )

            if current_state == CommandState.SUCCEEDED.value:
                if (
                    row["result_code"] == trimmed_result_code
                    and row["result_json"] == result_json
                ):
                    self._conn.execute("COMMIT")
                    return self._row_to_entry(row)
                raise CommandConflictError(
                    f"Command '{command_id}' already completed as SUCCEEDED with conflicting result data."
                )

            if current_state == CommandState.FAILED.value:
                raise InvalidStateTransitionError(
                    f"Cannot transition terminal command '{command_id}' from FAILED to SUCCEEDED."
                )

            if current_state != CommandState.APPLYING.value:
                raise InvalidStateTransitionError(
                    f"Invalid state transition for command '{command_id}': {current_state} -> SUCCEEDED."
                )

            now_iso = _utc_now_iso()
            self._conn.execute(
                """
                UPDATE command_journal
                SET state = ?, result_code = ?, result_json = ?, completed_at = ?, updated_at = ?
                WHERE command_id = ?
                """,
                (
                    CommandState.SUCCEEDED.value,
                    trimmed_result_code,
                    result_json,
                    now_iso,
                    now_iso,
                    command_id,
                ),
            )
            self._conn.execute("COMMIT")
            return self.get(command_id)  # type: ignore[return-value]
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def mark_failed(
        self,
        command_id: str,
        result_code: str,
        result: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Record failed terminal command execution. Requires prior APPLYING state."""
        if self._conn is None:
            raise JournalError("Journal is closed.")

        if not isinstance(result_code, str) or not result_code.strip():
            raise CommandValidationError("result_code must be a non-empty string.")
        trimmed_result_code = result_code.strip()
        result_json = _serialize_result(result)

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self._conn.execute(
                "SELECT * FROM command_journal WHERE command_id = ?",
                (command_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise JournalError(f"Command '{command_id}' not found in journal.")

            current_state = row["state"]
            if current_state == CommandState.RECEIVED.value:
                raise InvalidStateTransitionError(
                    f"Cannot transition command '{command_id}' directly from RECEIVED to FAILED. "
                    "Execution must first be durably marked APPLYING."
                )

            if current_state == CommandState.FAILED.value:
                if (
                    row["result_code"] == trimmed_result_code
                    and row["result_json"] == result_json
                ):
                    self._conn.execute("COMMIT")
                    return self._row_to_entry(row)
                raise CommandConflictError(
                    f"Command '{command_id}' already completed as FAILED with conflicting result data."
                )

            if current_state == CommandState.SUCCEEDED.value:
                raise InvalidStateTransitionError(
                    f"Cannot transition terminal command '{command_id}' from SUCCEEDED to FAILED."
                )

            if current_state != CommandState.APPLYING.value:
                raise InvalidStateTransitionError(
                    f"Invalid state transition for command '{command_id}': {current_state} -> FAILED."
                )

            now_iso = _utc_now_iso()
            self._conn.execute(
                """
                UPDATE command_journal
                SET state = ?, result_code = ?, result_json = ?, completed_at = ?, updated_at = ?
                WHERE command_id = ?
                """,
                (
                    CommandState.FAILED.value,
                    trimmed_result_code,
                    result_json,
                    now_iso,
                    now_iso,
                    command_id,
                ),
            )
            self._conn.execute("COMMIT")
            return self.get(command_id)  # type: ignore[return-value]
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def get(self, command_id: str) -> JournalEntry | None:
        """Retrieve durable journal entry for command_id, or None if not found."""
        if self._conn is None:
            raise JournalError("Journal is closed.")

        cur = self._conn.execute(
            "SELECT * FROM command_journal WHERE command_id = ?",
            (command_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def close(self) -> None:
        """Close SQLite database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def __enter__(self) -> CommandJournal:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
