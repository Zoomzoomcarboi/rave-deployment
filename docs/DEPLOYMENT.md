# Deployment workflow

There is no customer deployment today. No signed release image, production RAVE
metadata receiver, pairing/authentication flow, automotive power design, or complete
Pi 5 performance qualification exists yet.

There are, however, hardware-validated development baselines that must be preserved
as deployment work moves forward. See `VALIDATED_BASELINES.md`.

## Hard target

Raspberry Pi 5 is the deployment target and must be treated as the performance budget
from the beginning. Deployment candidates that only work after assuming desktop-class
compute are not acceptable. Low frame age, stale-frame dropping, bounded processing,
and compute headroom are release requirements rather than later optimizations.

## Dedicated runtime network baseline

The intended runtime transport is a dedicated wired Ethernet link:

```text
RAVE computer / future Pi 5   10.77.0.1/24
Comma 3X                      10.77.0.2/24
```

The Comma-side RAVE profile uses no gateway or DNS, is `never-default`, disables IPv6,
and must preserve the device's normal Wi-Fi/default-route behavior. Provisioning is
owned by the StarPilot backend and must work without requiring SSH, terminal commands,
or manual NetworkManager setup on a fresh supported adapter.

Both supported C3X adapter paths have passed hardware validation including reboot
persistence: ASIX AX88179/AX88179A (`ax88179_178a`, `0b95:1790`) and Realtek RTL8153
(`r8152`, tested `0bda:8153`). An earlier Realtek reboot-enumeration/reset event was
not reproduced during the final untouched-reboot validation and is treated as a
transient test event rather than a qualification failure.

## Development path

Developers can validate configuration and run the explicitly gated mock as described
in the repository README. `scripts/install.sh`, Debian packaging, systemd services,
and image files are still scaffolding and do not install the validated ZBook or C3X
integration work as a production Pi perception service.

## Release/update requirements

Application and model updates must eventually be signed, atomic, reversible, and
subject to safety-state controls. Release readiness also requires a reproducible Pi
image, exact hardware compatibility checks, thermal/power validation, fault injection,
and a rollback path. No production update pipeline is implemented yet.
