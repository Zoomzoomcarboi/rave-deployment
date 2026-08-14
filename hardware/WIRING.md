# Physical topology

## Target deployment topology

```text
Arducam B0589 USB rear camera
          |
          | USB
          v
Raspberry Pi 5 + selected accelerator
10.77.0.1/24
          |
          | built-in RJ45 Ethernet
          v
Dedicated short Ethernet cable
          |
          v
C3X USB-C Ethernet adapter
ASIX AX88179/AX88179A or validated Realtek RTL8153
          |
          v
Comma 3X
10.77.0.2/24
```

The dedicated RAVE link has no gateway or DNS and must never replace or disturb the
Comma's normal Wi-Fi/LTE/default route. The Comma-side profile is backend-managed and
must not depend on a hardcoded interface name, MAC address, or NetworkManager UUID.

ASIX AX88179/AX88179A and Realtek RTL8153 (`r8152`) both passed the current C3X
hardware-validation path, including pairing/profile reuse, hotplug behavior, and
reboot persistence. An earlier Realtek reboot-enumeration/reset event was not
reproduced during the final untouched-reboot validation.

The Pi must have its own validated automotive power supply. Power conditioning,
shutdown behavior, and vehicle-environment EMI/thermal qualification remain open.
