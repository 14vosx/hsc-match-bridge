"""Configuration loading and validation for HSC Match Bridge."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigurationError(Exception):
    """Raised when configuration or registry fails validation."""


@dataclass(frozen=True)
class ServerResourceConfig:
    """Validated server resource managed by the bridge node."""

    server_key: str


@dataclass(frozen=True)
class BridgeConfig:
    """Immutable bridge node configuration."""

    bridge_node_key: str
    state_db_path: Path
    servers: tuple[ServerResourceConfig, ...]

    @property
    def server_keys(self) -> tuple[str, ...]:
        return tuple(s.server_key for s in self.servers)


def parse_server_registry(file_path: Path) -> tuple[ServerResourceConfig, ...]:
    """Parse and strictly validate the local server registry JSON file."""
    if not file_path.is_file():
        raise ConfigurationError(
            f"HSC_BRIDGE_SERVERS_FILE does not exist or is not a file: {file_path}"
        )

    try:
        raw_text = file_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception as e:
        raise ConfigurationError(
            f"Failed to parse server registry file '{file_path}': {e}"
        ) from e

    if not isinstance(data, dict):
        raise ConfigurationError("Server registry root must be a JSON object.")

    # Strict schema: reject unknown root keys
    allowed_root_keys = {"schemaVersion", "servers"}
    unknown_root_keys = set(data.keys()) - allowed_root_keys
    if unknown_root_keys:
        raise ConfigurationError(
            f"Unknown fields in server registry root: {sorted(unknown_root_keys)}"
        )

    # Validate schemaVersion
    if "schemaVersion" not in data:
        raise ConfigurationError("Server registry missing required field: 'schemaVersion'.")

    schema_version = data["schemaVersion"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
        raise ConfigurationError(
            f"Unsupported server registry schemaVersion: {schema_version}. Expected integer 1."
        )

    # Validate servers list
    if "servers" not in data:
        raise ConfigurationError("Server registry missing required field: 'servers'.")

    servers_data = data["servers"]
    if not isinstance(servers_data, list):
        raise ConfigurationError("Field 'servers' must be a JSON array.")

    if not servers_data:
        raise ConfigurationError("Server registry 'servers' array must contain at least one server.")

    seen_keys: set[str] = set()
    validated_servers: list[ServerResourceConfig] = []

    allowed_server_keys = {"serverKey"}

    for idx, entry in enumerate(servers_data):
        if not isinstance(entry, dict):
            raise ConfigurationError(f"Server entry at index {idx} must be a JSON object.")

        unknown_entry_keys = set(entry.keys()) - allowed_server_keys
        if unknown_entry_keys:
            raise ConfigurationError(
                f"Unknown fields in server entry at index {idx}: {sorted(unknown_entry_keys)}"
            )

        if "serverKey" not in entry:
            raise ConfigurationError(f"Server entry at index {idx} missing required field 'serverKey'.")

        raw_server_key = entry["serverKey"]
        if not isinstance(raw_server_key, str):
            raise ConfigurationError(f"Field 'serverKey' at index {idx} must be a string.")

        server_key = raw_server_key.strip()
        if not server_key:
            raise ConfigurationError(f"Field 'serverKey' at index {idx} cannot be empty.")

        if len(server_key) > 64:
            raise ConfigurationError(
                f"Field 'serverKey' at index {idx} exceeds maximum length of 64 characters: '{server_key}'"
            )

        if server_key in seen_keys:
            raise ConfigurationError(
                f"Duplicate serverKey found in registry after normalization: '{server_key}'"
            )

        seen_keys.add(server_key)
        validated_servers.append(ServerResourceConfig(server_key=server_key))

    return tuple(validated_servers)


def load_config(env: Mapping[str, str] | None = None) -> BridgeConfig:
    """Load and validate bridge configuration from environment variables."""
    if env is None:
        env = os.environ

    # HSC_BRIDGE_NODE_KEY
    if "HSC_BRIDGE_NODE_KEY" not in env:
        raise ConfigurationError("HSC_BRIDGE_NODE_KEY environment variable is required.")

    raw_node_key = env["HSC_BRIDGE_NODE_KEY"]
    if not isinstance(raw_node_key, str):
        raise ConfigurationError("HSC_BRIDGE_NODE_KEY must be a string.")

    bridge_node_key = raw_node_key.strip()
    if not bridge_node_key:
        raise ConfigurationError("HSC_BRIDGE_NODE_KEY cannot be empty.")

    if len(bridge_node_key) > 64:
        raise ConfigurationError(
            f"HSC_BRIDGE_NODE_KEY exceeds maximum length of 64 characters: '{bridge_node_key}'"
        )

    # HSC_BRIDGE_STATE_DB
    if "HSC_BRIDGE_STATE_DB" not in env:
        raise ConfigurationError("HSC_BRIDGE_STATE_DB environment variable is required.")

    raw_state_db = env["HSC_BRIDGE_STATE_DB"]
    if not isinstance(raw_state_db, str):
        raise ConfigurationError("HSC_BRIDGE_STATE_DB must be a string.")

    state_db_str = raw_state_db.strip()
    if not state_db_str:
        raise ConfigurationError("HSC_BRIDGE_STATE_DB cannot be empty.")

    state_db_path = Path(state_db_str)

    # HSC_BRIDGE_SERVERS_FILE
    if "HSC_BRIDGE_SERVERS_FILE" not in env:
        raise ConfigurationError("HSC_BRIDGE_SERVERS_FILE environment variable is required.")

    raw_servers_file = env["HSC_BRIDGE_SERVERS_FILE"]
    if not isinstance(raw_servers_file, str):
        raise ConfigurationError("HSC_BRIDGE_SERVERS_FILE must be a string.")

    servers_file_str = raw_servers_file.strip()
    if not servers_file_str:
        raise ConfigurationError("HSC_BRIDGE_SERVERS_FILE cannot be empty.")

    servers_file_path = Path(servers_file_str)

    servers = parse_server_registry(servers_file_path)

    return BridgeConfig(
        bridge_node_key=bridge_node_key,
        state_db_path=state_db_path,
        servers=servers,
    )
