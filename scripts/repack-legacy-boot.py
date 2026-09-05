#!/usr/bin/env python3
"""Recompress an Android boot image v0 ramdisk as kernel-compatible XZ.

Huawei MediaPad 10 FHD has an 8 MiB boot partition. postmarketOS' generated
initramfs is an XZ stream for this port, but its default compressor settings
leave boot.img slightly too large and modern XZ defaults use CRC64. Linux 4.9
in the S10 kernel accepts CRC32 but rejects CRC64 during early initramfs
unpacking. This tool keeps the exact initramfs contents, recompresses them with
XZ preset 9 + CRC32, then updates ramdisk_size and the legacy boot SHA-1 id.
"""

from __future__ import annotations

import argparse
import hashlib
import lzma
import struct
from pathlib import Path

ANDROID_MAGIC = b"ANDROID!"
ID_OFFSET = 576
ID_SIZE = 32
RAMDISK_SIZE_OFFSET = 16


def align(value: int, page: int) -> int:
    return (value + page - 1) // page * page


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    image = args.input.read_bytes()
    if image[:8] != ANDROID_MAGIC:
        raise SystemExit("not an Android boot image")

    (
        kernel_size,
        kernel_addr,
        ramdisk_size,
        ramdisk_addr,
        second_size,
        second_addr,
        tags_addr,
        page_size,
        dt_size,
        unused,
    ) = struct.unpack_from("<10I", image, 8)

    if page_size <= 0 or page_size > 65536:
        raise SystemExit(f"invalid page size: {page_size}")
    if second_size != 0:
        raise SystemExit("unexpected second stage; refusing to rewrite")
    if dt_size != 0:
        raise SystemExit("unexpected boot header DT payload; DTB should be appended to zImage")

    kernel_offset = page_size
    kernel = image[kernel_offset : kernel_offset + kernel_size]
    ramdisk_offset = align(kernel_offset + kernel_size, page_size)
    ramdisk = image[ramdisk_offset : ramdisk_offset + ramdisk_size]

    if len(kernel) != kernel_size or len(ramdisk) != ramdisk_size:
        raise SystemExit("boot image is truncated")

    try:
        raw_initramfs = lzma.decompress(ramdisk)
    except lzma.LZMAError as exc:
        raise SystemExit(f"ramdisk is not an XZ/LZMA stream: {exc}") from exc

    # Linux 4.9's early XZ decoder in this kernel accepts CRC32, not CRC64.
    # Never fall back to the original stream solely because it is smaller:
    # modern tools commonly emit CRC64, which makes PID 1 unreachable.
    recompressed = lzma.compress(
        raw_initramfs,
        format=lzma.FORMAT_XZ,
        check=lzma.CHECK_CRC32,
        preset=9,
    )

    header = bytearray(image[:page_size])
    struct.pack_into("<I", header, RAMDISK_SIZE_OFFSET, len(recompressed))
    header[ID_OFFSET : ID_OFFSET + ID_SIZE] = b"\0" * ID_SIZE

    # Android boot image v0 ID: SHA1(kernel + kernel_size + ramdisk +
    # ramdisk_size + second + second_size). The S10 image has no second stage.
    digest = hashlib.sha1()
    digest.update(kernel)
    digest.update(struct.pack("<I", kernel_size))
    digest.update(recompressed)
    digest.update(struct.pack("<I", len(recompressed)))
    digest.update(struct.pack("<I", 0))
    header[ID_OFFSET : ID_OFFSET + 20] = digest.digest()

    output = bytearray(header)
    output.extend(kernel)
    output.extend(b"\0" * (align(kernel_size, page_size) - kernel_size))
    output.extend(recompressed)
    output.extend(b"\0" * (align(len(recompressed), page_size) - len(recompressed)))

    # Verify that compression did not alter initramfs contents.
    check_offset = align(page_size + kernel_size, page_size)
    check_ramdisk = bytes(output[check_offset : check_offset + len(recompressed)])
    if lzma.decompress(check_ramdisk) != raw_initramfs:
        raise SystemExit("repacked initramfs verification failed")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)

    print(f"page_size={page_size}")
    print(f"kernel_size={kernel_size}")
    print(f"old_ramdisk_size={ramdisk_size}")
    print(f"new_ramdisk_size={len(recompressed)}")
    print("xz_check=crc32")
    print(f"old_boot_size={len(image)}")
    print(f"new_boot_size={len(output)}")
    print(f"sha256={hashlib.sha256(output).hexdigest()}")

    if args.limit and len(output) > args.limit:
        raise SystemExit(
            f"repacked boot.img is still too large: {len(output)} > {args.limit} bytes"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
