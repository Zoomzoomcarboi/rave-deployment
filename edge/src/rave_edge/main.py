from __future__ import annotations

import argparse
import logging
import signal
import time

from .config import load_config
from .messages import mock_message


def main() -> None:
    parser = argparse.ArgumentParser(description="RAVE edge mock runtime")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    logging.warning("MOCK MODE: no camera, Hailo inference, tracking, or Comma transport is active")
    logging.info("Loaded configuration for %s", cfg.device.get("name"))
    frame_id = 0
    while running:
        message = mock_message(frame_id)
        logging.debug("frame=%s bytes=%s", frame_id, len(message.to_json()))
        frame_id += 1
        time.sleep(1)


if __name__ == "__main__":
    main()
