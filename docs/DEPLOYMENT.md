# Deployment workflow

## Customer path

1. Assemble only the approved hardware profile.
2. Select **RAVE OS Stable** in Raspberry Pi Imager, or flash the `.img.xz` release asset with **Use Custom**.
3. Insert storage and connect camera, Ethernet, and power.
4. Connect a phone to the temporary `RAVE-SETUP-*` network.
5. Open the setup portal and complete hardware checks.
6. Enable RAVE in a compatible Starpilot build and enter the displayed pairing code.
7. Confirm that both systems report **Ready** before use.

## Developer path

Developers may install the Debian package on the pinned Raspberry Pi OS release using `scripts/install.sh`. This is not the supported customer path.

## Updates

Normal application and model updates should be signed, atomic, reversible, and blocked while the vehicle is moving or the perception service is active. Major base-OS migrations may require reflashing.
