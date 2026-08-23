# Flash RAVE OS to a microSD card

These are the acceptance steps to use after a validated Gate 2B candidate is
provided locally. No downloadable Gate 2B image is currently published.

## 1. Download RAVE OS

After a validated build has been packaged, obtain the reviewed local
`build/<build-name>/candidate/RAVE-OS-Pi5-Gate2B-Candidate.img.xz` and verify it
against the `SHA256SUMS` generated in that same candidate directory. Do not
infer an asset URL. No Gate 2B public download currently exists.

Do not extract the image.

## 2. Install Raspberry Pi Imager

Install Raspberry Pi Imager 2.x from Raspberry Pi.

## 3. Insert the microSD card

Insert the microSD card into your computer.

Everything currently stored on that card will be erased.

## 4. Open Raspberry Pi Imager

Choose:

Device
  → Raspberry Pi 5

Choose:

Operating System
  → Use Custom

Select:

RAVE-OS-Pi5-Gate2B-Candidate.img.xz

Choose:

Storage
  → your microSD card

Carefully verify that you selected the correct removable device.

## 5. Do not customize the image

Do not add Raspberry Pi Imager hostname, Wi-Fi, user, SSH,
or other OS customizations to this release.

RAVE currently uses an unmodified appliance image for validation.

## 6. Write the image

Select Write.

Confirm that the selected microSD card may be erased.

Allow Raspberry Pi Imager to complete both:

Writing
and
Verification

Do not remove the card until Imager reports that the operation
completed successfully.

## 7. Boot RAVE

Remove the microSD card from the computer.

Make sure the Raspberry Pi 5 is powered off.

Insert the card into the Raspberry Pi 5.

Power on the Raspberry Pi 5.

Join the open `RAVE-Setup` Wi-Fi network from a phone or laptop, then browse to
`http://192.168.77.1:8080`. No display, keyboard, SSH, or shell is required.

## Current validation boundary

The Gate 2B test image is intended for appliance bring-up and validation.

The open AP is prerelease-only. Secure per-device onboarding is required before
production or public-release qualification.

Hailo inference, camera operation, RAVE perception, C3X integration,
vehicle integration, and road operation are not qualified by these
flashing instructions.
