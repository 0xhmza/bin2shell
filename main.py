#!/usr/bin/env python3
from __future__ import annotations
import sys

# Thin entrypoint to the packaged CLI. Keep main.py minimalistic.
from bin2shell.cli import main as _main


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
