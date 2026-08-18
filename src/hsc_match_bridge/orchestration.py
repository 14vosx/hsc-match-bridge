"""Intake and prepare orchestration boundaries for HSC Match Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hsc_match_bridge.client import MatchBridgeClient
from hsc_match_bridge.config import BridgeConfig, ServerResourceConfig
from hsc_match_bridge.journal import CommandJournal
from hsc_match_bridge.matchzy_actuator import (
    MatchZyActuationError,
    load_matchzy_match,
    materialize_matchzy_config,
)
from hsc_match_bridge.matchzy_verifier import (
    inspect_matchzy_prepared,
    wait_for_matchzy_prepared,
)
from hsc_match_bridge.models import (
    CommandIdentity,
    CommandState,
    CommandType,
    CommandValidationError,
)
from hsc_match_bridge.protocol import ClaimedCommand, ProtocolError


class IntakeOutcome(str, Enum):
    """Outcome of an intake cycle."""

    NO_WORK = "NO_WORK"
    OBSERVED = "OBSERVED"


@dataclass(frozen=True)
class IntakeResult:
    """Result of an intake cycle execution."""

    outcome: IntakeOutcome
    command_id: str | None = None


class PrepareOutcome(str, Enum):
    """Outcome of a prepare orchestration cycle."""

    NO_WORK = "NO_WORK"
    PREPARED = "PREPARED"
    REPORTED_PREPARED = "REPORTED_PREPARED"
    FAILED = "FAILED"
    REPORTED_FAILED = "REPORTED_FAILED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class PrepareResult:
    """Result of a prepare orchestration cycle execution."""

    outcome: PrepareOutcome
    command_id: str | None = None
    result_code: str | None = None


def _resolve_server(config: BridgeConfig, server_key: str) -> ServerResourceConfig:
    for server in config.servers:
        if server.server_key == server_key:
            return server
    raise ProtocolError(
        f"Claimed serverKey '{server_key}' is not managed by this bridge node registry."
    )


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
    _resolve_server(config, claimed.target.server_key)

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


def prepare_one_cycle(
    config: BridgeConfig,
    client: MatchBridgeClient,
    journal: CommandJournal,
) -> PrepareResult:
    """Execute one prepare cycle: claim -> observe -> state-aware execution/reconciliation -> submit result."""
    claimed = client.claim()
    if claimed is None:
        return PrepareResult(outcome=PrepareOutcome.NO_WORK)

    server = _resolve_server(config, claimed.target.server_key)

    identity = CommandIdentity(
        command_id=claimed.command_id,
        assignment_id=claimed.assignment_id,
        server_key=claimed.target.server_key,
        runtime_match_id=claimed.match_spec.runtime_match_id,
        command_type=CommandType.PREPARE_MATCH,
    )

    entry = journal.observe(identity)

    # State-aware branch
    if entry.state == CommandState.SUCCEEDED:
        # Terminal reconciliation
        if entry.result_code != "PREPARED":
            raise CommandValidationError(
                f"Command '{claimed.command_id}' is locally SUCCEEDED with unexpected result_code: {entry.result_code}"
            )
        client.submit_result(
            command_id=claimed.command_id,
            lease_token=claimed.lease_token,
            outcome="SUCCEEDED",
            result_code="PREPARED",
            result=None,
        )
        return PrepareResult(
            outcome=PrepareOutcome.REPORTED_PREPARED,
            command_id=claimed.command_id,
            result_code="PREPARED",
        )

    if entry.state == CommandState.FAILED:
        # Terminal reconciliation for durable failure
        result_code = entry.result_code or "LOCAL_ACTUATION_FAILED"
        client.submit_result(
            command_id=claimed.command_id,
            lease_token=claimed.lease_token,
            outcome="FAILED",
            result_code=result_code,
            result=None,
        )
        return PrepareResult(
            outcome=PrepareOutcome.REPORTED_FAILED,
            command_id=claimed.command_id,
            result_code=result_code,
        )

    if entry.state == CommandState.APPLYING:
        # Uncertain prior execution: NEVER re-actuate, check verifier only
        is_prepared = inspect_matchzy_prepared(
            csgo_root=server.csgo_root,
            rcon_executable=config.rcon_executable,
            rcon_config_path=server.rcon_config_path,
            match_spec=claimed.match_spec,
        )
        if is_prepared:
            journal.mark_succeeded(
                command_id=claimed.command_id,
                result_code="PREPARED",
                result=None,
            )
            client.submit_result(
                command_id=claimed.command_id,
                lease_token=claimed.lease_token,
                outcome="SUCCEEDED",
                result_code="PREPARED",
                result=None,
            )
            return PrepareResult(
                outcome=PrepareOutcome.PREPARED,
                command_id=claimed.command_id,
                result_code="PREPARED",
            )
        # Cannot be proven PREPARED: remain APPLYING, do not retry or mark FAILED
        return PrepareResult(
            outcome=PrepareOutcome.UNCERTAIN,
            command_id=claimed.command_id,
        )

    # Newly observed command in RECEIVED state:
    # 1. Durably mark APPLYING before first local side effect
    journal.mark_applying(claimed.command_id)

    # 2. Side effects: materialization and RCON load
    try:
        rel_config_path = materialize_matchzy_config(
            csgo_root=server.csgo_root,
            match_spec=claimed.match_spec,
        )
        load_matchzy_match(
            rcon_executable=config.rcon_executable,
            rcon_config_path=server.rcon_config_path,
            relative_config_path=rel_config_path,
        )
    except MatchZyActuationError as e:
        if not e.execution_uncertain:
            # Certain no-RCON execution failure
            journal.mark_failed(
                command_id=claimed.command_id,
                result_code="LOCAL_ACTUATION_FAILED",
                result=None,
            )
            client.submit_result(
                command_id=claimed.command_id,
                lease_token=claimed.lease_token,
                outcome="FAILED",
                result_code="LOCAL_ACTUATION_FAILED",
                result=None,
            )
            return PrepareResult(
                outcome=PrepareOutcome.FAILED,
                command_id=claimed.command_id,
                result_code="LOCAL_ACTUATION_FAILED",
            )
        # Uncertain execution failure (e.g. timeout after launch): remain APPLYING
        return PrepareResult(
            outcome=PrepareOutcome.UNCERTAIN,
            command_id=claimed.command_id,
        )

    # 3. Bounded PREPARED verification
    is_prepared = wait_for_matchzy_prepared(
        csgo_root=server.csgo_root,
        rcon_executable=config.rcon_executable,
        rcon_config_path=server.rcon_config_path,
        match_spec=claimed.match_spec,
    )

    if not is_prepared:
        # Verification timed out / incomplete evidence: remain APPLYING
        return PrepareResult(
            outcome=PrepareOutcome.UNCERTAIN,
            command_id=claimed.command_id,
        )

    # 4. Terminal success recording and Central result submission
    journal.mark_succeeded(
        command_id=claimed.command_id,
        result_code="PREPARED",
        result=None,
    )
    client.submit_result(
        command_id=claimed.command_id,
        lease_token=claimed.lease_token,
        outcome="SUCCEEDED",
        result_code="PREPARED",
        result=None,
    )
    return PrepareResult(
        outcome=PrepareOutcome.PREPARED,
        command_id=claimed.command_id,
        result_code="PREPARED",
    )
