# RAVE OS image

This directory will contain the pinned `rpi-image-gen` configuration used to build RAVE OS from Raspberry Pi OS Lite 64-bit.

A future production image would need to:

- pin the Raspberry Pi OS base release and package snapshot;
- install the accelerator-specific Hailo runtime;
- install the signed `rave-edge` Debian package;
- create the unprivileged `rave` service account;
- configure an alias for an exact, validated camera (none is currently approved);
- configure the direct Ethernet network;
- keep the edge service disabled until a production runtime exists;
- use a resilient/mostly read-only filesystem design where practical;
- include no private signing keys, training data, or GitHub credentials;
- emit a machine-readable build manifest and SHA-256 checksum.

`mock-image.yml` is intentionally descriptive and is not yet a valid `rpi-image-gen` configuration.
It does not build or publish an image.
