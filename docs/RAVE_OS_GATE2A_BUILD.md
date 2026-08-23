# RAVE OS Gate 2A build record

Gate 1 provided a declarative definition but no successful image build. On
2026-08-23 UTC, Gate 2A generated and inspected a final Raspberry Pi image using the
accepted foundation commit `a65fff1a08c3facdb3f1b9a0d121dc8c7ffaad10` plus the
uncommitted Gate 2A changes described by the generated provenance's dirty-worktree
flag.

## Pinned builder and command

- Repository: `https://github.com/raspberrypi/rpi-image-gen.git`
- Tag: `v2.7.0`
- Commit: `a7b6d4806183195f3efadb533f58c8e46393d057`
- Builder container: `docker.io/library/debian@sha256:34cd9e9fd437c0a095ec39cb2e73422c9f30821b0d0848ed74fd0d43bae4d958`
- Configuration: `image/config/rave-os-gate1.yaml`
- Target: Raspberry Pi 5, arm64

```sh
/builder/rpi-image-gen build -B /out/work -S /rave/image \
  -c rave-os-gate1.yaml -- IGconf_artefact_version=gate2a-a65fff1a08c3
```

The upstream tag was resolved directly from Git and the checkout's full commit was
verified before the build. The source tree, configuration resolution, composable
layer metadata, mmdebstrap hook lifecycle, Pi 5 device layer, Raspberry Pi OS image
layer, and deployment behavior were reviewed against that pinned checkout rather than
upstream master.

## Artifact evidence

- Artifact: `rave-os-gate2a.img.zst`
- Compressed size: `226179879` bytes
- SHA-256: `656d26d3ef13ccb30f6f7905c3232bcb30c5df57651e4819fc06134f0a84931a`
- Raw image size: `1778384896` bytes
- Partition table: DOS; 104 MiB FAT32 boot partition and 1.5 GiB Linux root partition
- Build output used for this record: `/tmp/rave-gate2a-build/`

The generated artifact is intentionally not tracked by Git. Its machine-readable
verification report and provenance record are alongside that build output. The
provenance records the RAVE commit, dirty-worktree state, exact builder tag/commit,
builder-container digest, target, configuration, timestamp, artifact filename, size,
digest, and reproducibility qualifications.

## Filesystem validation

The artifact/rootfs checks passed for an empty machine ID; absent D-Bus machine ID,
SSH host keys, NetworkManager user profiles, RAVE private identity/pairing/session
state, logs, caches, developer paths, injected build identities, Wi-Fi secrets, and
private-key markers. The `rave` account, RAVE directory modes/ownership, tmpfiles
contract, web Python/static files, Galaxy notice, and direct FastAPI/Pydantic/Uvicorn
Debian dependencies were present. `rave-webd` remained disabled, unprivileged, and
bound to loopback only. Network, Hailo, perception, and update layers retained their
truthful non-integrated markers.

These are artifact facts, not hardware-functionality claims.

## Reproducibility and validation boundary

Builder source and the container base are pinned. Debian and Raspberry Pi package
repositories are not snapshot-pinned, and output timestamps are not normalized.
No bit-for-bit reproducibility claim is made without independent builds and matching
hashes.

Still unvalidated are Pi 5 boot, first-boot identity regeneration, Hailo-8/AI HAT+,
Arducam B0589, management Wi-Fi, provisioning AP, dedicated Ethernet behavior,
thermal/power behavior, runtime performance, YOLO/Hailo inference, ByteTrack,
perception/temporal/threat processing, the C3X link, and road operation. The image is
not release-qualified or production-ready.
