from __future__ import annotations
import hashlib
import secrets
import struct
import textwrap
from typing import Any, Dict, List, Optional, Tuple


# Bounds for a user-supplied key string. The key is a human-readable string;
# per-algorithm key material is derived from it with SHA-256, so any length in
# this range works for every keyed encoder. An empty/blank key means "generate
# a random one".
KEY_MIN_LENGTH = 1
KEY_MAX_LENGTH = 64
_RANDOM_KEY_BYTES = 24  # secrets.token_urlsafe(24) -> 32 characters


def validate_user_key(user_key: Any) -> Optional[str]:
    """Normalize a user-supplied key string.

    Returns the key string when provided and valid, ``None`` when no key was
    given (``None``/blank), and raises :class:`ValueError` when the key falls
    outside the allowed length bounds.
    """
    if user_key is None:
        return None
    key_str = str(user_key)
    if not key_str.strip():
        return None
    n = len(key_str)
    if n < KEY_MIN_LENGTH:
        raise ValueError(f"key is too short ({n} character(s); minimum {KEY_MIN_LENGTH})")
    if n > KEY_MAX_LENGTH:
        raise ValueError(f"key is too long ({n} characters; maximum {KEY_MAX_LENGTH})")
    return key_str


def _derive_key_material(key_str: str, parts: List[Tuple[str, int]]) -> Dict[str, bytes]:
    """Derive deterministic, length-exact key bytes for each requested part.

    Uses SHA-256 in a per-name counter block so every algorithm receives
    exactly the byte length it needs regardless of the input key length.
    """
    seed = key_str.encode("utf-8")
    result: Dict[str, bytes] = {}
    for name, length in parts:
        out = bytearray()
        counter = 0
        while len(out) < length:
            block = hashlib.sha256(
                seed + name.encode("utf-8") + struct.pack(">I", counter)
            ).digest()
            out += block
            counter += 1
        result[name] = bytes(out[:length])
    return result


REQUIRED_FIELDS = {
    "encoders": ["name", "index", "python_snippet", "cpp_inverse"],
    "envelopes": ["name", "index", "python_snippet", "cpp_decode"],
    "web_helpers": ["name", "index", "cpp_includes", "cpp_fetch_bytes", "cpp_fetch_text"],
}


class Playbook:
    def __init__(self, y: Dict[str, Any]):
        self.y = y or {}
        self.encoders: Dict[int, Dict[str, Any]] = {}
        self.envelopes: Dict[int, Dict[str, Any]] = {}
        self.web_helpers: Dict[int, Dict[str, Any]] = {}
        self._validate_and_index()

    def _require_list(self, key: str) -> List[Dict[str, Any]]:
        v = self.y.get(key)
        if not isinstance(v, list):
            raise ValueError(f"YAML error: top-level '{key}' must be a list")
        return v

    def _validate_block(self, block_name: str, items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        req = REQUIRED_FIELDS[block_name]
        by_idx: Dict[int, Dict[str, Any]] = {}
        seen_names: set[str] = set()
        for i, spec in enumerate(items, 1):
            if not isinstance(spec, dict):
                raise ValueError(f"YAML error: '{block_name}[{i}]' must be an object")
            missing = [k for k in req if k not in spec]
            if missing:
                raise ValueError(
                    f"YAML error: '{block_name}[{i}]' missing fields: {', '.join(missing)}"
                )
            name = spec["name"]
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"YAML error: '{block_name}[{i}]' field 'name' must be a non-empty string"
                )
            if name in seen_names:
                raise ValueError(f"YAML error: duplicate name '{name}' in '{block_name}'")
            seen_names.add(name)
            idx = spec["index"]
            if not isinstance(idx, int) or idx < 0:
                raise ValueError(
                    f"YAML error: '{block_name}[{i}]' field 'index' must be an integer >= 0"
                )
            if idx in by_idx:
                prev = by_idx[idx]["name"]
                raise ValueError(
                    f"YAML error: duplicate index {idx} in '{block_name}' (used by '{prev}' and '{name}')"
                )
            for k in req:
                if k.endswith("_snippet") or k.startswith("cpp_"):
                    if not isinstance(spec[k], str) or not spec[k].strip():
                        raise ValueError(
                            f"YAML error: '{block_name}[{i}]' field '{k}' must be a non-empty string"
                        )
            by_idx[idx] = spec
        if not by_idx:
            raise ValueError(f"YAML error: '{block_name}' must contain at least one entry")
        return by_idx

    def _validate_and_index(self) -> None:
        encs = self._require_list("encoders")
        envs = self._require_list("envelopes")

        self.encoders = self._validate_block("encoders", encs)
        self.envelopes = self._validate_block("envelopes", envs)

        web = self.y.get("web_helpers")
        if isinstance(web, list) and web:
            self.web_helpers = self._validate_block("web_helpers", web)

    def _block_table(self, block: str) -> Dict[int, Dict[str, Any]]:
        return {
            "encoders": self.encoders,
            "envelopes": self.envelopes,
            "web_helpers": self.web_helpers,
        }[block]

    def list_block(self, block: str) -> List[Dict[str, Any]]:
        table = self._block_table(block)
        return [table[i] for i in sorted(table.keys())]

    def default_index(self, block: str) -> int:
        table = self._block_table(block)
        if not table:
            return 0
        return min(table.keys())

    @staticmethod
    def _exec_snippet(snippet: str, symbol_name: str, inject: Dict[str, Any]) -> Any:
        loc: Dict[str, Any] = {}
        loc.update(inject or {})
        code = textwrap.dedent(snippet)
        exec(code, loc, loc)
        if symbol_name not in loc:
            raise RuntimeError(f"Snippet did not define {symbol_name}")
        return loc[symbol_name]

    def _resolve_keys(self, spec: Dict[str, Any], user_key: Any) -> Dict[str, bytes]:
        """Resolve an encoder's key material from its ``key`` declaration.

        ``key`` is an optional list of ``{name, length}`` entries describing
        the key arrays the encoder's C++ inverse expects. When the user
        supplied a key string it is validated and used to derive exact-length
        bytes; otherwise a fresh random key is generated.
        """
        key_spec = spec.get("key")
        if not key_spec:
            return {}
        if not isinstance(key_spec, list) or not key_spec:
            raise RuntimeError(
                "encoder 'key' must be a non-empty list of {name, length} entries"
            )
        parts: List[Tuple[str, int]] = []
        seen: set = set()
        for entry in key_spec:
            if not isinstance(entry, dict):
                raise RuntimeError(
                    "encoder 'key' entries must be objects with 'name' and 'length'"
                )
            name = entry.get("name")
            length = entry.get("length")
            if not isinstance(name, str) or not name:
                raise RuntimeError("encoder 'key' entry 'name' must be a non-empty string")
            if name in seen:
                raise RuntimeError(f"encoder 'key' duplicate name '{name}'")
            seen.add(name)
            if isinstance(length, bool) or not isinstance(length, int) or not (1 <= length <= 256):
                raise RuntimeError(
                    f"encoder 'key' entry '{name}' length must be an integer 1..256"
                )
            parts.append((name, length))
        key_str = validate_user_key(user_key)
        if key_str is None:
            key_str = secrets.token_urlsafe(_RANDOM_KEY_BYTES)
        return _derive_key_material(key_str, parts)


    def run_encode(
        self, idx: int, data: bytes, user_key: Any = None
    ) -> Tuple[bytes, Dict[str, bytes], Dict[str, Any], Dict[str, Any]]:
        spec = self.encoders.get(idx)
        if not spec:
            raise RuntimeError(f"Unknown encoder index '{idx}'")
        name = spec.get("name", "")
        if name.lower() in ("none", "passthrough"):
            return data, {}, {}, spec
        keys = self._resolve_keys(spec, user_key)
        encode = self._exec_snippet(spec["python_snippet"], "encode", {})
        # Call encode with keys only if a key declaration was present; otherwise
        # let the snippet use its default key parameter.
        if keys:
            out = encode(data, keys)
        else:
            out = encode(data)
        if not isinstance(out, (bytes, bytearray)):
            raise RuntimeError("encode() must return bytes")
        emit = spec.get("emit", {})
        return bytes(out), keys, emit, spec

    def run_envelope(self, idx: int, data: bytes) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        spec = self.envelopes.get(idx)
        if not spec:
            raise RuntimeError(f"Unknown envelope index '{idx}'")
        envelope_fn = self._exec_snippet(spec["python_snippet"], "envelope", {})
        text = envelope_fn(data)
        if not isinstance(text, str):
            raise RuntimeError("envelope() must return str")
        emit = spec.get("emit", {})
        return text, emit, spec
