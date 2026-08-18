"""Intake orchestration boundary for HSC Match Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hsc_match_bridge.client import MatchBridgeClient
from hsc_match_bridge.config import BridgeConfig
from hsc_match_bridge.journal import CommandJournal
from hsc_match_bridge.models import CommandIdentity, CommandType
from hsc_match_bridge.protocol import ProtocolError


class IntakeOutcome(str, Enum):
    """Outcome of an intake cycle."""

    NO_WORK = "NO_WORK"
    OBSERVED = "OBSERVED"


@dataclass(frozen=True)
class IntakeResult:
    """Result of an intake cycle execution."""

    outcome: IntakeOutcome
    command_id: str | None = None


def intake_one_cycle(
    config: BridgeConfig,
    client: MatchBridgeClient,
    journal: CommandJournal,
) -> IntakeResult:
    """Execute one intake cycle: claim command -> validate -> verify local server ownership -> journal.observe."""
    claimed = client.claim()
    if claimed is None:
        return IntakeResult(outcome=IntakeOutcome.NO_WORK)

    # Validate local server ownership against configured registry
    if claimed.target.server_key not in config.server_keys:
        raise ProtocolError(
            f"Claimed serverKey '{claimed.target.server_key}' is not managed by this bridge node registry."
        )

    # Construct immutable domain command identity and observe into SQLite journal
    identity = CommandIdentity(
        command_id=claimed.command_id,
        assignment_id=claimed.assignment_id,
        server_key=claimed.target.server_key,
        runtime_match_id=claimed.match_spec.runtime_match_id,
        command_type=CommandType.PREPARE_MATCH,
    )

    # Observation records state as RECEIVED. G1 does NOT call mark_applying().
    journal.observe(identity)

    return IntakeResult(
        outcome=IntakeOutcome.OBSERVED,
        command_id=claimed.command_id,
    )
