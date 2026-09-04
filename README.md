# postmarketOS builder for Huawei MediaPad 10 FHD

Private CI workspace for bringing up postmarketOS on the Huawei MediaPad 10 FHD S10-101x (HiSilicon K3V2 / Hi3620).

## What this repository builds

- ARMv7 postmarketOS root filesystem
- a Huawei/Android `boot.img` using the custom Hi3620 Linux 4.9 kernel
- separate boot/root images (`pmbootstrap install --split`)
- build logs, selected configuration and SHA256 checksums as GitHub Actions artifacts

Nothing in this repository flashes the tablet automatically.

## Current hardware status

The kernel builds successfully and currently has early Hi3620 support for CPU/GIC/timers/PL011 plus initial K3 DW-MMC nodes for the internal eMMC and removable SD controller. The display, touch, USB gadget/networking, Wi-Fi, audio and power management are not considered working yet.

For that reason **Console** is the recommended UI for first boot tests. Graphical UIs can be selected in the workflow for future testing, but a successful image build does not mean the LCD will display anything yet.

## Build

Open **Actions → Build postmarketOS → Run workflow**.

Useful inputs:

- **Channel**: `edge` (recommended for bring-up) or `v26.06` (stable)
- **UI**: `console`, `fbkeyboard`, `weston`, `xfce4`, `phosh`, `plasma-mobile`
- **Extra packages**: optional comma-separated Alpine/postmarketOS packages
- **UI extras**: include the optional extras recommended by the selected UI
- **Debug tools**: add `strace`, `evtest`, `i2c-tools`, `mmc-utils`, `util-linux`, `e2fsprogs-extra`, `nano`
- **Extra image space**: 512/1024/2048/4096 MiB
- **SSH server**: enabled by default for headless bring-up

The root filesystem is intentionally fixed to **ext4**. The service manager is left on postmarketOS `default`, so the selected UI can choose its supported manager; the recommended console bring-up remains the lightweight path.

The CI-only initial login password is `147147`. Do not reuse it for a real installation exposed to a network.

## Local pmaports overlay

The workflow clones the selected official pmaports branch and then overlays:

- `device-huawei-s10-101x`
- `linux-huawei-s10-101x`

The device package contains the stock Huawei Android boot header v0 layout and the current `kernel-cmdline.conf` debug console configuration.

## Kernel source

The local kernel aport is pinned to the known-good MediaPad branch in:

`vildangil/mediapad-s10-hi3620-linux`

It applies the compatibility fixes required to build this Linux 4.9 tree with current Alpine/GNU toolchains, including forcing ARMv7-A so Alpine's hard-float cross compiler cannot trigger the old kernel's ARMv5 fallback. It then builds `zImage` and `hi3620-s10-101x.dtb`.

## Artifacts

A successful run exports postmarketOS images into the workflow artifact together with:

- `deviceinfo`
- `kernel-cmdline.conf`
- `pmbootstrap_v3.cfg`
- `pmbootstrap.log` when available
- `SHA256SUMS`

Because this tablet has no working `fastboot boot` command, the CI deliberately does not try to test or flash the generated image.

## Flashing warning

The old Huawei fastboot implementation accepts transfers but does **not** implement `fastboot boot` (`invalid command`). Do not blindly flash rootfs images to internal eMMC partitions. The stock partition table contains bootloader/NVME/OEM/modem partitions and must be preserved.

When we start hardware testing, keep a copy of the original `boot.img` and only use flashing commands that have been explicitly verified for this tablet.
