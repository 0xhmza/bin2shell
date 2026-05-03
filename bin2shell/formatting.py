from __future__ import annotations
from typing import Any, Dict


def make_c_array(name: str, buf: bytes, term_width: int) -> str:
    head = f"unsigned char {name}[] = {{ "
    tail = "};\n"
    indent = "  "
    lines, line, col = [], head, len(head)

    def push(tok: str):
        nonlocal line, col
        if col + len(tok) > term_width:
            lines.append(line.rstrip())
            line = indent + tok
            col = len(indent) + len(tok)
        else:
            line += tok
            col += len(tok)

    for i, b in enumerate(buf):
        tok = f"0x{b:02x}"
        tok += ", " if i + 1 < len(buf) else " "
        push(tok)
    lines.append(line.rstrip())
    return "\n".join(lines) + "\n" + tail


def make_len_var(name: str, n: int) -> str:
    return f"unsigned int {name}_len = {n};\n"


def _c_string_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append("\\\"")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


# Escaped-content size beyond which chunked static arrays are emitted to avoid
# MSVC C1060 (compiler out of heap space) from string-literal concatenation.
_CHUNK_THRESHOLD = 65_000
_CHUNK_SIZE      = 16_000


def _split_esc_chunks(esc: str, chunk_size: int) -> "list[str]":
    """Split *esc* into segments of at most *chunk_size* chars without breaking
    in the middle of a backslash escape sequence."""
    chunks: "list[str]" = []
    i = 0
    while i < len(esc):
        end = min(i + chunk_size, len(esc))
        while end > i + 1 and end < len(esc) and esc[end - 1] == '\\':
            end -= 1
        chunks.append(esc[i:end])
        i = end
    return chunks


def make_c_bstring(name: str, s: str, term_width: int) -> str:
    esc = _c_string_escape(s)
    max_seg = max(32, term_width - 4)

    if len(esc) <= _CHUNK_THRESHOLD:
        # Small payload: standard multi-line string literal approach.
        parts: "list[str]" = []
        i = 0
        while i < len(esc):
            end = min(i + max_seg, len(esc))
            # Avoid splitting in the middle of an escape sequence (e.g., \", \\, \n)
            while end > i and esc[end - 1] == '\\':
                end -= 1
            if end == i:
                # Edge case: segment is all backslashes; include at least one
                end = min(i + max_seg, len(esc))
            parts.append(esc[i:end])
            i = end
        body = "\n".join(f'"{p}"' for p in parts)
        return f"const char {name}[] = \n{body}\n;\n"

    # Large payload: emit individually-declared static chunk arrays assembled at
    # static-init time.  This avoids MSVC C1060 which exhausts compiler heap
    # when concatenating tens-of-thousands of string literal tokens.
    chunks = _split_esc_chunks(esc, _CHUNK_SIZE)
    lines: "list[str]" = []
    for ci, chunk in enumerate(chunks):
        lines.append(f'static const char __{name}_chunk{ci}[] = "{chunk}";')
    lines.append(f'static char {name}[{len(esc) + 1}];')
    refs  = ", ".join(f"__{name}_chunk{i}" for i in range(len(chunks)))
    sizes = ", ".join(str(len(c)) for c in chunks)
    lines.append(f'static const char* const __{name}_chunks[] = {{ {refs} }};')
    lines.append(f'static const int __{name}_chunk_sizes[] = {{ {sizes} }};')
    lines.append(f'static bool __{name}_init = ([](){{')
    lines.append(f'    int __p = 0;')
    lines.append(f'    for (int __c = 0; __c < {len(chunks)}; ++__c)')
    lines.append(f'        for (int __i = 0; __i < __{name}_chunk_sizes[__c]; ++__i)')
    lines.append(f'            {name}[__p++] = __{name}_chunks[__c][__i];')
    lines.append(f"    {name}[{len(esc)}] = '\\0';")
    lines.append(f'    return true;')
    lines.append(f'}})();')
    return "\n".join(lines) + "\n"


def safe_format_cpp(template: str, ctx: Dict[str, Any]) -> str:
    if not ctx:
        return template.replace("{", "{{").replace("}", "}}").format()

    protected = template
    sentinels = {}
    for k in sorted(ctx.keys(), key=len, reverse=True):
        ph = "{" + k + "}"
        token = f"<<PH_{k}>>"
        sentinels[token] = ph
        protected = protected.replace(ph, token)

    escaped = protected.replace("{", "{{").replace("}", "}}")

    for token, ph in sentinels.items():
        escaped = escaped.replace(token, ph)

    return escaped.format(**ctx)

