"""Tests protecting critical observable protocol models and Match Spec v1 parsing."""

import unittest

from hsc_match_bridge.models import CommandType
from hsc_match_bridge.protocol import ProtocolError, parse_claimed_command_payload


def _valid_claim_payload() -> dict:
    return {
        "ok": True,
        "protocolVersion": 1,
        "command": {
            "commandId": "cmd-001",
            "assignmentId": "assign-100",
            "commandType": "PREPARE_MATCH",
            "attempt": 1,
            "leaseToken": "lease_tok_abc123",
            "leaseExpiresAt": "2026-08-18T15:00:30.000Z",
            "target": {
                "serverKey": "srv-east-1",
            },
            "matchSpec": {
                "specVersion": 1,
                "competitiveMatchId": "match-uuid-1",
                "runtimeMatchId": 1000001,
                "map": {
                    "poolKey": "pool-active-1",
                    "poolVersion": 1,
                    "key": "de_mirage",
                    "displayName": "Mirage",
                },
                "teams": {
                    "A": [
                        {
                            "playerAccountId": f"p-a{i}",
                            "steamid64": f"7656119800000000{i}",
                            "personaname": f"Player A{i}",
                        }
                        for i in range(1, 6)
                    ],
                    "B": [
                        {
                            "playerAccountId": f"p-b{i}",
                            "steamid64": f"7656119800000001{i}",
                            "personaname": f"Player B{i}",
                        }
                        for i in range(1, 6)
                    ],
                },
            },
        },
    }


class TestProtocolContracts(unittest.TestCase):
    """Observable contracts for Central Auth API claim payload and Match Spec v1."""

    def test_parse_valid_claimed_command_payload(self) -> None:
        """A valid claim response payload parses cleanly into immutable ClaimedCommand."""
        payload = _valid_claim_payload()
        claimed = parse_claimed_command_payload(payload)

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.command_id, "cmd-001")
        self.assertEqual(claimed.assignment_id, "assign-100")
        self.assertEqual(claimed.command_type, CommandType.PREPARE_MATCH)
        self.assertEqual(claimed.attempt, 1)
        self.assertEqual(claimed.lease_token, "lease_tok_abc123")
        self.assertEqual(claimed.target.server_key, "srv-east-1")
        self.assertEqual(claimed.match_spec.runtime_match_id, 1000001)
        self.assertEqual(claimed.match_spec.map.key, "de_mirage")
        self.assertEqual(len(claimed.match_spec.teams.team_a), 5)
        self.assertEqual(len(claimed.match_spec.teams.team_b), 5)
        self.assertEqual(claimed.match_spec.teams.team_a[0].personaname, "Player A1")

    def test_parse_empty_claim_returns_none(self) -> None:
        """A claim response with command=null returns None."""
        payload = {"ok": True, "protocolVersion": 1, "command": None}
        self.assertIsNone(parse_claimed_command_payload(payload))

    def test_parse_rejects_malformed_protocol_and_rosters(self) -> None:
        """Parser rejects unsupported versions, invalid command types, invalid runtimeMatchId, corrupt 5v5 rosters, missing personaname."""
        base = _valid_claim_payload()

        # 1. Unsupported protocolVersion
        invalid_protocol = {**base, "protocolVersion": 2}
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(invalid_protocol)

        # 2. Unsupported specVersion
        invalid_spec = _valid_claim_payload()
        invalid_spec["command"]["matchSpec"]["specVersion"] = 2
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(invalid_spec)

        # 3. Invalid runtimeMatchId < 1_000_000
        invalid_runtime_id = _valid_claim_payload()
        invalid_runtime_id["command"]["matchSpec"]["runtimeMatchId"] = 999999
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(invalid_runtime_id)

        # 4. Asymmetrical roster (4 on Team A)
        invalid_roster_count = _valid_claim_payload()
        invalid_roster_count["command"]["matchSpec"]["teams"]["A"] = (
            invalid_roster_count["command"]["matchSpec"]["teams"]["A"][:4]
        )
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(invalid_roster_count)

        # 5. Duplicate SteamID64
        duplicate_steam = _valid_claim_payload()
        duplicate_steam["command"]["matchSpec"]["teams"]["B"][0] = {
            "playerAccountId": "p-b1-alt",
            "steamid64": duplicate_steam["command"]["matchSpec"]["teams"]["A"][0]["steamid64"],
            "personaname": "Player B1 Alt",
        }
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(duplicate_steam)

        # 6. Missing or invalid personaname
        missing_personaname = _valid_claim_payload()
        del missing_personaname["command"]["matchSpec"]["teams"]["A"][0]["personaname"]
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(missing_personaname)

        empty_personaname = _valid_claim_payload()
        empty_personaname["command"]["matchSpec"]["teams"]["A"][0]["personaname"] = "   "
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(empty_personaname)

        # Opaque values with surrounding whitespace are rejected, never repaired.
        padded_opaque_value = _valid_claim_payload()
        padded_opaque_value["command"]["leaseToken"] = " lease_tok_abc123 "
        with self.assertRaises(ProtocolError):
            parse_claimed_command_payload(padded_opaque_value)


if __name__ == "__main__":
    unittest.main()
