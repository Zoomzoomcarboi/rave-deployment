# Candidate and validated hardware matrix

No complete production hardware profile is approved yet. Individual components may be
validated for a specific function without being release-qualified as a full system.

| Component | Hardware | Current status | Remaining validation |
|---|---|---:|---|
| Computer | Raspberry Pi 5, 8 GB target | **Hard target / unvalidated runtime** | inference/tracking latency, thermal, USB load, storage endurance |
| Accelerator | Raspberry Pi AI HAT+ 26 TOPS / Hailo-8 candidate | Candidate / unvalidated | exact SKU, runtime/model compatibility, latency/headroom |
| Camera | Arducam B0589 USB/UVC (`04b4:0822`) | **Validated on ZBook development path** | Pi USB path, thermal, exposure/low light, vehicle-environment/FOV qualification |
| Storage | 64 GB high-endurance microSD candidate | Candidate / unvalidated | sustained writes, power-loss behavior |
| Cooling | Active cooler/case candidate | Candidate / unvalidated | enclosed-car thermal soak |
| Pi power | Automotive regulated 5 V supply candidate | Candidate / unvalidated | crank, load dump, brownout, orderly shutdown |
| Comma adapter | ASIX AX88179/AX88179A (`ax88179_178a`, `0b95:1790`) | **C3X hardware-validated; reboot persistence passed** | cable/vehicle EMI durability and longer soak |
| Comma adapter | Realtek RTL8152/RTL8153 (`r8152`; tested `0bda:8153`) | **C3X hardware-validated; reboot persistence passed** | cable/vehicle EMI durability and longer soak |
| Ethernet | Short dedicated Ethernet cable | Link validated in development setup | EMI and installation durability |
| Mount | High-center rear-glass mount | Deployment location selected | vibration, temperature, repeatability, final FOV |

## Camera baseline

The B0589 development path has been validated at 1920x1080 MJPEG 60 FPS. The current
live-inference baseline uses a 1920x391 software crop (`y=300:691`) and YOLO input
size 960. This does not yet make the camera or crop production-approved on the Pi 5.

## Future release rule

Any future public image must name an exact validated hardware profile and reject or
clearly warn about unsupported substitutions. Component-level validation must not be
represented as full-system qualification.
