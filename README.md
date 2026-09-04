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

For that reason **console** is the recommended UI for first boot tests. Graphical UIs can be selected in the workflow for future testing, but a successful image build does not mean the LCD will display anything yet.

## Build

Open **Actions → Build postmarketOS → Run workflow**.

Useful inputs:

- **Channel**: `edge` (recommended for bring-up) or `v26.06` (stable)
- **UI**: `console`, `fbkeyboard`, `weston`, `xfce4`, `phosh`, `plasma-mobile`
- **Username**: Linux account name created in the image
- **Password**: temporary Linux password used by pmbootstrap (workflow inputs are not secret)
- **Extra packages**: optional comma-separated Alpine/postmarketOS packages
- **UI extras**: include the optional extras recommended by the selected UI
- **Debug tools**: add `strace`, `evtest`, `i2c-tools`, `mmc-utils`, `util-linux`, `e2fsprogs-extra`, `nano`
- **Extra image space**: 512/1024/2048/4096 MiB
- **SSH server**: enabled by default for headless bring-up

The root filesystem is fixed to **ext4** and the initial bring-up uses **OpenRC**.

## Kernel releases

The postmarketOS builder does **not** compile Linux anymore.

Kernel development stays in:

`vildangil/mediapad-s10-hi3620-linux`

For each kernel version, publish a normal GitHub release there and attach the CI artifact renamed exactly to:

`kernel.zip`

The postmarketOS workflow automatically queries GitHub `releases/latest`, downloads `kernel.zip`, verifies the GitHub SHA-256 digest when available, and extracts:

- `zImage`
- `hi3620-s10-101x.dtb`

The ZIP may also contain `zImage-dtb`, `kernel.config`, `SHA256SUMS`, and `kernel.release`; they do not hurt. The builder deliberately uses the **plain `zImage`**, because `deviceinfo_append_dtb=true` makes postmarketOS append the DTB itself when creating `boot.img`.

For the current Linux tree, if `kernel.release` is not present in the ZIP the builder falls back to `4.9.51`.

This means updating postmarketOS to a newer kernel is simply:

1. build the kernel in `mediapad-s10-hi3620-linux`;
2. create a newer normal GitHub release;
3. upload its artifact as `kernel.zip`;
4. run the postmarketOS workflow again.

No commit SHA or kernel source checksum needs to be edited in this repository.

## Local pmaports overlay

The workflow clones the selected official pmaports branch and then overlays:

- `device-huawei-s10-101x`
- `linux-huawei-s10-101x`

`linux-huawei-s10-101x` is now only a small prebuilt-kernel APK wrapper. It installs the downloaded `zImage`, board DTB and kernel release metadata in the locations expected by postmarketOS.

The device package contains the stock Huawei Android boot header v0 layout and the current `kernel-cmdline.conf` debug console configuration.

## Artifacts

A successful run exports postmarketOS images into the workflow artifact together with:

- `deviceinfo`
- `kernel-cmdline.conf`
- `kernel-release.txt` with the exact release tag/URL/digests used
- `pmbootstrap_v3.cfg`
- `pmbootstrap.log` when available
- `SHA256SUMS`

Because this tablet has no working `fastboot boot` command, the CI deliberately does not try to test or flash the generated image.

## Flashing warning

The old Huawei fastboot implementation accepts transfers but does **not** implement `fastboot boot` (`invalid command`). Do not blindly flash rootfs images to internal eMMC partitions. The stock partition table contains bootloader/NVME/OEM/modem partitions and must be preserved.

When we start hardware testing, keep a copy of the original `boot.img` and only use flashing commands that have been explicitly verified for this tablet.
