# Proposed Comma bridge contract

RAVE currently has no Comma receiver. This document is a future contract and does not
modify or integrate with Openpilot, FrogPilot, Starpilot, Panda, or vehicle CAN.
Transport, pairing, authentication, replay protection, and bridge implementation are
not present.

A future receiver must:

- bind only to a dedicated RAVE interface and use an explicitly selected transport;
- pair through an explicit user action and authenticate each message or session;
- provide replay protection, including authenticated sequence windows;
- validate protocol, model, data ranges, and boot/session identity;
- record receiver-local monotonic arrival time for each message;
- determine heartbeat timeouts and freshness from elapsed receiver time since arrival;
- never compare Pi monotonic timestamps with the receiver's monotonic clock;
- treat a new boot/session identifier as a state reset only after authentication;
- expose unavailable/invalid status through the receiver's existing messaging system;
- default to logging-only behavior during future validation.

The Pi must have no Panda or CAN interfaces, dependencies, credentials, permissions,
or code. The receiver must never translate Pi metadata directly into Panda/CAN or
vehicle-control commands.

Sender timestamps may describe ordering or sender-side processing latency within one
authenticated boot/session. They are not evidence of cross-device freshness.
