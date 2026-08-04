# Proposed deployment workflow

There is no customer deployment today: no hardware profile or camera is approved, no
release image is built, and no Comma receiver or pairing flow exists.

A future deployment may provide a signed image, guided setup, candidate-hardware
validation, and a separately reviewed receiver. Those are plans, not instructions
that can currently be followed.

## Development path

Developers can validate configuration and run the explicitly gated mock as described
in the repository README. `scripts/install.sh`, Debian packaging, systemd services,
and image files are scaffolding and do not install a working perception service.

## Future update requirements

Application and model updates would need to be signed, atomic, reversible, and
subject to safety-state controls. No download, signing, update, or release pipeline
is implemented.
