# RAVE OS image build

Gate 1 established the seven-layer declarative image definition, but it had not been
built. Gate 2A pins `raspberrypi/rpi-image-gen` v2.7.0 at commit
`a7b6d4806183195f3efadb533f58c8e46393d057` and has generated and inspected a real
Raspberry Pi 5 image. This is image-build evidence only: the image has not been
flashed, booted, or validated on a Pi.

The pin, including the digest-pinned Debian builder container, is recorded in
`rpi-image-gen.lock.json`. The single build entry point is:

```sh
./scripts/build-rave-os.sh
```

An optional argument selects the output directory. The default is
`build/rave-os-gate2a/`, covered by the repository's narrow `build/` ignore. The
script clones only the pinned tag into that output directory, verifies its full
commit, and uses the repository's `image/` source tree. It runs upstream's required
host tools in a digest-pinned privileged container without passing a block device. It
does not flash media or change host networking. Docker, Git, Python 3, network access
to upstream source/package repositories, and sufficient disk space are prerequisites.

The known-good upstream invocation, run inside that controlled container, is:

```sh
/builder/rpi-image-gen build -B /out/work -S /rave/image \
  -c rave-os-gate1.yaml -- IGconf_artefact_version=gate2a-<rave-commit>
```

With `-S /rave/image`, v2.7.0 resolves configuration names below that source tree's
`config/` directory, so `-c config/rave-os-gate1.yaml` is invalid. Compression is a
deployment setting in this release (`deploy.compression: zstd`); the former
`image.compression` key did not control the deployed artifact.

The build produces the compressed image below `work/deploy-<version>/`, an artifact
safety report, and `provenance.json`. The verifier checks clone identity, credentials,
logs/caches, filesystem ownership, installed web content/dependencies, loopback-only
service configuration, and the deliberately disabled `rave-webd` unit before
provenance is written.

## Composition and limits

The composition starts from upstream `trixie-minbase.yaml`, targets the upstream Pi 5
and Raspberry Pi OS image layers, and adds `rave-base`, `rave-identity`, `rave-network`,
`rave-hailo`, `rave-runtime`, `rave-web`, and `rave-update`. Hailo, perception,
network actuation, provisioning, and updating remain explicit non-integrated markers.

The procedure pins builder source and the container base. Debian and Raspberry Pi
package repositories are not snapshot-pinned, and filesystem/image timestamps are not
normalized. Gate 2A therefore establishes a reproducible procedure and provenance,
not bit-for-bit reproducibility.

The final `rave-identity` cleanup runs after package and customization hooks. The
generic image ends with an empty `/etc/machine-id`, no SSH host keys, no RAVE private
identity/pairing/session state, no NetworkManager user profiles, and no carried
logs/caches. First-boot identity behavior still requires Pi boot validation.
