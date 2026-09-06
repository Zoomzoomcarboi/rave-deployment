# M2B.2 selected-model application VStream ABI

This first bounded M2B.2 step records the user-supplied hardware qualification for:

- Model: `RAVE-2026.09.02-001`, artifact `rave_yolo26n_960.hef`.
- HEF SHA256: `913053bb96815b16b79093924ed563844f8edbc02ef6d40129a290eff3e32aea`.
- Target: Raspberry Pi 5 with Hailo-8 (`HAILO8`), HailoRT `4.23.0`.
- Immutable evidence: `RAVE-2026.09.02-001.output-abi.json` alongside this document.

## Evidence and boundary

The supplied HailoRT CLI `parse-hef` record reports output VStreams in this order:
`conv61`, `conv77`, `conv91`, `conv64`, `conv80`, `conv94`, all under the
`rave_yolo26n_960/` prefix. This order is preserved only as reporting evidence.
The sidecar records the exact qualified input/output names, shapes, types, orders,
and quantization values. Shapes use height, width, features.

The native evidence interface is `hailort::Hef::create()` followed by
`Hef::get_input_vstream_infos()` and `Hef::get_output_vstream_infos()`. The checker
requires exactly one network group, `rave_yolo26n_960`, and exactly one network
in that group, `rave_yolo26n_960/rave_yolo26n_960`, using `Hef::get_network_infos()`.
These exact group/network identities are part of the qualified interface and are
recorded in the sidecar. Only after validating that topology does the checker query
VStreams for the explicitly validated group and validate one input and six outputs
by exact VStream name. It does not aggregate streams across arbitrary groups. It rejects duplicate, missing, unexpected, and mismatched
entries regardless of their vector positions.

These contracts describe application-facing **VStreams**, not packed physical
Hailo **Streams**. Do not substitute low-level Stream shapes, padding, or packing
for these VStream shapes, including where the reported order is `FCR`.

The native API and metadata types were checked against the
[HailoRT 4.23.0 HEF declarations](https://github.com/hailo-ai/hailort/blob/v4.23.0/hailort/libhailort/include/hailo/hef.hpp)
and [HailoRT metadata declarations](https://github.com/hailo-ai/hailort/blob/v4.23.0/hailort/libhailort/include/hailo/hailort.h).
The quantization rule is:

```text
real = (raw - qp_zp) * qp_scale
```

Quantization fields are native float32. Qualified decimal literals are rounded to
float32 and compared exactly, with no epsilon allowance. This rejects non-finite
values and changes as small as one representable float step.

## Manual check and image installation

On the appliance, first verify the HEF identity using the unchanged M2B.1 validator:

```sh
/usr/libexec/rave/rave-model validate /opt/rave/models/RAVE-2026.09.02-001/manifest.json /opt/rave/models/RAVE-2026.09.02-001
/usr/libexec/rave/rave-hef-abi-check /opt/rave/models/RAVE-2026.09.02-001/rave_yolo26n_960.hef
```

Proceed to the ABI check only if identity validation succeeds. The ABI checker
reads HEF metadata without configuring a device or performing inference. Exit 0
means the VStream metadata matches; exit 1 reports a read or ABI mismatch, and
exit 2 reports incorrect arguments. It does not hash the file, check a connected
accelerator, or change installed models, current, or known-good.

The image layer compiles C++17 against its pinned installed HailoRT during image
construction. It installs the checker root-owned mode 0755 and the evidence at
`/usr/share/rave/models/RAVE-2026.09.02-001.output-abi.json`, root-owned mode 0644.
No startup compilation or HEF inclusion is added.

## Qualification limits

M2B.1 remains hardware-validated CLOSED/PASS per the supplied baseline. Its
manifest is unchanged, including `output_abi: null`, and its administrative
utility and installed-model semantics are unchanged.

The hardware qualification values above are supplied evidence, not a claim that
this task repeated `parse-hef` or native introspection on a Pi. Host tests use a
synthetic native API and do not prove device execution. The checker also received
a syntax check with existing HailoRT headers; a fresh target image build and checker
execution against the selected HEF remain acceptance work.

ABI qualification does not qualify YOLO decoding semantics, camera integration,
or the production perception runtime. `PERCEPTION_NOT_INTEGRATED` remains present.
No inference, decoder, tracking, temporal logic, transport, or service integration
is introduced by this step.
