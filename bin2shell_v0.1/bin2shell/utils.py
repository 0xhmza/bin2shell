from __future__ import annotations
import os
import shutil


def get_terminal_width() -> int:
    try:
        w = shutil.get_terminal_size(fallback=(0, 0)).columns
        if w and w > 0:
            return w
    except Exception:
        pass
    try:
        w = int(os.environ.get("COLUMNS", "0"))
        if w > 0:
            return w
    except Exception:
        pass
    return 80


def read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()

