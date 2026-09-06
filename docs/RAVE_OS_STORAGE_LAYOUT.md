# RAVE OS storage layout

RAVE OS Gate 2B uses the pinned `rpi-image-gen` `image-rpios` layout. This is a
single-system MBR image with two filesystems:

| Partition | Filesystem label | Stable alias | Configured size |
|---|---|---|---:|
| Boot | `BOOT` | `/dev/disk/by-slot/boot` | 512 MiB |
| System/root | `ROOT` | `/dev/disk/by-slot/system` | 12 GiB |

The `/dev/disk/by-slot/system` name is a stable udev alias for the filesystem labeled
`ROOT`. It is not an A/B slot selector. The current image has no alternate system
partition, persistent-data partition, or implemented OS rollback service.

## Why the image is fixed at 12 GiB

The inherited Trixie minimum-base configuration used `root_part_size: 300%`. That
percentage is relative to populated filesystem content, not the target SD-card size.
The observed build therefore produced a roughly 1.5 GiB root filesystem regardless of
the 64 GB-class card onto which it was flashed.

Gate 2B now overrides the inherited percentage with explicit binary units:

```yaml
image:
  layer: image-rpios
  boot_part_size: 512M
  root_part_size: 12G
```

The fixed system size provides deterministic space for the Debian/Raspberry Pi OS
base, the future compatible Hailo stack, package metadata, RAVE services, and multiple
model states. M2B.1 stores immutable installed model artifacts under
`/opt/rave/models`, with staging on that same filesystem. Mutable RAVE state remains
under `/var/lib/rave`. Both paths currently reside on the system/root filesystem;
a dedicated persistent-data partition remains deferred.

The generated image is deliberately flashable to different supported media sizes. On
every boot, `rave-grow-rootfs.service` verifies that the mounted root is ext4, labeled
`ROOT`, resolves through `/dev/disk/by-slot/system`, is partition 2 on the physical MBR
boot device, and is the final partition after the unchanged `BOOT` partition. It then:

1. removes any prior completion record so a failure cannot leave a stale success claim;
2. uses `growpart` only when meaningful trailing capacity exists;
3. verifies the root start sector and complete boot-partition entry are unchanged;
4. requires no more than 16 MiB of alignment slack at the end of the device;
5. runs `resize2fs`, including after a prior partition-only partial operation;
6. verifies the ext4 filesystem fills the expanded partition; and
7. atomically records the verified final geometry under
   `/var/lib/rave/storage/root-expanded-v1.json`.

The service is idempotent and remains enabled rather than relying on its completion
record as a skip condition. Moving an already-used image to larger compatible media
therefore triggers another verified expansion.

On a representative 58.3 GiB physical device, first boot should retain the 512 MiB
boot partition and expand root from its 12 GiB image size to approximately 57.8 GiB,
leaving at most 16 MiB of unavoidable alignment slack. The same geometry-driven logic
applies to 32 GB, 64 GB, 128 GB, and larger compatible media.

## Deliberate boundary

A third data partition is not added in this gate. The current single-system image
layer has no such partition, and mounting a new empty filesystem over `/var/lib/rave`
would hide image-provisioned state and change update, identity, reset, ownership, and
recovery semantics. Those contracts must be designed together rather than inferred
from spare card capacity.

Likewise, the repository does not switch to the available upstream A/B GPT image
layer. A/B boot selection, persistent-data migration, signed updates, health-gated
activation, and rollback remain later release work requiring their own implementation
and hardware fault testing.

The image configuration verifier enforces this bounded contract and rejects a return
to percentage-based or sub-12-GiB system sizing. Host tests exercise representative
partition geometry and fail when multi-gigabyte trailing capacity remains. Actual
`findmnt`, `lsblk`, `blockdev`, partition-end, `resize2fs`, and filesystem-size results
remain first-boot acceptance evidence; this source change is host-validated only until
a new image is built, inspected, flashed, and Pi-validated.
