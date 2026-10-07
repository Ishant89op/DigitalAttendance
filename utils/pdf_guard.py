"""
Minimal PDF safety check for uploaded evidence.

Rejects PDFs that carry executable or smuggled content (JavaScript, launch
actions, embedded files, XFA forms, rich media). Stream *data* is skipped
when scanning, because compressed image bytes can contain sequences like
"/JS" by pure chance — except object streams (/Type /ObjStm), which hold
dictionaries and are decompressed and scanned, since that is exactly where
an attacker would hide an action.
"""

from __future__ import annotations

import re
import zlib

_ACTIVE_NAMES = (
    b"JavaScript", b"JS", b"Launch", b"EmbeddedFile", b"EmbeddedFiles",
    b"RichMedia", b"XFA", b"SubmitForm", b"ImportData", b"GoToE",
)
# A PDF name ends at whitespace or a delimiter.
_NAME_RE = re.compile(rb"/(" + b"|".join(_ACTIVE_NAMES) + rb")(?=[\s/<>\[\]()%{}]|$)")
_HEX_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
_MAX_INFLATED = 32 * 1024 * 1024


def _decode_names(data: bytes) -> bytes:
    """/J#61vaScript -> /JavaScript (PDF allows hex escapes inside names)."""
    return _HEX_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), data)


def _has_active_names(data: bytes) -> bool:
    return _NAME_RE.search(_decode_names(data)) is not None


def is_safe_pdf(content: bytes) -> bool:
    if not content.startswith(b"%PDF-"):
        return False
    if b"%%EOF" not in content[-2048:]:
        return False

    inflated_budget = _MAX_INFLATED
    outside_streams: list[bytes] = []
    pos = 0
    # Single linear pass: split the file into "dictionary/text" regions and
    # stream bodies (stream <EOL> ... endstream).
    while True:
        s = content.find(b"stream", pos)
        if s == -1:
            break
        if content[s - 3:s] == b"end":          # an 'endstream' we already passed
            pos = s + 6
            continue
        body_start = s + 6
        if content[body_start:body_start + 2] == b"\r\n":
            body_start += 2
        elif content[body_start:body_start + 1] in (b"\n", b"\r"):
            body_start += 1
        else:                                    # the word 'stream' inside text
            pos = s + 6
            continue
        body_end = content.find(b"endstream", body_start)
        if body_end == -1:
            return False                         # truncated / malformed

        outside_streams.append(content[pos:s])
        obj_start = content.rfind(b"obj", pos, s)
        header = _decode_names(content[obj_start if obj_start != -1 else max(pos, s - 4096):s])
        if b"/ObjStm" in header:
            if b"/FlateDecode" not in header:
                return False                     # unusual encoding for an object stream
            try:
                inflater = zlib.decompressobj()
                data = inflater.decompress(content[body_start:body_end], inflated_budget)
            except zlib.error:
                return False
            inflated_budget -= len(data)
            if inflated_budget <= 0 or inflater.unconsumed_tail:
                return False                     # decompression-bomb guard
            if _has_active_names(data):
                return False
        pos = body_end + len(b"endstream")
    outside_streams.append(content[pos:])
    return not _has_active_names(b"".join(outside_streams))
