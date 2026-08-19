# HSC Match Bridge — Deployment Runbook (Hostinger VPS)

This runbook defines the operational procedure for deploying and running **HSC Match Bridge** on the Hostinger VPS host (`srv1353392`, Debian GNU/Linux 13 trixie x86_64).

---

## A. Prerequisites & Environment Decisions

- **Host**: `srv1353392` (Debian 13 trixie, x86_64).
- **Python**: System Python 3.13.5 (`/usr/bin/python3`) with standard `venv` module.
- **Process Identity**:
  - `User=amp`
  - `Group=amp`
  - *Rationale*: AMP instance directories (`/home/amp`) and instance roots are mode `0700 amp:amp`. The Bridge runs as `amp:amp` to access and write CS2/MatchZy match configurations directly.
- **Logical Identifiers**:
  - `bridgeNodeKey`: `hsc-cs2-hostinger-01`
  - Initial `serverKey`: `hsc-mix-01` (CS2 instance `MixHAXIXE01`).

---

## B. Production Filesystem Layout & Permissions Policy

| Path | Owner:Group | Mode | Purpose |
|---|---|---|---|
| `/opt/hsc-match-bridge` | `root:root` | `0755` | Repository clone & runtime directory |
| `/opt/hsc-match-bridge/.venv` | `root:root` | `0755` | Isolated Python 3.13 virtual environment |
| `/usr/local/bin/hsc-match-bridge` | `root:root` | `0755` | Symlink to `/opt/hsc-match-bridge/.venv/bin/hsc-match-bridge` |
| `/usr/local/bin/rcon` | `root:root` | `0755` | Validated `gorcon/rcon-cli` binary (v0.10.3) |
| `/etc/hsc-match-bridge` | `root:amp` | `0750` | Bridge configuration root directory |
| `/etc/hsc-match-bridge/bridge.env` | `root:amp` | `0640` | Production environment variables & bridge credential |
| `/etc/hsc-match-bridge/servers.json` | `root:amp` | `0640` | Managed server resource registry |
| `/etc/hsc-match-bridge/rcon` | `root:amp` | `0750` | Dedicated RCON configuration directory |
| `/etc/hsc-match-bridge/rcon/mix01.yaml` | `root:amp` | `0640` | CS2 RCON connection parameters & password |
| `/var/lib/hsc-match-bridge` | `amp:amp` | `0750` | SQLite durable state database directory |
| `/var/lib/hsc-match-bridge/bridge.sqlite3` | `amp:amp` | `0600` | SQLite journal database file |
| `/etc/systemd/system/hsc-match-bridge.service` | `root:root` | `0644` | Systemd service unit |
| `<csgoRoot>/hsc-match-bridge` | `amp:amp` | `0750` | MatchZy match JSON output directory |

---

## C. Code Deployment

Clone or update the repository at `/opt/hsc-match-bridge` to the approved release commit or tag:

```bash
# As root:
sudo mkdir -p /opt/hsc-match-bridge
sudo chown root:root /opt/hsc-match-bridge

# Clone or checkout the specifically approved commit/tag
cd /opt/hsc-match-bridge
sudo git clone https://github.com/14vosx/hsc-match-bridge.git .
sudo git checkout <APPROVED_COMMIT_OR_TAG>

# Verify worktree cleanliness and HEAD SHA
sudo git status
sudo git rev-parse HEAD
```

---

## D. Python Virtual Environment Setup

Create an isolated virtual environment and install the Bridge package in editable/wheel mode:

```bash
# As root:
sudo python3 -m venv /opt/hsc-match-bridge/.venv
sudo /opt/hsc-match-bridge/.venv/bin/pip install -e /opt/hsc-match-bridge

# Link executable into standard path
sudo ln -sf /opt/hsc-match-bridge/.venv/bin/hsc-match-bridge /usr/local/bin/hsc-match-bridge

# Verify executable resolution
which hsc-match-bridge
/usr/local/bin/hsc-match-bridge --help
```

---

## E. External RCON Binary Verification & Installation

The Match Bridge invokes the external `gorcon/rcon-cli` binary.

- **Required Version**: `rcon 0.10.3` (x86_64 Linux).
- **Frozen Expected SHA256**: `cc4efcccde182119805a1242bcf978350974573f04c1c8b20369f5a7268fc176`
- **Candidate Artifact Path**: `/tmp/hsc-g2-runtime/rcon`

```bash
# 1. Verify that candidate binary exists and is executable
test -x /tmp/hsc-g2-runtime/rcon

# 2. Validate exact frozen SHA256 checksum
echo "cc4efcccde182119805a1242bcf978350974573f04c1c8b20369f5a7268fc176  /tmp/hsc-g2-runtime/rcon" | sha256sum -c -

# 3. Install binary to target path
sudo cp /tmp/hsc-g2-runtime/rcon /usr/local/bin/rcon
sudo chown root:root /usr/local/bin/rcon
sudo chmod 0755 /usr/local/bin/rcon

# 4. Verify version after installation
/usr/local/bin/rcon --version
```

> **Operational Note**: If `/tmp/hsc-g2-runtime/rcon` is missing or was removed by system cleanup, the binary must be obtained operationally again. Installation must proceed **only** when the candidate binary matches the frozen SHA256 checksum above.

---

## F. Directory Creation & Permissions

```bash
# Configuration directories
sudo mkdir -p /etc/hsc-match-bridge/rcon
sudo chown -R root:amp /etc/hsc-match-bridge
sudo chmod 0750 /etc/hsc-match-bridge /etc/hsc-match-bridge/rcon

# State database directory
sudo mkdir -p /var/lib/hsc-match-bridge
sudo chown -R amp:amp /var/lib/hsc-match-bridge
sudo chmod 0750 /var/lib/hsc-match-bridge
```

---

## G. Install Server Registry

Copy the versioned production registry to `/etc/hsc-match-bridge/servers.json`:

```bash
sudo cp /opt/hsc-match-bridge/deploy/hostinger/servers.json /etc/hsc-match-bridge/servers.json
sudo chown root:amp /etc/hsc-match-bridge/servers.json
sudo chmod 0640 /etc/hsc-match-bridge/servers.json
```

---

## H. Materialize Environment File (`bridge.env`)

Copy the template and populate `HSC_BRIDGE_CREDENTIAL` with the secret raw value:

```bash
sudo cp /opt/hsc-match-bridge/deploy/hostinger/bridge.env.example /etc/hsc-match-bridge/bridge.env
sudo chown root:amp /etc/hsc-match-bridge/bridge.env
sudo chmod 0640 /etc/hsc-match-bridge/bridge.env

# Edit /etc/hsc-match-bridge/bridge.env securely to set HSC_BRIDGE_CREDENTIAL=<RAW_SECRET>
```

> **Security Note**: Never commit, log, or display `HSC_BRIDGE_CREDENTIAL`. Central stores only the SHA-256 digest of this credential.

---

## I. Materialize RCON Configuration

Install the operational RCON YAML configuration for `mix01` without displaying secrets:

```bash
# 1. Verify existence of candidate RCON config
test -f /tmp/hsc-g2-runtime/mix01-rcon.yaml

# 2. Securely copy to target path with proper ownership and mode
sudo install \
  -o root \
  -g amp \
  -m 0640 \
  /tmp/hsc-g2-runtime/mix01-rcon.yaml \
  /etc/hsc-match-bridge/rcon/mix01.yaml
```

> **Security Note**: Never `cat`, echo, or paste the content of `/etc/hsc-match-bridge/rcon/mix01.yaml` in terminal, chat, or logs. If `/tmp/hsc-g2-runtime/mix01-rcon.yaml` is not present, recreate/materialize `/etc/hsc-match-bridge/rcon/mix01.yaml` manually from the known operational configuration with owner `root:amp` and mode `0640`.

---

## J. Create MatchZy Output Directory

Ensure the target MatchZy JSON output directory exists under the CS2 root for `MixHAXIXE01`:

```bash
sudo -u amp mkdir -p /home/amp/.ampdata/instances/MixHAXIXE01/counter-strike2/730/game/csgo/hsc-match-bridge
sudo chmod 0750 /home/amp/.ampdata/instances/MixHAXIXE01/counter-strike2/730/game/csgo/hsc-match-bridge
```

---

## K. Install Systemd Service Unit

```bash
sudo cp /opt/hsc-match-bridge/deploy/hostinger/hsc-match-bridge.service /etc/systemd/system/hsc-match-bridge.service
sudo chown root:root /etc/systemd/system/hsc-match-bridge.service
sudo chmod 0644 /etc/systemd/system/hsc-match-bridge.service
sudo systemctl daemon-reload
```

---

## L. Local Pre-Start Gate (SAFE BEFORE CENTRAL PROVISIONING)

The `check` subcommand performs strictly local validation of configuration, server registry paths, and SQLite journal initialization. **It makes no network requests**:
- Does not instantiate `MatchBridgeClient`
- Does not send heartbeats
- Does not claim commands
- Does not connect to Central Auth API

Run the verification as a transient systemd execution under `amp:amp` using native `EnvironmentFile` parsing (without exposing credentials via argv or shell expansion):

```bash
sudo systemd-run \
  --wait \
  --pipe \
  --quiet \
  --collect \
  --property=User=amp \
  --property=Group=amp \
  --property=EnvironmentFile=/etc/hsc-match-bridge/bridge.env \
  /usr/local/bin/hsc-match-bridge check
```

Expected output:
```text
OK: HSC Match Bridge configuration and journal verified (node=hsc-cs2-hostinger-01, servers=1).
```

---

## M. Central Provisioning Dependency (CRITICAL BOUNDARY)

> **DO NOT START OR ENABLE THE DAEMON (`run`) BEFORE CENTRAL PROVISIONING IS COMPLETE.**

Before starting the daemon, the following must be provisioned in the Central Match Domain (via G3-C):
1. **Bridge Node Registry**: `match_bridge_nodes` entry for `hsc-cs2-hostinger-01` with the SHA-256 digest of `HSC_BRIDGE_CREDENTIAL`.
2. **Server Resource Registry**: `match_server_resources` entry for `serverKey = "hsc-mix-01"` associated with node `hsc-cs2-hostinger-01`.

---

## N. Start & Enable Daemon (ONLY AFTER CENTRAL PROVISIONING)

Once Central provisioning is confirmed:

```bash
sudo systemctl enable hsc-match-bridge.service
sudo systemctl start hsc-match-bridge.service
```

---

## O. Operational Verification

### Service Status
```bash
sudo systemctl status hsc-match-bridge.service
```

### Stream Journald Logs
```bash
sudo journalctl -u hsc-match-bridge.service -f
```

Look for:
- Startup confirmation: `Starting HSC Match Bridge runtime loop (node=hsc-cs2-hostinger-01, servers=1).`
- Absence of `WARNING` transport backoff logs.

### Central Heartbeat Verification
Check Central Auth API monitoring / database to verify that `hsc-cs2-hostinger-01` last heartbeat timestamp is updating every ~15 seconds.

---

## P. Operational Rollback Procedure

If the service needs to be rolled back or stopped:

```bash
# 1. Stop and disable service
sudo systemctl stop hsc-match-bridge.service
sudo systemctl disable hsc-match-bridge.service

# 2. Check remaining status
sudo systemctl status hsc-match-bridge.service

# 3. If rollback of code is needed:
cd /opt/hsc-match-bridge
sudo git checkout <PREVIOUS_STABLE_COMMIT>
sudo /opt/hsc-match-bridge/.venv/bin/pip install -e /opt/hsc-match-bridge
```
