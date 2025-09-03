from __future__ import annotations
import os
from typing import Any, Dict, List


def _print_block_table(out: List[str], title: str, items: List[Dict[str, Any]], cpp_key: str, show_args: bool = False) -> None:
    out.append(title + ":")
    name_w = max((len(str(spec.get("name", ""))) for spec in items), default=4)
    for spec in items:
        idx = spec.get("index", "?")
        name = str(spec.get("name", ""))
        desc = str(spec.get("desc", ""))
        cpp_has = cpp_key in spec and bool(str(spec.get(cpp_key, "")).strip())
        cpp_part = "" if cpp_has else " (missing C++ snippet!)"
        args_list = spec.get("args", []) if show_args else []
        args_part = f" | Args: {':'.join(args_list)}" if args_list else ""
        desc_part = (" - " + desc) if desc else ""
        out.append(f"  [{idx:<2}] {name:<{name_w}}{desc_part}{args_part}{cpp_part}")
    out.append("")


def print_dynamic_help(
    argv0: str,
    cat,
    default_yaml_rel: str,
    resolved_yaml_path: str | None = None,
    load_error: str | None = None,
) -> None:
    exe = os.path.basename(argv0) if argv0 else "main.py"
    out: List[str] = []

    # Overview first
    out.extend(_overview_lines(default_yaml_rel))
    out.append("")

    # Usage and options next
    out.append("Usage:")
    out.append(
        f"  {exe} [-y <yaml>] [-e <enc_idx>] [-c <comp_idx>] [-env <env_idx>] [-s <method>] [--args a:b[:c]] <file>\n"
    )
    out.append("Options:")
    out.append(
        f"  -y,   --yaml <path>         Path to algorithms YAML (default: {default_yaml_rel})"
    )
    out.append("  -e,   --encoding <idx>      Encoder index")
    out.append("  -c,   --compression <idx>   Compressor index")
    out.append("  -env, --envelop <idx>       Envelope index")
    out.append("  -s,   --sleep <method>      Select a YAML snippet under 'sleeps' and inject via {SLEEP_SNIPPET}.")
    out.append("        --args a:b[:c]        Colon-separated args for the selected snippet (matches YAML 'args').")
    out.append("  -h,   --help                Show this help")
    out.append("")

    # Available algorithms from YAML (defaulted when -y not given)
    if cat is not None:
        out.append("Available From YAML:")
        _print_block_table(out, "Encoders", cat.list_block("encoders"), "cpp_inverse")
        _print_block_table(out, "Compressors", cat.list_block("compressors"), "cpp_decompress")
        _print_block_table(out, "Envelopes", cat.list_block("envelopes"), "cpp_decode")
        sleeps = cat.list_block("sleeps") if getattr(cat, "sleeps", None) else []
        if sleeps:
            _print_block_table(out, "Sleepers", sleeps, "cpp_snippet", show_args=True)
        out.append("Defaults (if not specified):")
        out.append(f"  encoder    -> index {cat.default_index('encoders')}")
        out.append(f"  compressor -> index {cat.default_index('compressors')}")
        out.append(f"  envelope   -> index {cat.default_index('envelopes')}")
    else:
        # Provide a helpful pointer about the default location that was tried
        if resolved_yaml_path:
            if os.path.isfile(resolved_yaml_path):
                msg = "Failed to load default YAML at '" + resolved_yaml_path + "'"
                if load_error:
                    msg += ": " + load_error
                out.append(msg)
            else:
                out.append("Default YAML not found at '" + resolved_yaml_path + "'.")
        else:
            out.append(
                "YAML not loaded; expected default at '" + default_yaml_rel + "' relative to cwd."
            )

    print("\n".join(out) + "\n")


def _overview_lines(default_yaml_rel: str) -> list[str]:
    lines: list[str] = []
    lines.append("Overview:")
    lines.append("  Purpose: generate C/C++ that reconstructs an input binary at runtime.")
    lines.append(
        "  Pipeline (forward in Python, reversed in emitted C++):"
    )
    lines.append(
        "    - Compression: produce compact bytes and optional dictionaries."
    )
    lines.append(
        "    - Encoding: reversible transform using optional keys (e.g., XOR/ARX)."
    )
    lines.append(
        "    - Envelope: render bytes to printable text (e.g., Base91/Base64)."
    )
    lines.append(
        "  YAML-driven: algorithms and C++ snippets live in the catalog (see 'sleeps')."
    )
    lines.append("")
    lines.append("Argument injection:")
    lines.append("  Use --args a:b[:c] for YAML snippets with placeholders, e.g.,")
    lines.append("    - Sleep duration: --sleep thread_ms --args 3000")
    lines.append("    - Stub siralloc:  -s siralloc --args 32:10 (PAYLOAD_LEN maps to code_blob_len)")
    lines.append("")
    lines.append("Bypass mode:")
    lines.append(
        "  Index 0 is reserved for 'none' across encoder/compressor/envelope."
    )
    lines.append(
        "  Omitting -e/-c/-env implies 0 (none)."
    )
    lines.append(
        f"  Default YAML location: {default_yaml_rel} (relative to cwd), override with -y."
    )
    return lines
