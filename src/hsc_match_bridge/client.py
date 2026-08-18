"""HTTPS client for communicating with HSC Central Auth API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from hsc_match_bridge.protocol import (
    ClaimedCommand,
    ProtocolError,
    parse_claimed_command_payload,
)

HTTP_TIMEOUT_SECONDS = 5


class MatchBridgeClient:
    """Outbound HTTPS client for Match Bridge operations."""

    def __init__(
        self,
        base_url: str,
        credential: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credential = credential

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {
            "x-hsc-bridge-key": self._credential,
            "Accept": "application/json",
        }

        body_bytes: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
                raw_data = response.read().decode("utf-8")
                return json.loads(raw_data)
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", errors="replace")
            raise ProtocolError(f"HTTP {e.code} from Central Auth API: {raw_err}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to Central Auth API at '{url}': {e.reason}") from e
        except Exception as e:
            raise ProtocolError(f"Unexpected communication error with Central Auth API: {e}") from e

    def heartbeat(self) -> bool:
        """Send a liveness heartbeat to Central Auth API."""
        data = self._post("/internal/match-bridge/heartbeat")
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ProtocolError(f"Invalid heartbeat response from Central: {data}")
        return True

    def claim(self) -> ClaimedCommand | None:
        """Claim next pending/expired-lease command from Central Auth API."""
        data = self._post("/internal/match-bridge/commands/claim")
        return parse_claimed_command_payload(data)

    def submit_result(
        self,
        command_id: str,
        lease_token: str,
        outcome: str,
        result_code: str,
        result: dict[str, Any] | None = None,
    ) -> bool:
        """Submit terminal execution result for a claimed command."""
        payload = {
            "leaseToken": lease_token,
            "outcome": outcome,
            "resultCode": result_code,
            "result": result,
        }
        data = self._post(f"/internal/match-bridge/commands/{command_id}/result", payload=payload)
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ProtocolError(f"Invalid result submission response from Central: {data}")
        return True
