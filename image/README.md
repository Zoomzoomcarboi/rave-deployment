# RAVE OS image build

Gate 1 established the seven-layer declarative image definition, but it had not been
built. Gate 2A pins `raspberrypi/rpi-image-gen` v2.7.0 at commit
`a7b6d4806183195f3efadb533f58c8e46393d057` and has generated and inspected a real
Raspberry Pi 5 image. This is image-build evidence only: the image has not been
qualified from the current networking source on a Pi.

An earlier `gate2b-ethernet-ssh-4c4bb1a` engineering image was flashed and used for
live diagnosis. That work proved three narrow management corrections, then reproduced
a reboot where Ethernet and the management stack survived but the SSH listener did
not. Those manually corrected runtime results are diagnostic hardware evidence, not a
clean-image validation of the current source. The new source still requires the
five-boot procedure in `docs/GATE2B_NETWORK_ACCEPTANCE.md`.

The pin, including the digest-pinned Debian builder container, is recorded in
`rpi-image-gen.lock.json`. The single engineering-image build entry point requires
the intended ED25519 public key as explicit input:

```sh
RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE=/path/to/engineering-key.pub \
  ./scripts/build-rave-os.sh
```

An optional argument selects the output directory. The default is
`build/rave-os-gate2b/`, covered by the repository's narrow `build/` ignore. The
script clones only the pinned tag into that output directory, verifies its full
commit, and uses the repository's `image/` source tree. It runs upstream's required
host tools in a digest-pinned privileged container without passing a block device. It
does not flash media or change host networking. Docker, Git, Python 3, network access
to upstream source/package repositories, and sufficient disk space are prerequisites.

The builder invocation, run inside that controlled container, also receives the
validated public key through the image configuration override:

```sh
/builder/rpi-image-gen build -B /out/work -S /rave/image \
  -c rave-os.yaml -- IGconf_artefact_version=gate2b-<rave-commit> \
  IGconf_rave_ssh_public_key='<validated-ed25519-public-key>'
```

With `-S /rave/image`, v2.7.0 resolves configuration names below that source tree's
`config/` directory, so `-c config/rave-os.yaml` is invalid. Compression is a
deployment setting in this release (`deploy.compression: zstd`); the former
`image.compression` key did not control the deployed artifact.

The build produces the compressed image below `work/deploy-<version>/`, an artifact
safety report, and `provenance.json`. Before the artifact verifier runs, the target
image's own dnsmasq and systemd parsers validate the installed DHCP configuration and
relevant units/drop-ins. The verifier then checks clone identity, credentials,
logs/caches, filesystem ownership, installed web content/dependencies, the exact
management-only listener/AP/DHCP policy, DHCP sandbox/lease state, SSH dependency
isolation, and required boot enablement before provenance is written.

## Composition and limits

The composition starts from upstream `trixie-minbase.yaml`, targets the upstream Pi 5
and Raspberry Pi OS image layers, and adds `rave-base`, `rave-identity`, `rave-network`,
`rave-engineering-ssh`, `rave-hailo`, `rave-runtime`, `rave-web`, and `rave-update`.
Hailo, production perception, and updating remain explicit non-integrated markers.
The management path consists of saved-station startup, the isolated provisioning AP,
typed scan/connect/provisioning operations, and truthful appliance observations. The
new path remains pending target-image and Pi validation.

`rave-engineering-ssh` is a deliberately non-publishable Gate 2B diagnostic feature.
It enables key-only `pi` administration through systemd socket activation bound only
to the exact `10.77.0.1:22` address; it does not expose SSH on the management Wi-Fi
network. `FreeBind=yes` permits early address binding without coupling the socket's
lifetime to the `eth0.device` unit. Direct `ssh.service` boot enablement is removed;
the enabled socket activates the service on demand after per-device host-key
generation. RAVE's unconditional generator is the socket's sole host-key prerequisite;
the distro's conditional generator is not also wired into the socket transaction.
The repository carries no default engineering authorization key. An engineering build
fails unless it receives one valid OpenSSH ED25519 public key; its fingerprint is
recorded in provenance. The resulting non-publishable image carries that public key
and the reviewed sudo policy, never a private key. This access must be removed or
replaced by an approved administration policy before public-release qualification.

Gate 2B explicitly sets the Wi-Fi regulatory domain to `US` for physical validation
units operated in the United States. The appliance timezone is explicitly `Etc/UTC`;
unsynchronized wall time remains reported as unsynchronized. Locale, keyboard, and
first-boot region selection remain later work.
A future public release requires an explicit country-appropriate regulatory-domain
and onboarding policy; no single Wi-Fi regulatory domain is valid everywhere.

The procedure pins builder source and the container base. Debian and Raspberry Pi
package repositories are not snapshot-pinned, and filesystem/image timestamps are not
normalized. Gate 2A therefore establishes a reproducible procedure and provenance,
not bit-for-bit reproducibility.

The final `rave-identity` cleanup runs after package and customization hooks. The
generic image ends with an empty `/etc/machine-id`, no SSH host keys, no RAVE private
identity/pairing/session state, exactly one reviewed product AP profile (and no user
profiles), and no carried logs/caches. First-boot identity behavior still requires Pi
boot validation.
