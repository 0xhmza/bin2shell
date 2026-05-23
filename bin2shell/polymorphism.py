"""
Polymorphism layer for bin2shell-generated C++.

Goal: a different-looking source file each run, even with identical inputs.
The public contract is unchanged — the emitted source still exposes
``code_blob`` and ``code_blob_len`` at file scope so downstream consumers
(Washmachine, integrators) keep working — but internal symbol names,
ordering of independent declarations, and a sprinkling of harmless junk
code vary between runs.

Two knobs are surfaced:

* ``Polymorphism(seed=...)`` — fix the random sequence for reproducible
  builds (CI smoke tests, golden snapshots).
* ``Polymorphism(level=...)`` — 0 (off), 1 (rename internal symbols),
  2 (rename + reorder), 3 (rename + reorder + insert junk locals in the
  initializer lambda).

The renamer operates as a post-pass on the assembled C++ text: it
substitutes a whitelist of "internal" identifiers with run-unique
replacements. Identifiers that appear in the public ABI (``code_blob``,
``code_blob_len``) and library symbols (``new``, ``unsigned``, etc.)
are never renamed.
"""
from __future__ import annotations

import os
import random
import re
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Internal identifier names that the generator emits and that polymorphism
# is allowed to rewrite. Anything not in this set is left untouched.
#
# Public symbols (``code_blob``, ``code_blob_len``) are deliberately *not*
# here: they form the consumer-facing ABI of every generated file.
INTERNAL_SYMBOLS = (
    "enc_buf",
    "enc_len",
    "code_blob_text",
    "code_blob_text_len",
    "code_blob_expected",
    "code_blob_expected_len",
    "bin2shell_payload",
    "Bin2ShellPayload",
)


# Generated-key variable patterns: keys_snippet results land under these
# names in the YAML catalog (xor_key, xtea_key, tea_key, chacha_key/nonce, ...).
# Rather than enumerate them, polymorphism finds any identifier that ends
# in ``_key`` / ``_nonce`` / ``_iv`` / ``_salt`` and renames it consistently.
KEY_SUFFIX_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*?)(_key|_nonce|_iv|_salt|_round)\b")


_IDENT_CHARS = string.ascii_lowercase + string.digits


def _new_ident(rng: random.Random, prefix: str = "_v") -> str:
    """Generate a random C identifier that won't collide with C++ keywords.

    Always starts with an underscore so it never matches a keyword or
    Win32/CRT public symbol.
    """
    return prefix + "".join(rng.choices(_IDENT_CHARS, k=rng.randint(5, 8)))


@dataclass
class Polymorphism:
    """Configuration + helpers for per-run source-level diversification."""

    seed: Optional[int] = None
    level: int = 1
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        if self.seed is None:
            self.seed = int.from_bytes(os.urandom(8), "big")
        self.rng = random.Random(self.seed)

    # ── primitives consumed by carriers / encoders ──────────────────
    def random_bytes(self, n: int) -> bytes:
        """Deterministic per-instance random bytes (for keys etc.)."""
        return bytes(self.rng.randrange(256) for _ in range(n))

    def random_uint32(self) -> int:
        return self.rng.randrange(2**32)

    def choice(self, items):
        return self.rng.choice(items)

    # ── post-pass that rewrites internal identifiers ────────────────
    def rename_internals(self, source: str) -> str:
        """Rewrite known-internal identifiers to per-run random names.

        Preserves the public ``code_blob``/``code_blob_len`` symbols.
        Returns the original text unchanged when ``level == 0``.
        """
        if self.level <= 0:
            return source

        mapping: Dict[str, str] = {}
        for sym in INTERNAL_SYMBOLS:
            mapping[sym] = _new_ident(self.rng, prefix="_b")

        # Discover dynamic key/nonce/iv variables in the source so each
        # one gets a consistent fresh name. Walk in declaration order so
        # the rename is deterministic for a given seed.
        for match in KEY_SUFFIX_PATTERN.finditer(source):
            full = match.group(0)
            if full in mapping or full in INTERNAL_SYMBOLS:
                continue
            mapping[full] = _new_ident(self.rng, prefix="_k")
            mapping[f"{full}_len"] = mapping[full] + "_len"

        # Whole-word substitution, longest-first so foo_key_len isn't
        # nibbled by foo_key.
        for old in sorted(mapping.keys(), key=len, reverse=True):
            new = mapping[old]
            source = re.sub(rf"\b{re.escape(old)}\b", new, source)

        return source

    def header_banner(self) -> str:
        """Comment banner identifying the run (seed only — not the level).

        Polymorphism level isn't included because that's a build-time
        knob, while the seed alone is enough to reproduce the output.
        """
        return f"// bin2shell — generated with seed {self.seed:#018x}\n"
