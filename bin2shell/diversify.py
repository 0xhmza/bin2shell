"""
Source diversification for bin2shell-generated C++.

Goal: a different-looking source file each run, even with identical inputs.
The public contract is unchanged — the emitted source still exposes
``code_blob`` and ``code_blob_len`` at file scope so downstream consumers
(Washmachine, integrators) keep working — but internal symbol names,
ordering of independent declarations, and a sprinkling of harmless junk
code vary between runs.

Two knobs are surfaced:

* ``Diversifier(seed=...)`` — fix the random sequence for reproducible
  builds (CI smoke tests, golden snapshots).
* ``Diversifier(level=...)`` — 0 (off), 1 (rename internal symbols),
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
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Internal identifier names that the generator emits and that the diversifier
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
# names in the YAML playbook (xor_key, xtea_key, tea_key, chacha_key/nonce, ...).
# Rather than enumerate them, the diversifier finds any identifier that ends
# in ``_key`` / ``_nonce`` / ``_iv`` / ``_salt`` and renames it consistently.
KEY_SUFFIX_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*?)(_key|_nonce|_iv|_salt|_round)\b")


_TECHNICAL_WORDS = (
    "buffer", "context", "handle", "stream", "offset", "segment", "frame",
    "token", "cursor", "index", "counter", "state", "cache", "node", "entry",
    "slot", "chunk", "block", "queue", "stack", "depth", "stride", "margin",
    "layer", "filter", "vertex", "sample", "region", "extent", "phase",
    "epoch", "batch", "pivot", "delta", "threshold", "capacity", "weight",
    "interval", "timeout", "channel", "socket", "packet", "header", "field",
    "record", "column", "digest", "seed", "vector", "scalar", "tensor",
    "matrix", "kernel", "module", "driver", "adapter", "bridge", "proxy",
    "factory", "builder", "parser", "scanner", "lexer", "mapper", "reducer",
    "visitor", "handler", "emitter", "decoder", "encoder", "resolver",
    "provider", "manager", "tracker", "monitor", "watcher", "listener",
    "dispatch", "pipeline", "sequence", "iterator", "allocator", "layout",
    "section", "surface", "texture", "sampler", "viewport", "canvas",
    "polygon", "contour", "gradient", "palette", "density", "volume",
    "cluster", "anchor", "origin", "target", "source", "result", "output",
    "metric", "signal", "fence", "barrier", "mutex", "spinlock", "hazard",
    "fiber", "thread", "worker", "slab", "arena", "pool", "bucket",
    "register", "opcode", "operand", "literal", "constant", "binding",
)

_IDENT_STYLES = (
    lambda words: "_".join(words),                         # snake_case
    lambda words: words[0] + "".join(w.title() for w in words[1:]),  # camelCase
)


def _new_ident(rng: random.Random, prefix: str = "_", seen: Optional[set] = None) -> str:
    """Generate a random C identifier from technical English words.

    Produces names like ``buffer_context``, ``_streamOffset``, etc.
    that blend in with real source while remaining collision-free.
    """
    for _ in range(50):
        n = rng.randint(1, 2)
        words = rng.sample(_TECHNICAL_WORDS, k=n)
        style = rng.choice(_IDENT_STYLES)
        name = style(words)
        if prefix and not name.startswith("_"):
            name = prefix + name
        if seen is None or name not in seen:
            if seen is not None:
                seen.add(name)
            return name
    return prefix + "fallback" + str(rng.randint(1000, 9999))


@dataclass
class Diversifier:
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

        seen: set = set()
        mapping: Dict[str, str] = {}
        for sym in INTERNAL_SYMBOLS:
            mapping[sym] = _new_ident(self.rng, prefix="_", seen=seen)

        # Discover dynamic key/nonce/iv variables in the source so each
        # one gets a consistent fresh name. Walk in declaration order so
        # the rename is deterministic for a given seed.
        for match in KEY_SUFFIX_PATTERN.finditer(source):
            full = match.group(0)
            if full in mapping or full in INTERNAL_SYMBOLS:
                continue
            mapping[full] = _new_ident(self.rng, prefix="_", seen=seen)
            mapping[f"{full}_len"] = mapping[full] + "_len"

        # Whole-word substitution, longest-first so foo_key_len isn't
        # nibbled by foo_key.
        for old in sorted(mapping.keys(), key=len, reverse=True):
            new = mapping[old]
            source = re.sub(rf"\b{re.escape(old)}\b", new, source)

        return source

    def header_banner(self) -> str:
        """Comment banner identifying the run (seed only — not the level).

        The diversification level isn't included because that's a build-time
        knob, while the seed alone is enough to reproduce the output.
        """
        return f"// bin2shell — generated with seed {self.seed:#018x}\n"
