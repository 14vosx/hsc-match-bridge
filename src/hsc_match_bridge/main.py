"""Command-line entry point for HSC Match Bridge."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from typing import Any, Sequence

from hsc_match_bridge.client import MatchBridgeClient
from hsc_match_bridge.config import ConfigurationError, load_config
from hsc_match_bridge.journal import CommandJournal
from hsc_match_bridge.models import CommandValidationError, JournalError
from hsc_match_bridge.runtime import run_bridge_loop

logger = logging.getLogger("hsc_match_bridge")


def build_parser() -> argparse.ArgumentParser:
    """Build command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="hsc-match-bridge",
        description="HSC Match Bridge control-plane adapter foundation.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # check subcommand
    subparsers.add_parser(
        "check",
        help="Validate environment configuration, server registry, and SQLite journal.",
    )

    # run subcommand
    subparsers.add_parser(
        "run",
        help="Run the persistent Match Bridge daemon in the foreground.",
    )

    return parser


def run_check() -> int:
    """Execute the check subcommand to validate configuration and journal."""
    config = load_config()

    # Check state database parent directory usability
    parent_dir = config.state_db_path.parent
    if not parent_dir.exists() or not parent_dir.is_dir():
        raise ConfigurationError(
            f"State database parent directory does not exist or is not a directory: {parent_dir}"
        )

    # Initialize / verify SQLite journal
    with CommandJournal(config.state_db_path) as journal:
        # Schema verification is performed during journal initialization
        pass

    print(
        f"OK: HSC Match Bridge configuration and journal verified "
        f"(node={config.bridge_node_key}, servers={len(config.servers)})."
    )
    return 0


def run_daemon() -> int:
    """Execute the run subcommand to start the persistent bridge loop."""
    config = load_config()

    parent_dir = config.state_db_path.parent
    if not parent_dir.exists() or not parent_dir.is_dir():
        raise ConfigurationError(
            f"State database parent directory does not exist or is not a directory: {parent_dir}"
        )

    client = MatchBridgeClient(
        base_url=config.auth_api_base_url,
        credential=config.bridge_credential,
    )

    stop_event = threading.Event()

    def _signal_handler(signum: int, _frame: Any) -> None:
        signame = signal.Signals(signum).name
        logger.info("Received signal %s, initiating graceful shutdown...", signame)
        stop_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    with CommandJournal(config.state_db_path) as journal:
        run_bridge_loop(
            config=config,
            client=client,
            journal=journal,
            stop_event=stop_event,
        )

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.subcommand == "check":
            return run_check()
        if args.subcommand == "run":
            return run_daemon()
        parser.print_help(sys.stderr)
        return 1
    except (ConfigurationError, JournalError, CommandValidationError) as e:
        print(f"Configuration/Journal error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
