# Comma bridge contract

## Current boundary

Gate 2A/2B established Comma-side dedicated-Ethernet management and native
StarPilot/Aether RAVE UI groundwork. That work is **not** the production RAVE
perception-metadata receiver. Production transport, pairing, authentication, replay
protection, freshness enforcement, and metadata consumption remain future work.

The Pi must have no Panda or CAN interfaces, dependencies, credentials, permissions,
or code. The receiver must never translate Pi metadata directly into Panda/CAN or
vehicle-control commands. RAVE must determine its own perception state without
depending on the Comma.

## Dedicated network-management contract

The current StarPilot integration manages only the dedicated RAVE Ethernet adapter.
It must:

- discover exactly one eligible USB Ethernet adapter;
- support the ASIX `ax88179_178a` and Realtek `r8152` software families;
- never hardcode `eth0`, a MAC address, or a NetworkManager profile UUID;
- configure `10.77.0.2/24` with no gateway/DNS, `never-default=yes`, IPv6 disabled,
  and autoconnect enabled;
- leave Wi-Fi/LTE, default routes, DNS, and unrelated Ethernet profiles unchanged;
- fail unavailable on missing or ambiguous eligible adapters;
- persist backend-owned profile identity in `RaveNetworkProfileUuid`;
- expose bounded backend status in `RaveNetworkStatus`;
- keep network ownership out of the UI.

Bounded status states are `disabled`, `adapterMissing`, `adapterAmbiguous`,
`configuring`, `connected`, `profileConflict`, and `networkError`.

## UI contract

The validated Gate 2B UI architecture is native StarPilot/Aether Raylib and
Params/state driven. The UI must not own networking, call D-Bus or `nmcli`, create a
networking thread, add sleeps/blocking work to render/update loops, or retain stale
`Connected` state after the backend changes. Unsafe on-road configuration actions
must not be introduced.

## Future metadata receiver requirements

A future receiver must:

- bind only to the dedicated RAVE interface and an explicitly selected transport;
- pair through an explicit user action and authenticate each message or session;
- provide replay protection, including authenticated sequence windows;
- validate protocol, model, data ranges, and boot/session identity;
- record receiver-local monotonic arrival time for each message;
- determine heartbeat timeouts and freshness from elapsed receiver time since arrival;
- never compare Pi monotonic timestamps with the receiver's monotonic clock;
- treat a new boot/session identifier as a state reset only after authentication;
- expose unavailable/invalid status through the receiver's existing messaging system;
- default to logging-only behavior during validation.

Sender timestamps may describe ordering or sender-side processing latency within one
authenticated boot/session. They are not evidence of cross-device freshness.
