"""Domain models and exceptions for HSC Match Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CommandValidationError(Exception):
    """Raised when command identity or result fails domain validation."""


class JournalError(Exception):
    """Base exception for journal operations."""


class CommandConflictError(JournalError):
    """Raised when an immutable command identity or terminal result conflicts."""


class InvalidStateTransitionError(JournalError):
    """Raised when an invalid state transition is attempted."""


class SchemaVersionError(JournalError):
    """Raised when an unsupported database schema version is encountered."""


class CommandType(str, Enum):
    """Valid command types for the Match Bridge."""

    PREPARE_MATCH = "PREPARE_MATCH"


class CommandState(str, Enum):
    """Durable states in the command journal."""

    RECEIVED = "RECEIVED"
    APPLYING = "APPLYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CommandIdentity:
    """Immutable identity of a domain command."""

    command_id: str
    assignment_id: str
    server_key: str
    runtime_match_id: int
    command_type: CommandType = CommandType.PREPARE_MATCH

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, str) or not self.command_id.strip():
            raise CommandValidationError("command_id must be a non-empty string.")

        if not isinstance(self.assignment_id, str) or not self.assignment_id.strip():
            raise CommandValidationError("assignment_id must be a non-empty string.")

        if not isinstance(self.server_key, str):
            raise CommandValidationError("server_key must be a string.")

        trimmed_server_key = self.server_key.strip()
        if not trimmed_server_key:
            raise CommandValidationError("server_key cannot be empty.")
        if len(trimmed_server_key) > 64:
            raise CommandValidationError(
                f"server_key exceeds maximum length of 64 characters: '{trimmed_server_key}'"
            )
        if trimmed_server_key != self.server_key:
            object.__setattr__(self, "server_key", trimmed_server_key)

        if isinstance(self.runtime_match_id, bool) or not isinstance(self.runtime_match_id, int):
            raise CommandValidationError("runtime_match_id must be an integer.")
        if self.runtime_match_id < 1_000_000:
            raise CommandValidationError(
                f"runtime_match_id must be >= 1000000, got {self.runtime_match_id}."
            )

        if not isinstance(self.command_type, CommandType):
            try:
                object.__setattr__(self, "command_type", CommandType(self.command_type))
            except ValueError:
                raise CommandValidationError(
                    f"Invalid command_type: {self.command_type}. Only PREPARE_MATCH is supported."
                )

        if self.command_type != CommandType.PREPARE_MATCH:
            raise CommandValidationError(
                f"Invalid command_type: {self.command_type}. Only PREPARE_MATCH is supported."
            )


@dataclass(frozen=True)
class JournalEntry:
    """Durable state of a command recorded in the journal."""

    command_id: str
    assignment_id: str
    server_key: str
    runtime_match_id: int
    command_type: CommandType
    state: CommandState
    result_code: str | None
    result_json: str | None
    first_seen_at: str
    execution_started_at: str | None
    completed_at: str | None
    updated_at: str
