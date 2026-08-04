# Comma bridge contract

This repository does not modify Openpilot, FrogPilot, or Starpilot. It defines the proposed external contract.

The bridge should:

- bind to the dedicated Pi Ethernet interface only;
- pair through an explicit user action;
- authenticate every datagram or authenticated session;
- verify protocol and model compatibility;
- use monotonic timestamps and strict freshness windows;
- expose RAVE health through the existing messaging/UI architecture;
- default to logging-only mode;
- never translate Pi packets directly into Panda/CAN commands.
