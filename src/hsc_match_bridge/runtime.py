"""Persistent foreground daemon runtime loop for HSC Match Bridge."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from hsc_match_bridge.client import MatchBridgeClient
from hsc_match_bridge.config import BridgeConfig
from hsc_match_bridge.journal import CommandJournal
from hsc_match_bridge.orchestration import PrepareOutcome, prepare_one_cycle

logger = logging.getLogger("hsc_match_bridge")

HEARTBEAT_INTERVAL_SECONDS: float = 15.0
IDLE_POLL_INTERVAL_SECONDS: float = 1.0
BACKOFF_INITIAL_SECONDS: float = 1.0
BACKOFF_MAX_SECONDS: float = 15.0


def run_bridge_loop(
    config: BridgeConfig,
    client: MatchBridgeClient,
    journal: CommandJournal,
    stop_event: threading.Event,
    time_fn: Callable[[], float] = time.monotonic,
) -> None:
    """Execute the persistent single-command bridge polling and heartbeat loop.

    Runs synchronously in the foreground until stop_event is set.
    """
    logger.info(
        "Starting HSC Match Bridge runtime loop (node=%s, servers=%d).",
        config.bridge_node_key,
        len(config.servers),
    )

    current_backoff = BACKOFF_INITIAL_SECONDS
    last_heartbeat_time = -float("inf")

    while not stop_event.is_set():
        now = time_fn()

        # 1. Heartbeat check & dispatch
        if now - last_heartbeat_time >= HEARTBEAT_INTERVAL_SECONDS:
            try:
                client.heartbeat()
                last_heartbeat_time = now
                current_backoff = BACKOFF_INITIAL_SECONDS
            except ConnectionError as e:
                logger.warning(
                    "Central Auth API heartbeat failed (transport unavailable): %s. Backing off for %.1fs.",
                    e,
                    current_backoff,
                )
                stop_event.wait(current_backoff)
                current_backoff = min(current_backoff * 2.0, BACKOFF_MAX_SECONDS)
                continue

        if stop_event.is_set():
            break

        # 2. Command processing / claim cycle
        try:
            result = prepare_one_cycle(config, client, journal)
            current_backoff = BACKOFF_INITIAL_SECONDS
        except ConnectionError as e:
            logger.warning(
                "Central Auth API communication failed during prepare cycle: %s. Backing off for %.1fs.",
                e,
                current_backoff,
            )
            stop_event.wait(current_backoff)
            current_backoff = min(current_backoff * 2.0, BACKOFF_MAX_SECONDS)
            continue

        if result.outcome == PrepareOutcome.NO_WORK:
            stop_event.wait(IDLE_POLL_INTERVAL_SECONDS)
        else:
            logger.info(
                "Processed command (commandId=%s, outcome=%s, resultCode=%s).",
                result.command_id,
                result.outcome.value,
                result.result_code,
            )

    logger.info("HSC Match Bridge runtime loop stopped.")
