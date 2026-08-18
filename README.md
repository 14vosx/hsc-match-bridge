# HSC Match Bridge

The **HSC Match Bridge** is a standalone bounded context and runtime acting as a control-plane adapter between the **HSC Central Match Domain** and local **CS2 / MatchZy** dedicated server instances.

---

## Architecture & Responsibilities

### Role & Process Topology
- **Process Topology**: Exactly **one Match Bridge process per `bridgeNodeKey`**.
- **Multi-Server Management**: A single `bridgeNodeKey` node/process manages one or more `serverKey` resources located on the local host.
- **Identity Boundaries**:
  - `bridgeNodeKey`: Identifies the local Bridge node / process boundary.
  - `serverKey`: Identifies a Central Match Domain `ServerResource`. It is *not* a CS2 port, IP, join address, AMP instance name, or Match Edge source key.

### Bounded Context Boundaries
- **No direct MariaDB access**: The Match Bridge does not connect to the Central database.
- **No RabbitMQ**: The Match Bridge does not participate in AMQP message broker topologies.
- **No Match Edge dependency**: The Match Bridge is fully independent of Match Edge services.
- **Outbound HTTPS only**: All Central communication occurs via outbound HTTPS initiated by the Bridge to Central Auth API.
- **No public inbound API**: The Bridge does not expose public HTTP listener endpoints.

---

## Slice G1 Scope: Central Bridge Protocol

Slice G1 establishes the reliable protocol foundation:
- Outbound HTTPS communication using Python's standard library (`urllib.request`) with finite timeout (`HTTP_TIMEOUT_SECONDS = 5`) and default TLS verification.
- Dedicated Bridge credential authentication via `x-hsc-bridge-key` header (the Bridge does not send `bridgeNodeKey` as an authority selector; Central derives it from credential digest).
- Strict protocol models for Central Match Spec v1 (authoritative 5v5 rosters, unique SteamID64s, frozen map snapshot).
- Local server registry ownership validation before journal observation.
- Intake orchestration (`intake_one_cycle`): claims command, validates protocol and local server ownership, and durably records state in SQLite journal as `RECEIVED`.
- **G1 Boundary**: Does *not* execute local preparation, invoke MatchZy, create server side-effects, or mark state `APPLYING`.

---

## Slice G2-A Scope: MatchZy Config Renderer

Slice G2-A provides pure, deterministic Match Spec v1 → MatchZy JSON translation:
- Pure translation from `MatchSpecV1` to MatchZy-compatible configuration dictionary and deterministic JSON.
- Maps `runtimeMatchId` to `matchid`, `teams.team_a` to `team1`, `teams.team_b` to `team2`, and `map.key` to single `maplist` entry.
- Standardizes 5v5 BO1 format with knife round (`map_sides: ["knife"]`), `skip_veto: true`, and `min_players_to_ready: 5`.
- **G2-A Boundary**: Pure renderer only. Does *not* write MatchZy files, execute RCON commands, or prepare a live server.

---

## Reliability & Execution Uncertainty Principle

### Exactly-Once Limitation
SQLite alone **cannot provide magical exactly-once local actuation**.

There is an unavoidable crash window between executing a local side effect (e.g. configuring CS2/MatchZy in G2) and recording the outcome durably in SQLite. Therefore, execution uncertainty is modeled explicitly:

1. `RECEIVED`: Command is durably observed; no local execution has started.
2. `APPLYING`: Execution was durably marked as started *prior* to executing local side effects.
3. `SUCCEEDED`: Terminal local outcome recorded successfully.
4. `FAILED`: Terminal local outcome recorded with failure.

### Crash Semantics for `APPLYING`
If the Bridge process crashes while a command is in the `APPLYING` state, that command represents an **uncertain execution**.

Upon restart:
- The command **remains in `APPLYING` state**.
- It is **never automatically reset** to `RECEIVED`.
- It is **never automatically retried**.
- It is **never implicitly converted** to `FAILED`.

Future G2 reconciliation/adapter logic will decide how an uncertain execution is safely reconciled.

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `HSC_BRIDGE_NODE_KEY` | Yes | Unique identifier for this bridge node instance (string, trimmed, max 64 chars). |
| `HSC_AUTH_API_BASE_URL` | Yes | Absolute HTTPS base URL of Central Auth API (e.g. `https://auth.example.com`). |
| `HSC_BRIDGE_CREDENTIAL` | Yes | Dedicated internal bridge credential secret (sent in `x-hsc-bridge-key`). |
| `HSC_BRIDGE_STATE_DB` | Yes | Filesystem path to the local SQLite database file (e.g. `state/journal.db`). |
| `HSC_BRIDGE_SERVERS_FILE` | Yes | Filesystem path to the local server registry JSON file. |

*(Note: MatchZy/RCON/AMP configurations belong to future Slice G2.)*

### Local Server Registry Schema (`schemaVersion: 1`)

The server registry defines the local server resources managed by this bridge node:

```json
{
  "schemaVersion": 1,
  "servers": [
    {
      "serverKey": "central-server-resource-01"
    },
    {
      "serverKey": "central-server-resource-02"
    }
  ]
}
```

*Strict validation rules*:
- Root must contain integer `schemaVersion: 1` and non-empty `servers` list.
- Each server entry must contain strictly `serverKey` (string, max 64 chars, non-empty after trimming).
- Duplicate normalized `serverKey` entries and unknown fields are rejected.

---

## Local Validation (CLI Check)

To validate local configuration, server registry, and SQLite journal initialization (without making network requests):

```bash
# Set environment variables (example paths)
export HSC_BRIDGE_NODE_KEY="node-local-dev-01"
export HSC_AUTH_API_BASE_URL="https://auth.example.com"
export HSC_BRIDGE_CREDENTIAL="placeholder-secret-credential"
export HSC_BRIDGE_STATE_DB="./state/journal.db"
export HSC_BRIDGE_SERVERS_FILE="./config/servers.json"

# Run check command
hsc-match-bridge check
# or
python3 -m hsc_match_bridge check
```

Output upon success:
```text
OK: HSC Match Bridge configuration and journal verified (node=node-local-dev-01, servers=2).
```

---

## Future Deployment Example (Informational)

In future production deployments (systemd unit to be defined in later slices), the database and configuration paths may follow standard conventions such as:
- State database: `/var/lib/hsc-match-bridge/journal.db` *(future example)*
- Server registry: `/etc/hsc-match-bridge/servers.json` *(future example)*
