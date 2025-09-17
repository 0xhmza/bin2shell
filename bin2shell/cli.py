from __future__ import annotations
import os
import sys
from typing import Any, Dict, List

try:
    import yaml  # PyYAML
except ImportError:
    sys.stderr.write("Error: PyYAML is required. Install with: pip install pyyaml\n")
    raise

from .utils import get_terminal_width, read_file
from .formatting import (
    make_c_array,
    make_len_var,
    make_c_bstring,
    safe_format_cpp,
)
from .catalog import Catalog
from .helptext import print_dynamic_help


DEFAULT_YAML_REL = os.path.join("data", "yaml", "algos.yaml")


def _resolve_yaml_path(provided: str | None) -> str:
    if provided:
        return provided
    # Prefer cwd-relative default
    cand = os.path.join(os.getcwd(), DEFAULT_YAML_REL)
    if os.path.isfile(cand):
        return cand
    # Fallback to location relative to this file (repo layout)
    here = os.path.dirname(os.path.abspath(__file__))
    cand2 = os.path.abspath(os.path.join(here, os.pardir, DEFAULT_YAML_REL))
    return cand2


def main(argv: List[str]) -> int:
    # Pre-scan for -y to enable dynamic help with correct catalog.
    yaml_path_arg = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("-y", "--yaml"):
            if i + 1 < len(argv):
                yaml_path_arg = argv[i + 1]
            break
        i += 1

    # Resolve default path even if not provided
    yaml_path_for_help = _resolve_yaml_path(yaml_path_arg)

    cat_for_help: Catalog | None = None
    help_error: str | None = None
    try:
        if os.path.isfile(yaml_path_for_help):
            with open(yaml_path_for_help, "r", encoding="utf-8") as f:
                cat_for_help = Catalog(yaml.safe_load(f))
    except Exception:
        import traceback as _tb
        help_error = _tb.format_exc(limit=1)
        cat_for_help = None

    # If user asked for help, show dynamic help and exit.
    if any(a in ("-h", "--help") for a in argv[1:]):
        print_dynamic_help(
            argv[0],
            cat_for_help,
            DEFAULT_YAML_REL,
            yaml_path_for_help,
            help_error,
        )
        return 0

    # Real parse
    enc_idx: int | None = None
    comp_idx: int | None = None
    env_idx: int | None = None
    filename: str | None = None
    yaml_path: str | None = None
    anti_sel: str | None = None
    snippet_args: List[str] = []
    positional: List[str] = []

    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("-y", "--yaml"):
            if i + 1 >= len(argv):
                sys.stderr.write("Error: -y requires a path to the YAML file\n")
                return 1
            yaml_path = argv[i + 1]
            i += 2
            continue
        elif a in ("-e", "--encoding"):
            if i + 1 >= len(argv):
                sys.stderr.write("Error: -e requires an encoder index\n")
                return 1
            try:
                enc_idx = int(argv[i + 1])
            except ValueError:
                sys.stderr.write("Error: -e/--encoding must be an integer index >= 1\n")
                return 1
            i += 2
            continue
        elif a in ("-c", "--compression"):
            if i + 1 >= len(argv):
                sys.stderr.write("Error: -c requires a compressor index\n")
                return 1
            try:
                comp_idx = int(argv[i + 1])
            except ValueError:
                sys.stderr.write("Error: -c/--compression must be an integer index >= 1\n")
                return 1
            i += 2
            continue
        elif a in ("-env", "--envelop", "--envelope"):
            if i + 1 >= len(argv):
                sys.stderr.write("Error: -env requires an envelope index\n")
                return 1
            try:
                env_idx = int(argv[i + 1])
            except ValueError:
                sys.stderr.write("Error: -env/--envelop must be an integer index >= 1\n")
                return 1
            i += 2
            continue
        elif a in ("-ae", "--entiemulation"):
            if i + 1 >= len(argv):
                sys.stderr.write("Error: -ae/--entiemulation requires a method name\n")
                return 1
            anti_sel = argv[i + 1]
            i += 2
            continue
        else:
            positional.append(a)
            i += 1

    if not positional:
        sys.stderr.write("Error: No input file provided\n")
        return 1

    filename = positional[-1]
    extras = positional[:-1]

    snippet_token: str | None = None
    if anti_sel:
        if extras:
            if len(extras) > 1:
                sys.stderr.write("Error: Too many argument blocks before input file; expected at most one a:b:c:.. list.\n")
                return 1
            snippet_token = extras[0]
    else:
        if extras:
            sys.stderr.write("Error: Unexpected positional arguments before input file\n")
            return 1

    if snippet_token:
        parts = [p.strip() for p in snippet_token.split(":")]
        if any(p == "" for p in parts):
            sys.stderr.write("Error: Anti-emulation args must not contain empty segments\n")
            return 1
        snippet_args = parts
    else:
        snippet_args = []

    try:
        data = read_file(filename)
    except OSError as e:
        sys.stderr.write(f"Error: Could not open file {filename}: {e}\n")
        return 1

    term_width = max(40, get_terminal_width())

    # Bare-bytes default mode: only input filename provided (no selections, no yaml flag)
    only_filename = (
        yaml_path_arg is None and enc_idx is None and comp_idx is None and env_idx is None and anti_sel is None
    )
    if only_filename:
        sys.stdout.write(make_c_array("code_blob", data, term_width))
        sys.stdout.write(make_len_var("code_blob", len(data)))
        return 0

    # Resolve final YAML path, default to data/yaml/algos.yaml
    yaml_path = _resolve_yaml_path(yaml_path)
    if not os.path.isfile(yaml_path):
        sys.stderr.write(
            f"Error: YAML not found. Expected at '{yaml_path}'. Pass with -y if different.\n"
        )
        return 1

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            cat = Catalog(yaml.safe_load(f))
    except Exception as e:
        sys.stderr.write(f"Error: failed to load/validate YAML: {e}\n")
        return 1

    # Choose defaults if not provided (smallest index)
    if enc_idx is None:
        enc_idx = cat.default_index("encoders")
    if comp_idx is None:
        comp_idx = cat.default_index("compressors")
    if env_idx is None:
        env_idx = cat.default_index("envelopes")

    # Sleep selection validation (optional)
    anti_spec = None
    if anti_sel is not None:
        anti_spec = cat.find_anti_emulation(anti_sel)
        if not anti_spec:
            sys.stderr.write("Error: Unknown anti-emulation method. Use -h to list.\n")
            return 1

    # 1) compression
    try:
        comp_bytes, comp_meta, comp_emit, comp_spec = cat.run_compress(comp_idx, data)
    except Exception as e:
        sys.stderr.write(f"Compression error (index {comp_idx}): {e}\n")
        return 1

    # 2) encode
    try:
        enc_bytes, keys_dict, enc_emit, enc_spec = cat.run_encode(enc_idx, comp_bytes)
    except Exception as e:
        sys.stderr.write(f"Encode error (index {enc_idx}): {e}\n")
        return 1

    # 3) envelope (optional)
    env_spec = cat.envelopes.get(env_idx)
    if not env_spec:
        sys.stderr.write(f"Envelope error (index {env_idx}): not found in catalog\n")
        return 1
    env_name = str(env_spec.get("name", "")).lower()
    if env_name != "none":
        try:
            envelope_text, env_emit, env_spec = cat.run_envelope(env_idx, enc_bytes)
        except Exception as e:
            sys.stderr.write(f"Envelope error (index {env_idx}): {e}\n")
            return 1

    # ---- Emit: keys first (if any) ----
    for key_name, key_bytes in keys_dict.items():
        sys.stdout.write(make_c_array(key_name, key_bytes, term_width))
        sys.stdout.write(make_len_var(key_name, len(key_bytes)))

    # ---- Emit dictionary/meta for compression if required ----
    if comp_emit.get("dict_arrays"):
        for arr in comp_emit["dict_arrays"]:
            var = arr["var"]
            kind = arr.get("kind", "bytes")
            if kind == "bytes_from_list_hi":
                buf = bytes(x[0] for x in comp_meta[arr["source"]])
            elif kind == "bytes_from_list_lo":
                buf = bytes(x[1] for x in comp_meta[arr["source"]])
            elif kind == "bytes_from_bytes":
                buf = comp_meta[arr["source"]]
            else:
                sys.stderr.write(f"Error: Unknown dict array kind: {kind}\n")
                return 1
            sys.stdout.write(make_c_array(var, buf, term_width))
            sys.stdout.write(make_len_var(var, len(buf)))

    # ---- Expected final decompressed length (original) ----
    sys.stdout.write(make_len_var("code_blob_expected", len(data)))

    # ---- Emit envelope or encoded bytes ----
    anti_ctx: Dict[str, Any] = {"ANTI-EMULATION-SNIPPET": ""}
    if anti_spec:
        raw = anti_spec.get("cpp_snippet", "")
        arg_names = anti_spec.get("args", []) or []
        # Build context for formatting: always inject through {ANTI-EMULATION-SNIPPET}
        ctx_anti: Dict[str, Any] = {"PAYLOAD_LEN": "code_blob_len"}
        if arg_names:
            if len(snippet_args) < len(arg_names):
                if len(arg_names) == 1 and not snippet_args and str(arg_names[0]).lower() == "duration":
                    ctx_anti["duration"] = "3000"
                else:
                    sys.stderr.write(f"Error: anti-emulation '{anti_spec.get('name','')}' expects {len(arg_names)} argument(s); provide them as a:b:c:.. before the input file.\n")
                    return 1
            elif len(snippet_args) > len(arg_names):
                sys.stderr.write(f"Error: anti-emulation '{anti_spec.get('name','')}' expects {len(arg_names)} argument(s); got {len(snippet_args)}.\n")
                return 1
            for name, value in zip(arg_names, snippet_args):
                ctx_anti[name] = value
        else:
            if snippet_args:
                sys.stderr.write(f"Error: anti-emulation '{anti_spec.get('name','')}' does not take arguments.\n")
                return 1
        if any(str(n).lower() == "duration" for n in arg_names) and "duration" not in ctx_anti:
            ctx_anti["duration"] = "3000"
        try:
            anti_code = safe_format_cpp(raw, ctx_anti)
        except KeyError as e:
            sys.stderr.write(f"Error: Anti-emulation snippet missing placeholder: {e}\n")
            return 1
        anti_ctx["ANTI-EMULATION-SNIPPET"] = anti_code

    if env_name == "none":
        # No envelope: emit encoded bytes directly as enc_buf/enc_len
        sys.stdout.write(make_c_array("enc_buf", enc_bytes, term_width))
        sys.stdout.write(f"unsigned int enc_len = {len(enc_bytes)};\n")
    else:
        # Emit envelope text and decoder snippet to produce enc_buf/enc_len
        sys.stdout.write(make_c_bstring("code_blob_text", envelope_text, term_width))
        sys.stdout.write(make_len_var("code_blob_text", len(envelope_text)))
        sys.stdout.write("\n// ---- inline envelope decode ----\n")
        env_cpp = env_spec["cpp_decode"]
        sys.stdout.write(safe_format_cpp(env_cpp, anti_ctx))

    # 3b) ENCODER inverse C++ (turn enc_buf -> comp_buf)
    enc_name = enc_spec["name"].lower()
    if enc_name == "none":
        sys.stdout.write(r"""
// ---- no encoding: enc_buf is compressed payload ----
unsigned char* comp_buf = new unsigned char[enc_len];
unsigned int comp_len = enc_len;
for (unsigned int i = 0; i < enc_len; ++i) comp_buf[i] = enc_buf[i];
""")
    else:
        inv_cpp = enc_spec["cpp_inverse"]
        ctx: Dict[str, Any] = {}
        for k in keys_dict:
            ctx[k] = k
            ctx[f"{k}_len"] = f"{k}_len"
        # include anti-emulation snippet if present
        ctx.update(anti_ctx)
        sys.stdout.write("\n// ---- inline inverse encoding ----\n")
        try:
            sys.stdout.write(safe_format_cpp(inv_cpp, ctx))
        except KeyError as e:
            sys.stderr.write(
                f"Error: Missing placeholder for encoder inverse C++: {e}\n"
            )
            return 1

    # 3c) COMPRESSION inverse C++ (turn comp_buf -> code_blob)
    decomp_cpp = comp_spec["cpp_decompress"]
    ctx: Dict[str, Any] = {}
    for arr in comp_emit.get("dict_arrays", []):
        var = arr["var"]
        ctx[var] = var
        ctx[f"{var}_len"] = f"{var}_len"
    ctx.update(anti_ctx)
    sys.stdout.write("\n// ---- inline decompression ----\n")
    try:
        sys.stdout.write(safe_format_cpp(decomp_cpp, ctx))
    except KeyError as e:
        sys.stderr.write(f"Error: Missing placeholder for decompression C++: {e}\n")
        return 1

    sys.stdout.write(
        "\n// code_blob now holds the original binary bytes; length = code_blob_len\n"
    )

    # No appended snippet emission; all snippets are injected via {ANTI-EMULATION-SNIPPET}
    return 0
