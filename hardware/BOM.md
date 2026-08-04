# Approved hardware matrix

No part is approved until it has passed bench, thermal, electrical, camera, networking, and vehicle testing.

| Component | Candidate | Status | Validation required |
|---|---|---:|---|
| Computer | Raspberry Pi 5, 8 GB | Candidate | boot, thermal, USB load, storage endurance |
| Accelerator | Raspberry Pi AI HAT+ 26 TOPS / Hailo-8 | Candidate | exact SKU and runtime compatibility |
| Camera | RAVE production rear camera | TBD | VID/PID, FOV, exposure, low light, crop |
| Storage | 64 GB high-endurance microSD | TBD | sustained writes, power-loss behavior |
| Cooling | Active cooler/case | TBD | enclosed-car thermal soak |
| Pi power | Automotive regulated 5 V supply | TBD | crank, load dump, brownout, shutdown |
| Comma adapter | USB-C to Ethernet | TBD | AGNOS enumeration and link recovery |
| Ethernet | Short shielded/unshielded cable | TBD | EMI and installation durability |
| Mount | High-center rear-glass mount | TBD | vibration, temperature, field of view |

## Release rule

A public RAVE OS image must declare the exact supported hardware profile. Unsupported substitutions should produce a clear warning or prevent activation when they could invalidate safety or performance assumptions.
