# M2B.1 manual model storage

This gate implements administrative storage only. It does not load a HEF, restart
perception, qualify a decoder, or enable automatic updates. Run mutation commands
as root on the appliance, at an operator-controlled maintenance boundary.

The image creates an empty root-owned, mode 0755 `/opt/rave/models` and installs
`/usr/libexec/rave/rave-model`. The `rave` service account can read models but cannot
write the store. HEFs are supplied separately; no model binary is in Git or the image.

The selected metadata is in `RAVE-2026.09.02-001.manifest.json` beside this document.
Only this exact model ID, artifact name, SHA256 and compatibility metadata are
accepted. Arbitrary release IDs, hashes and paths from manifests are not accepted.
The older `example-manifest.json` is not an M2B.1 manifest.

Example appliance commands, with the selected HEF and repository manifest supplied
in `/mnt/model-release`:

```sh
sudo /usr/libexec/rave/rave-model install /mnt/model-release/RAVE-2026.09.02-001.manifest.json /mnt/model-release
sudo /usr/libexec/rave/rave-model activate RAVE-2026.09.02-001
```

`validate MANIFEST SOURCE_DIRECTORY` checks without installing. An existing version
is validated and reported as installed; it is never overwritten. Temporary staging
is inside the store, on the same filesystem. Failed copies or validation are removed
without changing pointers. A process killed mid-operation may leave hidden staging
content; it cannot be selected for activation. Administrative writes take a nonblocking
filesystem lock; an overlapping command fails and may be retried manually.

Installed files are mode 0644 and version directories are 0755. The utility never
modifies installed versions. Files and directories are synced before publication;
`current` is replaced by an atomic symlink rename. Hardware power-loss qualification
is still outstanding. The storage pointer is not connected to the runtime.

After independent qualification, an operator explicitly records known-good:

```sh
sudo /usr/libexec/rave/rave-model qualify RAVE-2026.09.02-001
sudo /usr/libexec/rave/rave-model rollback
```

`qualify` records the operator's attestation; it does not perform qualification.
Installation and activation never change known-good implicitly. Rollback reads its
relative model ID, revalidates the installed manifest and HEF, then atomically
replaces current. Missing, broken, corrupt and out-of-store targets are rejected.

## Evidence boundary

The M2B.1 request supplies the selected ID, HEF filename, SHA256, Hailo-8 target,
HailoRT 4.23.0, 960x960 UINT8/NHWC input and vehicle/motorcycle class order.
The repository's older V5 records describe six raw output heads, but do not bind
exact output names, shapes, formats or quantization to this selected SHA256.
Consequently `output_abi` is explicitly null. No output ABI has been fabricated.
Validation checks declared HailoRT compatibility, not the installed hardware/runtime.

For this bounded gate, activation means only changing a storage pointer, as requested
for M2B.1. It does not supersede AGENTS.md's prohibition on runtime activation of an
unknown output ABI. Exact selected-model ABI evidence and decoder compatibility must
be established before runtime integration. Signing, downloads, runtime self-tests,
automatic rollback and M2B.2 remain outside this gate.
