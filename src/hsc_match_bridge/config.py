"""Configuration loading and validation for HSC Match Bridge."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class ConfigurationError(Exception):
    """Raised when configuration or registry fails validation."""


@dataclass(frozen=True)
class ServerResourceConfig:
    """Validated server resource managed by the bridge node."""

    server_key: str
    csgo_root: Path
    rcon_config_path: Path


@dataclass(frozen=True)
class BridgeConfig:
    """Immutable bridge node configuration."""

    bridge_node_key: str
    auth_api_base_url: str
    bridge_credential: str
    state_db_path: Path
    rcon_executable: Path
    servers: tuple[ServerResourceConfig, ...]

    @property
    def server_keys(self) -> tuple[str, ...]:
        return tuple(s.server_key for s in self.servers)

    def __repr__(self) -> str:
        return (
            f"BridgeConfig(bridge_node_key={self.bridge_node_key!r}, "
            f"auth_api_base_url={self.auth_api_base_url!r}, "
            f"bridge_credential='***', "
            f"state_db_path={self.state_db_path!r}, "
            f"rcon_executable={self.rcon_executable!r}, "
            f"servers={self.servers!r})"
        )



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
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 2:
        raise ConfigurationError(
            f"Unsupported server registry schemaVersion: {schema_version}. Expected integer 2."
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

    allowed_server_keys = {"serverKey", "csgoRoot", "rconConfigPath"}

    for idx, entry in enumerate(servers_data):
        if not isinstance(entry, dict):
            raise ConfigurationError(f"Server entry at index {idx} must be a JSON object.")

        unknown_entry_keys = set(entry.keys()) - allowed_server_keys
        if unknown_entry_keys:
            raise ConfigurationError(
                f"Unknown fields in server entry at index {idx}: {sorted(unknown_entry_keys)}"
            )

        # serverKey
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

        # csgoRoot
        if "csgoRoot" not in entry:
            raise ConfigurationError(f"Server entry at index {idx} missing required field 'csgoRoot'.")

        raw_csgo_root = entry["csgoRoot"]
        if not isinstance(raw_csgo_root, str):
            raise ConfigurationError(f"Field 'csgoRoot' at index {idx} must be a string.")

        csgo_root_str = raw_csgo_root.strip()
        if not csgo_root_str:
            raise ConfigurationError(f"Field 'csgoRoot' at index {idx} cannot be empty.")

        csgo_root_path = Path(csgo_root_str)
        if not csgo_root_path.is_absolute():
            raise ConfigurationError(
                f"Field 'csgoRoot' at index {idx} must be an absolute path, got: '{csgo_root_str}'"
            )

        # rconConfigPath
        if "rconConfigPath" not in entry:
            raise ConfigurationError(f"Server entry at index {idx} missing required field 'rconConfigPath'.")

        raw_rcon_config = entry["rconConfigPath"]
        if not isinstance(raw_rcon_config, str):
            raise ConfigurationError(f"Field 'rconConfigPath' at index {idx} must be a string.")

        rcon_config_str = raw_rcon_config.strip()
        if not rcon_config_str:
            raise ConfigurationError(f"Field 'rconConfigPath' at index {idx} cannot be empty.")

        rcon_config_path = Path(rcon_config_str)
        if not rcon_config_path.is_absolute():
            raise ConfigurationError(
                f"Field 'rconConfigPath' at index {idx} must be an absolute path, got: '{rcon_config_str}'"
            )

        seen_keys.add(server_key)
        validated_servers.append(
            ServerResourceConfig(
                server_key=server_key,
                csgo_root=csgo_root_path,
                rcon_config_path=rcon_config_path,
            )
        )

    return tuple(validated_servers)



def validate_auth_api_base_url(raw_url: str) -> str:
    """Validate and normalize Auth API base URL (HTTPS only, no credentials/query/fragment)."""
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ConfigurationError("HSC_AUTH_API_BASE_URL cannot be empty.")

    trimmed = raw_url.strip()
    parsed = urlsplit(trimmed)

    if parsed.scheme.lower() != "https":
        raise ConfigurationError(
            f"HSC_AUTH_API_BASE_URL must use HTTPS scheme, got: '{parsed.scheme}'."
        )

    if not parsed.netloc:
        raise ConfigurationError(
            f"HSC_AUTH_API_BASE_URL missing valid host: '{trimmed}'."
        )

    if "@" in parsed.netloc:
        raise ConfigurationError(
            "HSC_AUTH_API_BASE_URL must not contain embedded username or password."
        )

    if parsed.query:
        raise ConfigurationError(
            "HSC_AUTH_API_BASE_URL must not contain query parameters."
        )

    if parsed.fragment:
        raise ConfigurationError(
            "HSC_AUTH_API_BASE_URL must not contain URL fragments."
        )

    normalized_path = parsed.path.rstrip("/")
    return f"https://{parsed.netloc}{normalized_path}"


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

    # HSC_AUTH_API_BASE_URL
    if "HSC_AUTH_API_BASE_URL" not in env:
        raise ConfigurationError("HSC_AUTH_API_BASE_URL environment variable is required.")
    auth_api_base_url = validate_auth_api_base_url(env["HSC_AUTH_API_BASE_URL"])

    # HSC_BRIDGE_CREDENTIAL
    if "HSC_BRIDGE_CREDENTIAL" not in env:
        raise ConfigurationError("HSC_BRIDGE_CREDENTIAL environment variable is required.")
    raw_cred = env["HSC_BRIDGE_CREDENTIAL"]
    if not isinstance(raw_cred, str) or not raw_cred.strip():
        raise ConfigurationError("HSC_BRIDGE_CREDENTIAL cannot be empty or whitespace only.")
    bridge_credential = raw_cred  # Preserve exactly without trimming

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

    # HSC_RCON_EXECUTABLE
    if "HSC_RCON_EXECUTABLE" not in env:
        raise ConfigurationError("HSC_RCON_EXECUTABLE environment variable is required.")

    raw_rcon_executable = env["HSC_RCON_EXECUTABLE"]
    if not isinstance(raw_rcon_executable, str):
        raise ConfigurationError("HSC_RCON_EXECUTABLE must be a string.")

    rcon_executable_str = raw_rcon_executable.strip()
    if not rcon_executable_str:
        raise ConfigurationError("HSC_RCON_EXECUTABLE cannot be empty.")

    rcon_executable_path = Path(rcon_executable_str)
    if not rcon_executable_path.is_absolute():
        raise ConfigurationError(
            f"HSC_RCON_EXECUTABLE must be an absolute path, got: '{rcon_executable_str}'"
        )

    servers = parse_server_registry(servers_file_path)

    return BridgeConfig(
        bridge_node_key=bridge_node_key,
        auth_api_base_url=auth_api_base_url,
        bridge_credential=bridge_credential,
        state_db_path=state_db_path,
        rcon_executable=rcon_executable_path,
        servers=servers,
    )

