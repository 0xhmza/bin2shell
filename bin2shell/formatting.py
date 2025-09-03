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
        else:
            out.append(ch)
    return "".join(out)


def make_c_bstring(name: str, s: str, term_width: int) -> str:
    esc = _c_string_escape(s)
    max_seg = max(32, term_width - 4)
    parts = [esc[i:i + max_seg] for i in range(0, len(esc), max_seg)]
    body = "\n".join(f"\"{p}\"" for p in parts)
    return f"const char {name}[] = \n{body}\n;\n"


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

