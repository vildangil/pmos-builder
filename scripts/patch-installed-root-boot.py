#!/usr/bin/env python3
"""Build an S10 debug boot image for an already-installed postmarketOS rootfs.

The Huawei MediaPad 10 FHD has an 8 MiB boot partition. This tool starts from a
known-good pmbootstrap Android boot v0 image, optionally replaces its kernel,
patches the embedded initramfs for headless/OpenRC diagnostics, forces an
installed rootfs UUID in the kernel command line, recompresses XZ with CRC32,
and validates the final partition size.
"""
from __future__ import annotations

import argparse
import hashlib
import lzma
import stat
import struct
from dataclasses import dataclass
from pathlib import Path

ANDROID_MAGIC = b"ANDROID!"
ID_OFFSET = 576
ID_SIZE = 32
CMDLINE_OFFSET = 64
CMDLINE_SIZE = 512
EXTRA_CMDLINE_OFFSET = 608
EXTRA_CMDLINE_SIZE = 1024
RAMDISK_SIZE_OFFSET = 16
NEWC_MAGIC = b"070701"
NEWC_HEADER = 110

TRACE_HOOK = r'''#!/bin/busybox ash
# Installed by patch-installed-root-boot.py. Runs immediately before switch_root.
klog() {
    [ -w /dev/kmsg ] || return 0
    printf '<6>PMOS-TRACE: %s\n' "$*" > /dev/kmsg
}

klog "initramfs cleanup reached; preparing OpenRC trace"
if [ ! -d /sysroot/etc ]; then
    klog "ERROR: /sysroot/etc missing before switch_root"
    exit 0
fi

root_line="$(awk '$2 == "/sysroot" { print $1 ":" $3 ":" $4; exit }' /proc/mounts 2>/dev/null || true)"
[ -n "$root_line" ] || root_line="?"
klog "sysroot=$root_line"

if [ -e /sysroot/sbin/init ]; then
    init_target="$(readlink /sysroot/sbin/init 2>/dev/null || true)"
    [ -n "$init_target" ] || init_target="regular-file"
    klog "rootfs /sbin/init=$init_target"
else
    klog "ERROR: rootfs /sbin/init missing"
fi

if [ -r /sysroot/etc/inittab ]; then
    while IFS= read -r line; do
        case "$line" in ''|'#'*) continue ;; esac
        klog "inittab: $line"
    done < /sysroot/etc/inittab
else
    klog "WARNING: rootfs /etc/inittab missing"
fi

mkdir -p /sysroot/etc/init.d /sysroot/etc/runlevels/sysinit /sysroot/etc/runlevels/boot /sysroot/etc/runlevels/default

write_trace() {
    phase="$1"
    cat > "/sysroot/etc/init.d/pmos-trace-$phase" <<EOF
#!/sbin/openrc-run
description="Huawei S10 OpenRC $phase trace"
start() {
    uptime="\$(cut -d ' ' -f 1 /proc/uptime 2>/dev/null || true)"
    pid1="\$(tr '\\0' ' ' </proc/1/cmdline 2>/dev/null || true)"
    rootfs="\$(awk '\$2 == "/" { print \$1 ":" \$3; exit }' /proc/mounts 2>/dev/null || true)"
    [ -n "\$uptime" ] || uptime="?"
    [ -n "\$pid1" ] || pid1="?"
    [ -n "\$rootfs" ] || rootfs="?"
    [ -w /dev/kmsg ] && printf '<6>PMOS-TRACE: openrc $phase reached uptime=%s pid1="%s" root=%s\\n' "\$uptime" "\$pid1" "\$rootfs" > /dev/kmsg
    return 0
}
EOF
    chmod 0755 "/sysroot/etc/init.d/pmos-trace-$phase"
    ln -sf "/etc/init.d/pmos-trace-$phase" "/sysroot/etc/runlevels/$phase/pmos-trace-$phase"
}

write_trace sysinit
write_trace boot
write_trace default
sync
klog "OpenRC trace installed into rootfs"
'''.encode()

@dataclass
class CpioEntry:
    name: str
    fields: list[int]
    data: bytes


def align4(n: int) -> int:
    return (n + 3) & ~3


def parse_newc(blob: bytes) -> list[CpioEntry]:
    entries: list[CpioEntry] = []
    off = 0
    while True:
        if blob[off:off+6] != NEWC_MAGIC:
            raise ValueError(f"invalid newc magic at offset {off}")
        h = blob[off:off+NEWC_HEADER]
        fields = [int(h[6+i*8:14+i*8], 16) for i in range(13)]
        namesize = fields[11]
        filesize = fields[6]
        name_start = off + NEWC_HEADER
        name_raw = blob[name_start:name_start+namesize]
        if len(name_raw) != namesize or not name_raw.endswith(b"\0"):
            raise ValueError("invalid newc filename")
        name = name_raw[:-1].decode("utf-8", "surrogateescape")
        data_start = align4(name_start + namesize)
        data = blob[data_start:data_start+filesize]
        if len(data) != filesize:
            raise ValueError("truncated newc entry")
        entries.append(CpioEntry(name, fields, data))
        off = align4(data_start + filesize)
        if name == "TRAILER!!!":
            break
    return entries


def encode_entry(e: CpioEntry) -> bytes:
    name = e.name.encode("utf-8", "surrogateescape") + b"\0"
    f = list(e.fields)
    f[6] = len(e.data)
    f[11] = len(name)
    header = NEWC_MAGIC + b"".join(f"{x:08x}".encode() for x in f)
    out = bytearray(header)
    out += name
    out += b"\0" * (align4(len(out)) - len(out))
    out += e.data
    out += b"\0" * (align4(len(out)) - len(out))
    return bytes(out)


def make_regular(name: str, data: bytes, mode: int = 0o755, ino: int = 0x7f000001) -> CpioEntry:
    fields = [ino, stat.S_IFREG | mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name.encode()) + 1, 0]
    return CpioEntry(name, fields, data)


def patch_initramfs(raw: bytes, *, no_framebuffer: bool, openrc_trace: bool) -> bytes:
    entries = parse_newc(raw)
    trailer = entries.pop()

    if no_framebuffer:
        target = "usr/share/deviceinfo/device-huawei-s10-101x"
        found = False
        for e in entries:
            if e.name != target:
                continue
            text = e.data.decode()
            if 'deviceinfo_no_framebuffer=' not in text:
                needle = 'deviceinfo_drm="false"\n'
                if needle not in text:
                    raise ValueError(f"{target}: deviceinfo_drm marker not found")
                text = text.replace(needle, needle + '# Headless bring-up: do not wait for /dev/fb0.\ndeviceinfo_no_framebuffer="true"\n', 1)
                e.data = text.encode()
            found = True
            break
        if not found:
            raise ValueError(f"{target} not found in initramfs")

    if openrc_trace:
        hook_name = "hooks-cleanup/99-s10-openrc-trace.sh"
        entries = [e for e in entries if e.name != hook_name]
        entries.append(make_regular(hook_name, TRACE_HOOK))

    trailer.data = b""
    out = bytearray()
    for e in entries:
        out += encode_entry(e)
    out += encode_entry(trailer)
    out += b"\0" * ((512 - len(out) % 512) % 512)
    return bytes(out)


def get_cmdline(header: bytes) -> str:
    raw = header[CMDLINE_OFFSET:CMDLINE_OFFSET+CMDLINE_SIZE] + header[EXTRA_CMDLINE_OFFSET:EXTRA_CMDLINE_OFFSET+EXTRA_CMDLINE_SIZE]
    return raw.split(b"\0", 1)[0].decode("ascii", "strict")


def set_cmdline(header: bytearray, cmdline: str) -> None:
    raw = cmdline.encode("ascii")
    if len(raw) >= CMDLINE_SIZE + EXTRA_CMDLINE_SIZE:
        raise ValueError("kernel cmdline is too long for Android boot v0 header")
    header[CMDLINE_OFFSET:CMDLINE_OFFSET+CMDLINE_SIZE] = b"\0" * CMDLINE_SIZE
    header[EXTRA_CMDLINE_OFFSET:EXTRA_CMDLINE_OFFSET+EXTRA_CMDLINE_SIZE] = b"\0" * EXTRA_CMDLINE_SIZE
    first = raw[:CMDLINE_SIZE]
    extra = raw[CMDLINE_SIZE:]
    header[CMDLINE_OFFSET:CMDLINE_OFFSET+len(first)] = first
    header[EXTRA_CMDLINE_OFFSET:EXTRA_CMDLINE_OFFSET+len(extra)] = extra


def replace_arg(cmdline: str, key: str, value: str | None) -> str:
    parts = [x for x in cmdline.split() if x != key and not x.startswith(key + "=")]
    if value is not None:
        parts.append(f"{key}={value}")
    else:
        parts.append(key)
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_boot", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--kernel", type=Path, help="replacement zImage or zImage-dtb")
    ap.add_argument("--root-uuid", help="UUID of the already-installed pmOS rootfs")
    ap.add_argument("--rootfsopts", default=None)
    ap.add_argument("--single-cpu", action="store_true")
    ap.add_argument("--no-framebuffer", action="store_true")
    ap.add_argument("--openrc-trace", action="store_true")
    ap.add_argument("--limit", type=int, default=8 * 1024 * 1024)
    args = ap.parse_args()

    image = args.base_boot.read_bytes()
    if image[:8] != ANDROID_MAGIC:
        raise SystemExit("not an Android boot v0 image")

    kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size, second_addr, tags_addr, page_size, dt_size, unused = struct.unpack_from("<10I", image, 8)
    if second_size or dt_size:
        raise SystemExit("unexpected second/dt payload")

    def align(n: int) -> int:
        return (n + page_size - 1) // page_size * page_size

    old_kernel = image[page_size:page_size+kernel_size]
    ramdisk_offset = align(page_size + kernel_size)
    old_ramdisk = image[ramdisk_offset:ramdisk_offset+ramdisk_size]
    kernel = args.kernel.read_bytes() if args.kernel else old_kernel

    try:
        raw_initramfs = lzma.decompress(old_ramdisk)
    except lzma.LZMAError as exc:
        raise SystemExit(f"ramdisk is not XZ/LZMA: {exc}") from exc

    if args.no_framebuffer or args.openrc_trace:
        raw_initramfs = patch_initramfs(raw_initramfs, no_framebuffer=args.no_framebuffer, openrc_trace=args.openrc_trace)

    ramdisk = lzma.compress(raw_initramfs, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=9)

    header = bytearray(image[:page_size])
    struct.pack_into("<I", header, 8, len(kernel))
    struct.pack_into("<I", header, RAMDISK_SIZE_OFFSET, len(ramdisk))

    cmdline = get_cmdline(header)
    if args.root_uuid:
        cmdline = replace_arg(cmdline, "pmos_root_uuid", args.root_uuid)
    if args.rootfsopts:
        cmdline = replace_arg(cmdline, "pmos_rootfsopts", args.rootfsopts)
    if args.single_cpu:
        cmdline = replace_arg(cmdline, "nosmp", None)
        cmdline = replace_arg(cmdline, "maxcpus", "1")
    set_cmdline(header, cmdline)

    header[ID_OFFSET:ID_OFFSET+ID_SIZE] = b"\0" * ID_SIZE
    digest = hashlib.sha1()
    digest.update(kernel)
    digest.update(struct.pack("<I", len(kernel)))
    digest.update(ramdisk)
    digest.update(struct.pack("<I", len(ramdisk)))
    digest.update(struct.pack("<I", 0))
    header[ID_OFFSET:ID_OFFSET+20] = digest.digest()

    output = bytearray(header)
    output += kernel
    output += b"\0" * (align(len(kernel)) - len(kernel))
    output += ramdisk
    output += b"\0" * (align(len(ramdisk)) - len(ramdisk))

    if lzma.decompress(ramdisk) != raw_initramfs:
        raise SystemExit("initramfs verification failed")
    if args.limit and len(output) > args.limit:
        raise SystemExit(f"boot image too large: {len(output)} > {args.limit}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(f"kernel_size={len(kernel)}")
    print(f"ramdisk_size={len(ramdisk)}")
    print(f"boot_size={len(output)}")
    print(f"boot_limit={args.limit}")
    print(f"boot_free={args.limit-len(output) if args.limit else -1}")
    print("xz_check=crc32")
    print(f"cmdline={cmdline}")
    print(f"sha1_id={digest.hexdigest()}")
    print(f"sha256={hashlib.sha256(output).hexdigest()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
