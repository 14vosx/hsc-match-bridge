"""Tests protecting critical observable configuration and registry contracts."""

import json
import tempfile
import unittest
from pathlib import Path

from hsc_match_bridge.config import ConfigurationError, load_config, parse_server_registry


class TestConfigContracts(unittest.TestCase):
    """Observable contracts for environment configuration and server registry."""

    def test_valid_configuration_loads_and_normalizes_keys(self) -> None:
        """A valid configuration loads trimmed, normalized keys and masks credential in repr."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_file = Path(tmp_dir) / "servers.json"
            registry_file.write_text(
                json.dumps({
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "  server-alpha  ",
                            "csgoRoot": "/opt/cs2-server1/game/csgo",
                            "rconConfigPath": "/etc/rcon/server1.yaml",
                        },
                        {
                            "serverKey": "server-bravo",
                            "csgoRoot": "/opt/cs2-server2/game/csgo",
                            "rconConfigPath": "/etc/rcon/server2.yaml",
                        },
                    ],
                }),
                encoding="utf-8",
            )
            state_db = Path(tmp_dir) / "state.db"
            rcon_bin = Path("/usr/local/bin/rcon")

            env = {
                "HSC_BRIDGE_NODE_KEY": "  node-01  ",
                "HSC_AUTH_API_BASE_URL": "https://auth.example.com/api/",
                "HSC_BRIDGE_CREDENTIAL": "secret_bridge_token_123",
                "HSC_BRIDGE_STATE_DB": str(state_db),
                "HSC_BRIDGE_SERVERS_FILE": str(registry_file),
                "HSC_RCON_EXECUTABLE": str(rcon_bin),
            }

            config = load_config(env)

            self.assertEqual(config.bridge_node_key, "node-01")
            self.assertEqual(config.auth_api_base_url, "https://auth.example.com/api")
            self.assertEqual(config.bridge_credential, "secret_bridge_token_123")
            self.assertEqual(config.state_db_path, state_db)
            self.assertEqual(config.rcon_executable, rcon_bin)
            self.assertEqual(config.server_keys, ("server-alpha", "server-bravo"))
            self.assertEqual(config.servers[0].csgo_root, Path("/opt/cs2-server1/game/csgo"))
            self.assertEqual(config.servers[0].rcon_config_path, Path("/etc/rcon/server1.yaml"))
            # Ensure credential is never exposed in repr
            self.assertNotIn("secret_bridge_token_123", repr(config))
            self.assertIn("***", repr(config))

    def test_invalid_bridge_node_key_fails(self) -> None:
        """Missing, blank, or excessively long bridgeNodeKey raises ConfigurationError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            valid_registry = Path(tmp_dir) / "servers.json"
            valid_registry.write_text(
                json.dumps({
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                }),
                encoding="utf-8",
            )
            base_env = {
                "HSC_AUTH_API_BASE_URL": "https://auth.example.com",
                "HSC_BRIDGE_CREDENTIAL": "secret_key",
                "HSC_BRIDGE_STATE_DB": str(Path(tmp_dir) / "state.db"),
                "HSC_BRIDGE_SERVERS_FILE": str(valid_registry),
                "HSC_RCON_EXECUTABLE": "/usr/local/bin/rcon",
            }

            # Missing
            with self.assertRaises(ConfigurationError):
                load_config(base_env)

            # Blank / whitespace only
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_BRIDGE_NODE_KEY": "   "})

            # Exceeding 64 characters
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_BRIDGE_NODE_KEY": "x" * 65})

    def test_invalid_rcon_executable_fails(self) -> None:
        """Missing, blank, or relative HSC_RCON_EXECUTABLE raises ConfigurationError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            valid_registry = Path(tmp_dir) / "servers.json"
            valid_registry.write_text(
                json.dumps({
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                }),
                encoding="utf-8",
            )
            base_env = {
                "HSC_BRIDGE_NODE_KEY": "node-01",
                "HSC_AUTH_API_BASE_URL": "https://auth.example.com",
                "HSC_BRIDGE_CREDENTIAL": "secret_key",
                "HSC_BRIDGE_STATE_DB": str(Path(tmp_dir) / "state.db"),
                "HSC_BRIDGE_SERVERS_FILE": str(valid_registry),
            }

            # Missing
            with self.assertRaises(ConfigurationError):
                load_config(base_env)

            # Blank / whitespace only
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_RCON_EXECUTABLE": "   "})

            # Relative path
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_RCON_EXECUTABLE": "bin/rcon-cli"})

    def test_invalid_auth_api_url_and_credential_fails(self) -> None:
        """Rejects non-HTTPS schemes, embedded credentials, query strings, fragments, and blank credentials."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            valid_registry = Path(tmp_dir) / "servers.json"
            valid_registry.write_text(
                json.dumps({
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                }),
                encoding="utf-8",
            )
            base_env = {
                "HSC_BRIDGE_NODE_KEY": "node-01",
                "HSC_BRIDGE_STATE_DB": str(Path(tmp_dir) / "state.db"),
                "HSC_BRIDGE_SERVERS_FILE": str(valid_registry),
                "HSC_AUTH_API_BASE_URL": "https://auth.example.com",
                "HSC_BRIDGE_CREDENTIAL": "secret_token",
                "HSC_RCON_EXECUTABLE": "/usr/local/bin/rcon",
            }

            # Non-HTTPS URL
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_AUTH_API_BASE_URL": "http://auth.example.com"})

            # Embedded username/password
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_AUTH_API_BASE_URL": "https://user:pass@auth.example.com"})

            # Query params
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_AUTH_API_BASE_URL": "https://auth.example.com?query=1"})

            # Fragment
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_AUTH_API_BASE_URL": "https://auth.example.com#section"})

            # Blank credential
            with self.assertRaises(ConfigurationError):
                load_config({**base_env, "HSC_BRIDGE_CREDENTIAL": "   "})

    def test_server_registry_strict_schema_v2_validation(self) -> None:
        """Registry rejects schemaVersion 1, duplicate keys, blank keys, relative paths, missing fields, and unknown fields."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            reg_path = Path(tmp_dir) / "registry.json"

            invalid_payloads = [
                # Unsupported schemaVersion 1 (bumped to 2)
                {
                    "schemaVersion": 1,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                },
                # Missing servers / empty servers
                {"schemaVersion": 2, "servers": []},
                # Duplicate serverKey after normalization
                {
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2-a/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        },
                        {
                            "serverKey": "  srv-1  ",
                            "csgoRoot": "/opt/cs2-b/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv2.yaml",
                        },
                    ],
                },
                # Blank / too long serverKey
                {
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "   ",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                },
                {
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "k" * 65,
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                },
                # Missing csgoRoot or rconConfigPath
                {
                    "schemaVersion": 2,
                    "servers": [
                        {"serverKey": "srv-1", "rconConfigPath": "/etc/rcon/srv1.yaml"}
                    ],
                },
                {
                    "schemaVersion": 2,
                    "servers": [
                        {"serverKey": "srv-1", "csgoRoot": "/opt/cs2/game/csgo"}
                    ],
                },
                # Relative csgoRoot / relative rconConfigPath
                {
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "relative/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                },
                {
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "relative/rcon.yaml",
                        }
                    ],
                },
                # Unknown root field
                {
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                        }
                    ],
                    "extraField": True,
                },
                # Unknown server entry field
                {
                    "schemaVersion": 2,
                    "servers": [
                        {
                            "serverKey": "srv-1",
                            "csgoRoot": "/opt/cs2/game/csgo",
                            "rconConfigPath": "/etc/rcon/srv1.yaml",
                            "port": 27015,
                        }
                    ],
                },
            ]

            for payload in invalid_payloads:
                reg_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ConfigurationError, msg=f"Failed to reject: {payload}"):
                    parse_server_registry(reg_path)


if __name__ == "__main__":
    unittest.main()
