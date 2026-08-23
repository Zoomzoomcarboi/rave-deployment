# RAVE OS Gate 2B Test

This is source scaffolding for an unpublished Gate 2B candidate intended for
physical Raspberry Pi 5 first-boot validation. Local development builds have
passed artifact verification, but no clean-HEAD Gate 2B release artifact or
public release exists yet.

Candidate packaging generates the image, `SHA256SUMS`, and `release.json` under
the selected ignored `build/<build-name>/candidate/` directory. Artifact hashes,
sizes, source commit, and dirty-worktree state come from the validated artifact
and its matching build provenance; build-specific metadata is not tracked here.

Gate 2A passed:

- reproducible image-build procedure
- pinned rpi-image-gen v2.7.0
- generated Raspberry Pi 5 image
- filesystem contract verification
- clone-safety verification
- empty generic machine identity
- no SSH host keys carried into the generic image
- only the reviewed open RAVE-Setup product NetworkManager profile
- no RAVE private/pairing/session state
- artifact-integrity verification
- machine-readable provenance
- independent engineering review

Not yet validated:

- physical Raspberry Pi 5 boot
- first-boot machine-id generation
- first-boot SSH host-key generation
- root filesystem expansion
- physical AP and service startup behavior
- Hailo-8 / AI HAT+
- Arducam B0589
- production perception runtime
- C3X runtime link
- vehicle or road operation

This release must not be treated as production-ready or road-ready.
