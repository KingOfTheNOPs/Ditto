from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import time
from pathlib import Path


DEBUG_SECTION_NAMES = {
    ".debug",
    ".debug_abbrev",
    ".debug_addr",
    ".debug_aranges",
    ".debug_info",
    ".debug_line",
    ".debug_line_str",
    ".debug_loc",
    ".debug_loclists",
    ".debug_pubnames",
    ".debug_pubtypes",
    ".debug_ranges",
    ".debug_rnglists",
    ".debug_str",
    ".debug_str_offsets",
    ".zdebug_info",
    ".zdebug_line",
    ".zdebug_str",
    ".comment",
}

STRING_REPLACEMENTS = [
    (b"Mingw-w64 runtime failure:\n", "Runtime component message:\n"),
    (b"Address %p has no image-section", "Address %p region unavailable"),
    (b"  VirtualQuery failed for %d bytes at address %p", "  Memory query returned for %d bytes at addr %p"),
    (b"  VirtualProtect failed with code 0x%x", "  Memory protect returned status 0x%x"),
    (b"  Unknown pseudo relocation protocol version %d.\n", "  Runtime relocation protocol status code %d.\n"),
    (b"  Unknown pseudo relocation bit size %d.\n", "  Runtime relocation size code %d.\n"),
    (b"RUST_BACKTRACE", "TRACE_DISABLED"),
    (b"/rustc/", "/build/"),
    (b"ditto_native_host", "native_host_svc"),
    (b"Ditto Project", "Browser Core"),
    (b"Ditto Native Host", "Browser Host"),
]

DENYLIST = [
    b"Mingw-w64 runtime failure",
    b"RUST_BACKTRACE",
    b"/rustc/",
    b".debug_",
    b"Ditto Project",
    b"Ditto Native Host",
    b"Microsoft Corporation",
    b"DeviceHealthHost.exe",
    b"com.microsoft",
]


def find_optional_tool(candidates: list[str]) -> str:
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).exists():
            return candidate
    return ""


def _same_length(old: bytes, replacement: str) -> bytes:
    new = replacement.encode("ascii")
    if len(new) > len(old):
        raise ValueError(f"replacement for {old!r} is too long")
    return new.ljust(len(old), b" ")


def _run_tool(command: list[str], cwd: Path) -> tuple[bool, str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, output


def _pe_layout(data: bytes) -> dict:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("not a PE file")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError("invalid PE signature")
    file_header = pe_offset + 4
    section_count = struct.unpack_from("<H", data, file_header + 2)[0]
    optional_header_size = struct.unpack_from("<H", data, file_header + 16)[0]
    optional_header = file_header + 20
    section_table = optional_header + optional_header_size
    if section_table + (section_count * 40) > len(data):
        raise ValueError("invalid PE section table")
    return {
        "file_header": file_header,
        "section_count": section_count,
        "section_table": section_table,
    }


def _section_names(data: bytes) -> list[str]:
    layout = _pe_layout(data)
    names: list[str] = []
    for index in range(layout["section_count"]):
        offset = layout["section_table"] + (index * 40)
        raw = data[offset:offset + 8].split(b"\0", 1)[0]
        if not raw:
            continue
        try:
            names.append(raw.decode("ascii"))
        except UnicodeDecodeError:
            continue
    return names


def set_pe_timestamp(exe_path: Path, timestamp: int) -> int:
    data = bytearray(exe_path.read_bytes())
    layout = _pe_layout(data)
    timestamp = int(timestamp) & 0xFFFFFFFF
    struct.pack_into("<I", data, layout["file_header"] + 4, timestamp)
    exe_path.write_bytes(data)
    return timestamp


def trim_trailing_zero_overlay(exe_path: Path) -> int:
    data = exe_path.read_bytes()
    layout = _pe_layout(data)
    raw_end = 0
    for index in range(layout["section_count"]):
        offset = layout["section_table"] + (index * 40)
        raw_size = struct.unpack_from("<I", data, offset + 16)[0]
        raw_ptr = struct.unpack_from("<I", data, offset + 20)[0]
        if raw_ptr and raw_size:
            raw_end = max(raw_end, raw_ptr + raw_size)
    if raw_end <= 0 or raw_end >= len(data):
        return 0
    trimmed = data.rstrip(b"\0")
    if len(trimmed) < raw_end:
        trimmed = data[:raw_end]
    removed = len(data) - len(trimmed)
    if removed:
        exe_path.write_bytes(trimmed)
    return removed


def scrub_native_host_strings(exe_path: Path) -> dict:
    data = exe_path.read_bytes()
    patched = data
    hits: dict[str, int] = {}
    for old, replacement in STRING_REPLACEMENTS:
        count = patched.count(old)
        if not count:
            continue
        patched = patched.replace(old, _same_length(old, replacement))
        hits[old.decode("ascii", errors="replace")] = count
    if patched != data:
        exe_path.write_bytes(patched)
    return hits


def scan_denylist(exe_path: Path) -> dict:
    data = exe_path.read_bytes()
    hits: dict[str, int] = {}
    for needle in DENYLIST:
        count = data.count(needle)
        if count:
            hits[needle.decode("ascii", errors="replace")] = count
    return hits


def remove_debug_sections(exe_path: Path, objcopy_tool: str = "") -> dict:
    if not objcopy_tool:
        return {"removed": [], "tool": "", "error": "objcopy not available"}

    data = exe_path.read_bytes()
    existing = set(_section_names(data))
    remove_names = sorted(
        section
        for section in existing
        if section.startswith(".debug") or section.startswith(".zdebug") or section == ".comment"
    )
    for name in DEBUG_SECTION_NAMES:
        if name in existing:
            remove_names.append(name)
    remove_names = sorted(set(remove_names))
    if not remove_names:
        return {"removed": [], "tool": objcopy_tool, "error": ""}

    tmp_path = exe_path.with_suffix(exe_path.suffix + ".objcopy")
    command = [objcopy_tool]
    for name in remove_names:
        command.extend(["--remove-section", name])
    command.extend([str(exe_path), str(tmp_path)])
    ok, output = _run_tool(command, exe_path.parent)
    if not ok:
        if tmp_path.exists():
            tmp_path.unlink()
        return {"removed": [], "tool": objcopy_tool, "error": output.strip()}
    shutil.move(str(tmp_path), exe_path)
    return {"removed": remove_names, "tool": objcopy_tool, "error": ""}


def strip_debug_symbols(exe_path: Path, strip_tool: str = "") -> dict:
    if not strip_tool:
        return {"tool": "", "ok": False, "error": "strip not available"}
    ok, output = _run_tool([strip_tool, "--strip-debug", str(exe_path)], exe_path.parent)
    return {"tool": strip_tool, "ok": ok, "error": "" if ok else output.strip()}


def harden_native_host(
    exe_path: Path,
    *,
    strip_tool: str = "",
    objcopy_tool: str = "",
    timestamp: int | None = None,
) -> dict:
    exe_path = Path(exe_path)
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    before_size = exe_path.stat().st_size

    strip_report = strip_debug_symbols(exe_path, strip_tool)
    section_report = remove_debug_sections(exe_path, objcopy_tool)
    scrubbed = scrub_native_host_strings(exe_path)
    written_timestamp = set_pe_timestamp(exe_path, timestamp)
    trimmed_overlay = trim_trailing_zero_overlay(exe_path)
    denylist_hits = scan_denylist(exe_path)

    return {
        "before_size": before_size,
        "after_size": exe_path.stat().st_size,
        "strip": strip_report,
        "sections": section_report,
        "scrubbed_strings": scrubbed,
        "timestamp": written_timestamp,
        "trimmed_overlay": trimmed_overlay,
        "denylist_hits": denylist_hits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Harden a Windows native host PE before signing.")
    parser.add_argument("exe", type=Path)
    parser.add_argument("--strip-tool", default="")
    parser.add_argument("--objcopy-tool", default="")
    parser.add_argument("--timestamp", type=int, default=None)
    args = parser.parse_args()
    report = harden_native_host(
        args.exe,
        strip_tool=args.strip_tool,
        objcopy_tool=args.objcopy_tool,
        timestamp=args.timestamp,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
