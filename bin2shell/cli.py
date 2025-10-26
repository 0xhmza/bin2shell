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
    env_idx: int | None = None
    filename: str | None = None
    yaml_path: str | None = None
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
        else:
            positional.append(a)
            i += 1

    if not positional:
        sys.stderr.write("Error: No input file provided\n")
        return 1
    if len(positional) > 1:
        sys.stderr.write("Error: Unexpected positional arguments before input file\n")
        return 1

    filename = positional[0]

    try:
        data = read_file(filename)
    except OSError as e:
        sys.stderr.write(f"Error: Could not open file {filename}: {e}\n")
        return 1

    term_width = max(40, get_terminal_width())

    # Bare-bytes default mode: only input filename provided (no selections, no yaml flag)
    only_filename = (
        yaml_path_arg is None and enc_idx is None and env_idx is None
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
    if env_idx is None:
        env_idx = cat.default_index("envelopes")

    # encode
    try:
        enc_bytes, keys_dict, _enc_emit, enc_spec = cat.run_encode(enc_idx, data)
    except Exception as e:
        sys.stderr.write(f"Encode error (index {enc_idx}): {e}\n")
        return 1

    # envelope (optional)
    env_spec = cat.envelopes.get(env_idx)
    if not env_spec:
        sys.stderr.write(f"Envelope error (index {env_idx}): not found in catalog\n")
        return 1
    env_name = str(env_spec.get("name", "")).lower()
    if env_name != "none":
        try:
            envelope_text, _env_emit, env_spec = cat.run_envelope(env_idx, enc_bytes)
        except Exception as e:
            sys.stderr.write(f"Envelope error (index {env_idx}): {e}\n")
            return 1

    # ---- Emit: keys first (if any) ----
    for key_name, key_bytes in keys_dict.items():
        sys.stdout.write(make_c_array(key_name, key_bytes, term_width))
        sys.stdout.write(make_len_var(key_name, len(key_bytes)))

    # ---- Expected final payload length (original) ----
    sys.stdout.write(make_len_var("code_blob_expected", len(data)))

    # ---- Emit envelope or encoded bytes ----

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
        sys.stdout.write(safe_format_cpp(env_cpp, {}))

    # ---- Inverse encoding (enc_buf -> code_blob) ----
    enc_name = enc_spec["name"].lower()
    inv_cpp = enc_spec["cpp_inverse"]
    ctx: Dict[str, Any] = {}
    for k in keys_dict:
        ctx[k] = k
        ctx[f"{k}_len"] = f"{k}_len"
    comment = "// ---- no encoding: enc_buf becomes code_blob ----" if enc_name == "none" else "// ---- inline inverse encoding ----"
    sys.stdout.write("\n" + comment + "\n")
    try:
        sys.stdout.write(safe_format_cpp(inv_cpp, ctx))
    except KeyError as e:
        sys.stderr.write(
            f"Error: Missing placeholder for encoder inverse C++: {e}\n"
        )
        return 1

    sys.stdout.write(
        "\n// code_blob now holds the original binary bytes; length = code_blob_len\n"
    )

    # No appended snippet emission; all snippets are injected via YAML definitions
    return 0
