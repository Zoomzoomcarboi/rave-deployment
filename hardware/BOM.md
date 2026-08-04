# Candidate hardware matrix

Every item below is candidate hardware. Nothing is approved until it passes bench,
thermal, electrical, camera, networking, installation, and vehicle-environment tests.
In particular, there is no approved production camera.

| Component | Candidate hardware | Status | Validation required |
|---|---|---:|---|
| Computer | Candidate Raspberry Pi 5, 8 GB | Candidate / unvalidated | boot, thermal, USB load, storage endurance |
| Accelerator | Candidate Raspberry Pi AI HAT+ 26 TOPS / Hailo-8 | Candidate / unvalidated | exact SKU and runtime compatibility |
| Camera | Candidate rear-facing camera, not selected | Candidate / unvalidated | VID/PID, FOV, exposure, low light, crop |
| Storage | Candidate 64 GB high-endurance microSD | Candidate / unvalidated | sustained writes, power-loss behavior |
| Cooling | Candidate active cooler/case | Candidate / unvalidated | enclosed-car thermal soak |
| Pi power | Candidate automotive regulated 5 V supply | Candidate / unvalidated | crank, load dump, brownout, shutdown |
| Comma adapter | Candidate USB-C-to-Ethernet adapter | Candidate / unvalidated | platform enumeration and link recovery |
| Ethernet | Candidate short Ethernet cable | Candidate / unvalidated | EMI and installation durability |
| Mount | Candidate high-center rear-glass mount | Candidate / unvalidated | vibration, temperature, field of view |

## Future release rule

Any future public image must name an exact validated hardware profile and reject or
clearly warn about unsupported substitutions. This repository does not currently
produce such an image.
