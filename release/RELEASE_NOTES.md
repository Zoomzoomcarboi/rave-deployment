# RAVE OS Gate 2B Test

This is the first end-user-style RAVE OS image prepared for physical
Raspberry Pi 5 first-boot validation.

Gate 2A passed:

- reproducible image-build procedure
- pinned rpi-image-gen v2.7.0
- generated Raspberry Pi 5 image
- filesystem contract verification
- clone-safety verification
- empty generic machine identity
- no SSH host keys carried into the generic image
- no user NetworkManager profiles
- no RAVE private/pairing/session state
- artifact-integrity verification
- machine-readable provenance
- independent engineering review

Not yet validated:

- physical Raspberry Pi 5 boot
- first-boot machine-id generation
- first-boot SSH host-key generation
- root filesystem expansion
- service startup posture
- management networking
- Hailo-8 / AI HAT+
- Arducam B0589
- production perception runtime
- C3X runtime link
- vehicle or road operation

This release must not be treated as production-ready or road-ready.
