"""HSC Match Bridge foundation package."""

from hsc_match_bridge.config import (
    BridgeConfig,
    ConfigurationError,
    ServerResourceConfig,
    load_config,
    parse_server_registry,
)
from hsc_match_bridge.journal import (
    CURRENT_SCHEMA_VERSION,
    CommandJournal,
)
from hsc_match_bridge.main import main
from hsc_match_bridge.matchzy import (
    render_matchzy_config,
    serialize_matchzy_config,
)
from hsc_match_bridge.matchzy_actuator import (
    MatchZyActuationError,
    execute_rcon_command,
    load_matchzy_match,
    materialize_matchzy_config,
)
from hsc_match_bridge.matchzy_verifier import (
    inspect_matchzy_prepared,
    wait_for_matchzy_prepared,
)
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
from hsc_match_bridge.orchestration import (
    IntakeOutcome,
    IntakeResult,
    PrepareOutcome,
    PrepareResult,
    intake_one_cycle,
    prepare_one_cycle,
)

__version__ = "0.1.0"

__all__ = [
    "BridgeConfig",
    "CommandConflictError",
    "CommandIdentity",
    "CommandJournal",
    "CommandState",
    "CommandType",
    "CommandValidationError",
    "ConfigurationError",
    "CURRENT_SCHEMA_VERSION",
    "IntakeOutcome",
    "IntakeResult",
    "InvalidStateTransitionError",
    "JournalEntry",
    "JournalError",
    "MatchZyActuationError",
    "PrepareOutcome",
    "PrepareResult",
    "SchemaVersionError",
    "ServerResourceConfig",
    "execute_rcon_command",
    "inspect_matchzy_prepared",
    "intake_one_cycle",
    "load_config",
    "load_matchzy_match",
    "main",
    "materialize_matchzy_config",
    "parse_server_registry",
    "prepare_one_cycle",
    "render_matchzy_config",
    "serialize_matchzy_config",
    "wait_for_matchzy_prepared",
]
