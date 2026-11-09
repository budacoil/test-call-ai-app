"""Statically extract application bytecode from the downloaded PyInstaller release.

Run with CPython 3.12. No extracted module is imported or executed.
"""
from pathlib import Path
import dis
import hashlib
import importlib.util
import io
import json
import marshal
import struct
import sys
import types
import zlib

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "downloads/pk-auto-v2.0.0.exe"
EXPECTED_SHA256 = "988953c55ac2a9111eda53c896ea1ba630db3ceb23ec2ccaf4d267b0357e26d4"


def walk(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from walk(value)


def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use CPython 3.12 to read this release's bytecode")
    data = EXE.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit("Release SHA-256 mismatch")
    cookie_at = data.rfind(b"MEI\x0c\x0b\x0a\x0b\x0e")
    if cookie_at < 0:
        raise ValueError("PyInstaller cookie not found")
    _, package_size, toc_offset, toc_size, py_version, library = struct.unpack(
        "!8sIIII64s", data[cookie_at:cookie_at + 88]
    )
    if py_version != 312:
        raise ValueError("Unexpected packaged Python version")
    start = cookie_at + 88 - package_size
    cursor, end = start + toc_offset, start + toc_offset + toc_size
    entries, payloads = [], {}
    while cursor < end:
        length, offset, size, raw_size, compressed, kind = struct.unpack(
            "!iIIIBc", data[cursor:cursor + 18]
        )
        if length < 18 or cursor + length > end:
            raise ValueError("Invalid CArchive table entry")
        name = data[cursor + 18:cursor + length].rstrip(b"\0").decode("utf-8")
        cursor += length
        entries.append(dict(name=name, offset=offset, size=size,
                            uncompressed_size=raw_size, compressed=compressed,
                            type=kind.decode()))
        if kind in (b"s", b"z"):
            if not 0 <= offset <= toc_offset or offset + size > toc_offset:
                raise ValueError("Invalid CArchive payload bounds")
            value = data[start + offset:start + offset + size]
            value = zlib.decompress(value) if compressed else value
            if len(value) != raw_size:
                raise ValueError("Invalid payload length")
            payloads[name] = value

    pyz = payloads["PYZ.pyz"]
    if pyz[:4] != b"PYZ\0" or pyz[4:8] != importlib.util.MAGIC_NUMBER:
        raise ValueError("Unexpected PYZ bytecode magic")
    toc_at = struct.unpack("!i", pyz[8:12])[0]
    toc = dict(marshal.loads(pyz[toc_at:]))
    app = {"main": marshal.loads(payloads["main"])}
    for name, (kind, offset, length) in toc.items():
        if kind not in (0, 1):
            continue
        code = marshal.loads(zlib.decompress(pyz[offset:offset + length]))
        # Application-level modules use bare filenames. Exclude the standard
        # library, which may also have bare filenames in frozen builds.
        if (isinstance(code, types.CodeType) and "." not in name
                and name not in sys.stdlib_module_names
                and code.co_filename == name + ".py"):
            app[name] = code

    reports = ROOT / "reports"
    bytecode = ROOT / "bytecode"
    assembly = ROOT / "disassembly"
    for folder in (reports, bytecode, assembly):
        folder.mkdir(exist_ok=True)
    manifest = []
    for name, code in sorted(app.items()):
        header = pyz[4:8] + struct.pack("<III", 0, 0, 0)
        (bytecode / (name + ".pyc")).write_bytes(header + marshal.dumps(code))
        listing = io.StringIO()
        dis.dis(code, file=listing)
        (assembly / (name + ".dis.txt")).write_text(listing.getvalue(), encoding="utf-8")
        manifest.append(dict(module=name, original_filename=code.co_filename,
                             global_names=list(code.co_names),
                             functions=[dict(name=c.co_qualname, line=c.co_firstlineno)
                                        for c in walk(code) if c is not code]))
    (reports / "carchive.json").write_text(json.dumps(dict(
        python_version=py_version, python_library=library.rstrip(b"\0").decode(),
        entries=entries), indent=2), encoding="utf-8")
    (reports / "pyz-modules.json").write_text(json.dumps(toc, indent=2), encoding="utf-8")
    (reports / "application-modules.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary = dict(file=str(EXE), bytes=len(data), sha256=digest, python="3.12",
                   carchive_entries=len(entries), pyz_modules=len(toc),
                   application_modules=len(app),
                   pyarmor_module_names=[name for name in toc if "pyarmor" in name.lower()],
                   pyarmor_symbols=[name for name, code in app.items()
                                    if any("__pyarmor__" in c.co_names for c in walk(code))],
                   application_executed=False, readable_source_recovered=False)
    (reports / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
