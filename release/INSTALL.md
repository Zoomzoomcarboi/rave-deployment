# Flash RAVE OS to a microSD card

These instructions are for installing a pre-built RAVE OS image.
You do not need to build RAVE OS yourself.

## 1. Download RAVE OS

Go to:

https://github.com/Zoomzoomcarboi/rave-deployment/releases

Open the newest supported RAVE OS release.

Download:

RAVE-OS-Pi5-Gate2B-Test.img.xz

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

RAVE-OS-Pi5-Gate2B-Test.img.xz

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

For the current Gate 2B test release, connect a display and keyboard
before first boot so first-boot behavior can be observed directly.

Power on the Raspberry Pi 5.

## Current validation boundary

The Gate 2B test image is intended for appliance bring-up and validation.

Hailo inference, camera operation, RAVE perception, C3X integration,
vehicle integration, and road operation are not qualified by these
flashing instructions.
