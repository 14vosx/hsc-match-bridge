"""Local MatchZy filesystem and RCON actuation."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from hsc_match_bridge.matchzy import serialize_matchzy_config
from hsc_match_bridge.protocol import MatchSpecV1

RCON_CLI_TIMEOUT_FLAG = "5s"
RCON_SUBPROCESS_TIMEOUT_SECONDS = 10.0


class MatchZyActuationError(Exception):
    """Raised when local filesystem or RCON actuation fails."""

    def __init__(self, message: str, *, execution_uncertain: bool = False) -> None:
        super().__init__(message)
        self.execution_uncertain = execution_uncertain


def materialize_matchzy_config(csgo_root: Path, match_spec: MatchSpecV1) -> str:
    """Atomically materialize deterministic MatchZy JSON configuration under csgo_root.

    Returns the MatchZy-relative path (e.g. 'hsc-match-bridge/1000000.json').
    """
    if not isinstance(csgo_root, Path):
        raise TypeError(f"Expected Path for csgo_root, got {type(csgo_root).__name__}")
    if not isinstance(match_spec, MatchSpecV1):
        raise TypeError(f"Expected MatchSpecV1 for match_spec, got {type(match_spec).__name__}")

    relative_subpath = f"hsc-match-bridge/{match_spec.runtime_match_id}.json"
    target_dir = csgo_root / "hsc-match-bridge"
    target_file = csgo_root / relative_subpath

    serialized_content = serialize_matchzy_config(match_spec).encode("utf-8")

    # If target already exists:
    if target_file.exists():
        try:
            existing_content = target_file.read_bytes()
        except Exception as e:
            raise MatchZyActuationError(
                f"Failed to read existing config at '{target_file}': {e}",
                execution_uncertain=False,
            ) from e

        if existing_content == serialized_content:
            # Idempotent match
            return relative_subpath

        # Divergent content for same runtimeMatchId: fail closed
        raise MatchZyActuationError(
            f"Config file already exists at '{target_file}' with divergent content for runtimeMatchId {match_spec.runtime_match_id}.",
            execution_uncertain=False,
        )

    # Atomic write to target directory
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise MatchZyActuationError(
            f"Failed to create target directory '{target_dir}': {e}",
            execution_uncertain=False,
        ) from e

    fd, temp_path_str = tempfile.mkstemp(
        dir=target_dir,
        prefix=f".tmp_{match_spec.runtime_match_id}_",
        suffix=".json",
    )
    temp_path = Path(temp_path_str)

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(serialized_content)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replace
        temp_path.replace(target_file)
    except Exception as e:
        # Clean up temp file on failure if still present
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise MatchZyActuationError(
            f"Failed to atomically write config to '{target_file}': {e}",
            execution_uncertain=False,
        ) from e

    return relative_subpath


def execute_rcon_command(
    rcon_executable: Path,
    rcon_config_path: Path,
    command: str,
) -> str:
    """Execute an RCON command via external gorcon/rcon-cli and return stdout."""
    if not isinstance(rcon_executable, Path):
        raise TypeError(f"Expected Path for rcon_executable, got {type(rcon_executable).__name__}")
    if not isinstance(rcon_config_path, Path):
        raise TypeError(f"Expected Path for rcon_config_path, got {type(rcon_config_path).__name__}")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string.")

    cmd_str = command.strip()
    argv = [
        str(rcon_executable),
        "-c",
        str(rcon_config_path),
        "-T",
        RCON_CLI_TIMEOUT_FLAG,
        cmd_str,
    ]

    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=RCON_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise MatchZyActuationError(
            f"RCON execution timed out after {RCON_SUBPROCESS_TIMEOUT_SECONDS}s.",
            execution_uncertain=True,
        ) from e
    except Exception as e:
        raise MatchZyActuationError(
            f"Failed to launch RCON executable: {e}",
            execution_uncertain=False,
        ) from e

    if result.returncode != 0:
        stdout_diag = result.stdout.strip()
        stderr_diag = result.stderr.strip()
        diag = f"stdout: {stdout_diag}" if stdout_diag else ""
        if stderr_diag:
            diag = f"{diag}; stderr: {stderr_diag}" if diag else f"stderr: {stderr_diag}"
        raise MatchZyActuationError(
            f"RCON command exited with non-zero status ({result.returncode}). {diag}".strip(),
            execution_uncertain=True,
        )

    return result.stdout


def load_matchzy_match(
    rcon_executable: Path,
    rcon_config_path: Path,
    relative_config_path: str,
) -> None:
    """Invoke matchzy_loadmatch via external gorcon/rcon-cli executable.

    Note: Successful RCON invocation does NOT verify PREPARED state.
    """
    if not isinstance(relative_config_path, str) or not relative_config_path.strip():
        raise ValueError("relative_config_path must be a non-empty string.")

    execute_rcon_command(
        rcon_executable=rcon_executable,
        rcon_config_path=rcon_config_path,
        command=f"matchzy_loadmatch {relative_config_path.strip()}",
    )

