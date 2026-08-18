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
    "InvalidStateTransitionError",
    "JournalEntry",
    "JournalError",
    "SchemaVersionError",
    "ServerResourceConfig",
    "load_config",
    "main",
    "parse_server_registry",
]
