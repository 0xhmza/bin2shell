from __future__ import annotations
import textwrap
from typing import Any, Dict, List, Tuple


REQUIRED_FIELDS = {
    "encoders": ["name", "index", "python_snippet", "cpp_inverse"],
    "envelopes": ["name", "index", "python_snippet", "cpp_decode"],
}


class Catalog:
    def __init__(self, y: Dict[str, Any]):
        self.y = y or {}
        self.encoders: Dict[int, Dict[str, Any]] = {}
        self.envelopes: Dict[int, Dict[str, Any]] = {}
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

    def list_block(self, block: str) -> List[Dict[str, Any]]:
        table = {
            "encoders": self.encoders,
            "envelopes": self.envelopes,
        }[block]
        return [table[i] for i in sorted(table.keys())]

    def default_index(self, block: str) -> int:
        table = {
            "encoders": self.encoders,
            "envelopes": self.envelopes,
        }[block]
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

    def _maybe_keys(self, spec: Dict[str, Any]) -> Dict[str, bytes]:
        if "keys_snippet" not in spec or not spec["keys_snippet"]:
            return {}
        gen_keys = self._exec_snippet(spec["keys_snippet"], "gen_keys", {})
        keys = gen_keys()
        if not isinstance(keys, dict):
            raise RuntimeError("gen_keys() must return dict[str, bytes]")
        return keys


    def run_encode(
        self, idx: int, data: bytes
    ) -> Tuple[bytes, Dict[str, bytes], Dict[str, Any], Dict[str, Any]]:
        spec = self.encoders.get(idx)
        if not spec:
            raise RuntimeError(f"Unknown encoder index '{idx}'")
        name = spec.get("name", "")
        if name.lower() == "none":
            return data, {}, {}, spec
        keys = self._maybe_keys(spec)
        encode = self._exec_snippet(spec["python_snippet"], "encode", {})
        out = encode(data, keys)
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
