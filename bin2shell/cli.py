from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml  # PyYAML
except ImportError:
    sys.stderr.write("Error: PyYAML is required. Install with: pip install pyyaml\n")
    raise

from .catalog import Catalog
from .formatting import make_c_array, make_c_bstring, make_len_var, safe_format_cpp
from .helptext import print_dynamic_help
from .utils import get_terminal_width, read_file


DEFAULT_YAML_REL = os.path.join("data", "yaml", "algos.yaml")
PLACEHOLDER_TOKEN = "__PAYLOAD_PLACEHOLDER__"


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _block_scalar(name: str, value: str) -> str:
    normalized = _normalize_newlines(value)
    has_trailing_newline = normalized.endswith("\n")
    content = normalized.rstrip("\n")
    chomp = "|" if has_trailing_newline else "|-"
    lines = content.split("\n") if content else []
    block = [f"{name}: {chomp}"]
    if not lines:
        block.append("  ")
    else:
        block.extend(f"  {line}" for line in lines)
    return "\n".join(block)


class CLIError(Exception):
    """Raised for controlled CLI failures."""


@dataclass
class Section:
    kind: str
    meta: Dict[str, Any]


@dataclass
class CLIArgs:
    input_path: str
    yaml_override: Optional[str]
    encoder_index: Optional[int]
    envelope_index: Optional[int]
    web_mode: bool


@dataclass
class GenerationContext:
    sections: List[Section]
    payload_bytes: Optional[bytes]
    payload_text: Optional[str]
    options_meta: Dict[str, Any]


def _make_placeholder_array(name: str, placeholder: str) -> str:
    return f"unsigned char {name}[] = {{ /* {placeholder} */ }};\n"


def _render_sections(
    sections: Iterable[Section],
    web_mode: bool,
    term_width: int,
    placeholder: str,
) -> str:
    chunks: List[str] = []
    for section in sections:
        meta = section.meta
        if section.kind == "array":
            chunks.append(make_c_array(meta["name"], meta["data"], term_width))
        elif section.kind == "payload_array":
            if web_mode:
                chunks.append(_make_placeholder_array(meta["name"], placeholder))
            else:
                chunks.append(make_c_array(meta["name"], meta["data"], term_width))
        elif section.kind == "string":
            chunks.append(make_c_bstring(meta["name"], meta["text"], term_width))
        elif section.kind == "payload_string":
            if web_mode:
                chunks.append(make_c_bstring(meta["name"], placeholder, term_width))
            else:
                chunks.append(make_c_bstring(meta["name"], meta["text"], term_width))
        elif section.kind == "len_var":
            chunks.append(make_len_var(meta["name"], meta["value"]))
        elif section.kind == "len_literal":
            chunks.append(f"unsigned int {meta['name']} = {meta['value']};\n")
        elif section.kind == "raw":
            chunks.append(meta.get("text", ""))
        else:
            raise CLIError(f"Unsupported section type '{section.kind}'")
    return "".join(chunks)


def _resolve_yaml_path(provided: Optional[str]) -> str:
    if provided:
        return provided
    candidate = os.path.join(os.getcwd(), DEFAULT_YAML_REL)
    if os.path.isfile(candidate):
        return candidate
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, DEFAULT_YAML_REL))


def _find_yaml_flag(argv: List[str]) -> Optional[str]:
    i = 1
    while i < len(argv):
        token = argv[i]
        if token in ("-y", "--yaml") and i + 1 < len(argv):
            return argv[i + 1]
        i += 1
    return None


def _wants_help(argv: List[str]) -> bool:
    return any(arg in ("-h", "--help") for arg in argv[1:])


def _parse_args(argv: List[str]) -> CLIArgs:
    yaml_override: Optional[str] = None
    encoder_index: Optional[int] = None
    envelope_index: Optional[int] = None
    web_mode = False
    positional: List[str] = []

    i = 1
    while i < len(argv):
        token = argv[i]
        if token in ("-y", "--yaml"):
            if i + 1 >= len(argv):
                raise CLIError("Error: -y requires a path to the YAML file")
            yaml_override = argv[i + 1]
            i += 2
            continue
        if token in ("-e", "--encoding"):
            if i + 1 >= len(argv):
                raise CLIError("Error: -e requires an encoder index")
            try:
                encoder_index = int(argv[i + 1])
            except ValueError:
                raise CLIError("Error: -e/--encoding must be an integer index >= 1")
            i += 2
            continue
        if token in ("-env", "--envelop", "--envelope"):
            if i + 1 >= len(argv):
                raise CLIError("Error: -env requires an envelope index")
            try:
                envelope_index = int(argv[i + 1])
            except ValueError:
                raise CLIError("Error: -env/--envelop must be an integer index >= 1")
            i += 2
            continue
        if token in ("-w", "--web"):
            web_mode = True
            i += 1
            continue
        positional.append(token)
        i += 1

    if not positional:
        raise CLIError("Error: No input file provided")
    if len(positional) > 1:
        raise CLIError("Error: Unexpected positional arguments before input file")

    return CLIArgs(
        input_path=positional[0],
        yaml_override=yaml_override,
        encoder_index=encoder_index,
        envelope_index=envelope_index,
        web_mode=web_mode,
    )


def _load_binary(path: str) -> bytes:
    try:
        return read_file(path)
    except OSError as exc:
        raise CLIError(f"Error: Could not open file {path}: {exc}")


def _load_catalog(yaml_path: str) -> Catalog:
    try:
        with open(yaml_path, "r", encoding="utf-8") as handle:
            return Catalog(yaml.safe_load(handle))
    except Exception as exc:
        raise CLIError(f"Error: failed to load/validate YAML: {exc}")


def _build_simple_context(data: bytes) -> GenerationContext:
    sections = [
        Section("payload_array", {"name": "code_blob", "data": data}),
        Section("len_var", {"name": "code_blob", "value": len(data)}),
    ]
    options_meta = {
        "encoder": {"index": None, "name": "none"},
        "envelope": {"index": None, "name": "none"},
    }
    return GenerationContext(sections, payload_bytes=data, payload_text=None, options_meta=options_meta)


def _build_catalog_context(
    args: CLIArgs,
    data: bytes,
    catalog: Catalog,
    yaml_path: str,
) -> GenerationContext:
    sections: List[Section] = []

    enc_idx = args.encoder_index if args.encoder_index is not None else catalog.default_index("encoders")
    env_idx = args.envelope_index if args.envelope_index is not None else catalog.default_index("envelopes")

    try:
        enc_bytes, keys_dict, _enc_emit, enc_spec = catalog.run_encode(enc_idx, data)
    except Exception as exc:
        raise CLIError(f"Encode error (index {enc_idx}): {exc}")

    env_spec = catalog.envelopes.get(env_idx)
    if not env_spec:
        raise CLIError(f"Envelope error (index {env_idx}): not found in catalog")

    envelope_name = str(env_spec.get("name", "")).lower()
    payload_bytes: Optional[bytes]
    payload_text: Optional[str] = None

    for key_name, key_bytes in keys_dict.items():
        sections.append(Section("array", {"name": key_name, "data": key_bytes}))
        sections.append(Section("len_var", {"name": key_name, "value": len(key_bytes)}))

    sections.append(Section("len_var", {"name": "code_blob_expected", "value": len(data)}))

    if envelope_name == "none":
        sections.append(Section("payload_array", {"name": "enc_buf", "data": enc_bytes}))
        sections.append(Section("len_literal", {"name": "enc_len", "value": len(enc_bytes)}))
        payload_bytes = enc_bytes
    else:
        try:
            envelope_text, _env_emit, env_spec = catalog.run_envelope(env_idx, enc_bytes)
        except Exception as exc:
            raise CLIError(f"Envelope error (index {env_idx}): {exc}")
        sections.append(Section("payload_string", {"name": "code_blob_text", "text": envelope_text}))
        sections.append(Section("len_var", {"name": "code_blob_text", "value": len(envelope_text)}))
        sections.append(Section("raw", {"text": "\n// ---- inline envelope decode ----\n"}))
        env_cpp = env_spec["cpp_decode"]
        sections.append(Section("raw", {"text": safe_format_cpp(env_cpp, {})}))
        payload_bytes = envelope_text.encode("utf-8")
        payload_text = envelope_text

    enc_name = str(enc_spec.get("name", "")).lower()
    inverse_cpp = enc_spec["cpp_inverse"]
    context_map: Dict[str, str] = {}
    for key_name in keys_dict:
        context_map[key_name] = key_name
        context_map[f"{key_name}_len"] = f"{key_name}_len"

    comment = (
        "// ---- no encoding: enc_buf becomes code_blob ----"
        if enc_name == "none"
        else "// ---- inline inverse encoding ----"
    )
    sections.append(Section("raw", {"text": "\n" + comment + "\n"}))
    try:
        sections.append(Section("raw", {"text": safe_format_cpp(inverse_cpp, context_map)}))
    except KeyError as exc:
        raise CLIError(f"Error: Missing placeholder for encoder inverse C++: {exc}")

    sections.append(Section("raw", {"text": "\n// code_blob now holds the original binary bytes; length = code_blob_len\n"}))

    options_meta = {
        "encoder": {"index": enc_spec.get("index"), "name": enc_spec.get("name")},
        "envelope": {"index": env_spec.get("index"), "name": env_spec.get("name")},
        "yaml_path": yaml_path,
    }

    return GenerationContext(sections, payload_bytes=payload_bytes, payload_text=payload_text, options_meta=options_meta)


def _format_payload_bytes(payload: bytes, group: int = 16) -> str:
    hex_chunks = [f"0x{byte:02X}" for byte in payload]
    lines = [" ".join(hex_chunks[i : i + group]) for i in range(0, len(hex_chunks), group)]
    return "\n".join(lines)


def _emit_web(context: GenerationContext, term_width: int) -> None:
    if context.payload_bytes is None:
        raise CLIError("Error: payload unavailable for web output")

    code_template = _render_sections(context.sections, True, term_width, PLACEHOLDER_TOKEN)
    payload_value = context.payload_text if context.payload_text is not None else _format_payload_bytes(context.payload_bytes)
    checksum_value = hashlib.sha256(context.payload_bytes).hexdigest()

    payload_checksum = {
        "algorithm": "sha256",
        "value": checksum_value,
    }
    options = {**context.options_meta, "web": True}

    payload_checksum_yaml = yaml.safe_dump(
        {"payload_checksum": payload_checksum},
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    options_yaml = yaml.safe_dump(
        {"options": options},
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    output = "\n".join(
        [
            _block_scalar("code_template", code_template),
            _block_scalar("payload", payload_value),
            payload_checksum_yaml,
            options_yaml,
        ]
    )

    sys.stdout.write(output + "\n")


def _emit_native(context: GenerationContext, term_width: int) -> None:
    code_output = _normalize_newlines(
        _render_sections(context.sections, False, term_width, PLACEHOLDER_TOKEN)
    )
    sys.stdout.write(code_output)


def main(argv: List[str]) -> int:
    yaml_hint = _find_yaml_flag(argv)
    yaml_path_for_help = _resolve_yaml_path(yaml_hint)

    catalog_for_help: Optional[Catalog] = None
    help_error: Optional[str] = None
    try:
        if os.path.isfile(yaml_path_for_help):
            with open(yaml_path_for_help, "r", encoding="utf-8") as handle:
                catalog_for_help = Catalog(yaml.safe_load(handle))
    except Exception:
        import traceback as _tb

        help_error = _tb.format_exc(limit=1)
        catalog_for_help = None

    if _wants_help(argv):
        print_dynamic_help(
            argv[0],
            catalog_for_help,
            DEFAULT_YAML_REL,
            yaml_path_for_help,
            help_error,
        )
        return 0

    try:
        args = _parse_args(argv)
        data = _load_binary(args.input_path)
        term_width = max(40, get_terminal_width())

        if args.yaml_override is None and args.encoder_index is None and args.envelope_index is None:
            context = _build_simple_context(data)
        else:
            yaml_path = _resolve_yaml_path(args.yaml_override)
            if not os.path.isfile(yaml_path):
                raise CLIError(
                    f"Error: YAML not found. Expected at '{yaml_path}'. Pass with -y if different."
                )
            catalog = _load_catalog(yaml_path)
            context = _build_catalog_context(args, data, catalog, yaml_path)

        if args.web_mode:
            _emit_web(context, term_width)
        else:
            _emit_native(context, term_width)

        return 0
    except CLIError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

