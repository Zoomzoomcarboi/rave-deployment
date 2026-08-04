from __future__ import annotations

import argparse
import logging
import signal
import time
from collections.abc import Sequence

from .config import RaveConfig, load_config
from .messages import mock_message

logger = logging.getLogger(__name__)


def authorize_development_mock(config: RaveConfig, acknowledged: bool) -> None:
    """Fail closed unless both configuration and invocation explicitly select mock mode."""
    if config.device.mode != "development_mock" or config.inference.backend != "mock":
        raise RuntimeError("no production RAVE runtime is implemented")
    if not acknowledged:
        raise RuntimeError(
            "refusing to start mock scaffolding without explicit --development-mock"
        )


def run_development_mock(config: RaveConfig) -> None:
    logger.warning(
        "DEVELOPMENT MOCK ONLY: camera, inference, tracking, and transport are inactive"
    )
    logger.info("Loaded development configuration for %s", config.device.name)
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    frame_id = 0
    while running:
        message = mock_message(frame_id)
        logger.debug("mock_frame=%s debug_json_bytes=%s", frame_id, len(message.to_json()))
        frame_id += 1
        time.sleep(1)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="RAVE development mock scaffolding")
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--development-mock",
        action="store_true",
        help="acknowledge and enable synthetic development behavior",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        authorize_development_mock(config, args.development_mock)
    except RuntimeError as error:
        parser.error(str(error))
    run_development_mock(config)


if __name__ == "__main__":
    main()
