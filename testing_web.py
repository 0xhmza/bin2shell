#!/usr/bin/env python3
"""Test harness for bin2shell web mode.

Generates web-mode output for every encoder × envelope × web_helper combination,
validates the YAML bundle structure, and optionally compiles the C++ template.
Produces an HTML report similar to testing.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

try:
    import yaml
except ImportError:
    sys.stderr.write("Error: PyYAML is required. Install with: pip install pyyaml\n")
    sys.exit(1)


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_YAML = os.path.join(ROOT, "data", "yaml", "algos.yaml")
DEFAULT_INPUT = os.path.join(ROOT, "messagebox.bin")
DEFAULT_REPORT = os.path.join(ROOT, "report_web.html")


@dataclass
class AlgoSpec:
    index: int
    name: str


@dataclass
class TestCase:
    label: str
    args: list[str]
    encoder: str
    envelope: str
    web_helper: str
    input_path: str


@dataclass
class TestResult:
    case: TestCase
    main_ok: bool
    main_error: str
    yaml_ok: str
    yaml_error: str
    compile_ok: str
    compile_error: str
    command: str


def load_specs(yaml_path: str) -> tuple[list[AlgoSpec], list[AlgoSpec], list[AlgoSpec]]:
    with open(yaml_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    encoders = sorted(
        [AlgoSpec(index=int(s["index"]), name=str(s.get("name", ""))) for s in data.get("encoders", [])],
        key=lambda s: s.index,
    )
    envelopes = sorted(
        [AlgoSpec(index=int(s["index"]), name=str(s.get("name", ""))) for s in data.get("envelopes", [])],
        key=lambda s: s.index,
    )
    web_helpers = sorted(
        [AlgoSpec(index=int(s["index"]), name=str(s.get("name", ""))) for s in data.get("web_helpers", [])],
        key=lambda s: s.index,
    )
    return encoders, envelopes, web_helpers


def resolve_compiler(user_spec: str | None) -> list[str]:
    if user_spec:
        import shlex
        return shlex.split(user_spec, posix=os.name != "nt")
    env_spec = os.environ.get("CXX", "")
    if env_spec:
        import shlex
        return shlex.split(env_spec, posix=os.name != "nt")
    for candidate in ("g++", "clang++", "clang-cl", "cl"):
        path = shutil.which(candidate)
        if path:
            return [path]
    return []


def compiler_style(compiler_cmd: list[str]) -> str:
    if not compiler_cmd:
        return ""
    base = os.path.basename(compiler_cmd[0]).lower()
    if base in ("cl", "cl.exe") or "clang-cl" in base:
        return "msvc"
    return "gcc"


def run_main(main_py: str, args: list[str]) -> tuple[int, str, str]:
    cmd = [sys.executable, main_py] + args
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def validate_yaml_bundle(stdout: str) -> tuple[bool, str]:
    """Check that the output is a valid YAML bundle with expected keys."""
    try:
        bundle = yaml.safe_load(stdout)
    except Exception as exc:
        return False, f"YAML parse error: {exc}"
    if not isinstance(bundle, dict):
        return False, f"Expected dict, got {type(bundle).__name__}"
    required = {"cpp_includes", "cpp_web_fetch", "cpp_payload_init", "payload", "options"}
    missing = required - set(bundle.keys())
    if missing:
        return False, f"Missing keys: {missing}"
    opts = bundle.get("options", {})
    if not isinstance(opts, dict):
        return False, "options is not a dict"
    if not opts.get("web"):
        return False, "options.web is not true"
    fetch = bundle.get("cpp_web_fetch", "")
    if "bin2shell_fetch_payload" not in fetch:
        return False, "cpp_web_fetch missing fetch function"
    return True, ""


def extract_compilable_code(stdout: str) -> str | None:
    """Concatenate all cpp_* fields in order to form a compilable unit."""
    try:
        bundle = yaml.safe_load(stdout)
        parts = []
        for key in ("cpp_includes", "cpp_declarations", "cpp_web_fetch", "cpp_payload_init", "cpp_decode"):
            val = bundle.get(key, "")
            if val:
                parts.append(val)
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def compile_cpp(compiler_cmd: list[str], cpp_text: str) -> tuple[bool, str]:
    if not compiler_cmd:
        return False, "Compiler not found"
    style = compiler_style(compiler_cmd)
    with tempfile.TemporaryDirectory() as tmpdir:
        cpp_path = os.path.join(tmpdir, "generated.cpp")
        obj_path = os.path.join(tmpdir, "generated.obj" if style == "msvc" else "generated.o")
        with open(cpp_path, "w", encoding="utf-8") as handle:
            handle.write(cpp_text)
            if not cpp_text.endswith("\n"):
                handle.write("\n")
        if style == "msvc":
            cmd = compiler_cmd + ["/nologo", "/c", "/EHsc", "/std:c++17", cpp_path, f"/Fo:{obj_path}"]
        else:
            cmd = compiler_cmd + ["-std=c++17", "-c", cpp_path, "-o", obj_path]
        proc = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True)
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return proc.returncode == 0, output


def build_cases(
    encoders: list[AlgoSpec],
    envelopes: list[AlgoSpec],
    web_helpers: list[AlgoSpec],
    input_path: str,
) -> list[TestCase]:
    cases: list[TestCase] = []
    if not web_helpers:
        return cases
    for wh in web_helpers:
        for enc in encoders:
            for env in envelopes:
                cases.append(
                    TestCase(
                        label=f"wh={wh.index} enc={enc.index} env={env.index}",
                        args=[
                            "--encoder", str(enc.index),
                            "--envelope", str(env.index),
                            "--web",
                            "--web-helper", str(wh.index),
                            input_path,
                        ],
                        encoder=f"{enc.index}:{enc.name}",
                        envelope=f"{env.index}:{env.name}",
                        web_helper=f"{wh.index}:{wh.name}",
                        input_path=input_path,
                    )
                )
    return cases


def html_escape(value: str) -> str:
    return html.escape(value or "")


def status_span(text: str, cls: str) -> str:
    return f'<span class="{cls}">{html_escape(text)}</span>'


def render_report(
    results: list[TestResult],
    output_path: str,
    input_path: str,
    yaml_path: str,
    compiler_cmd: list[str],
) -> None:
    total = len(results)
    main_fail = sum(1 for r in results if not r.main_ok)
    yaml_fail = sum(1 for r in results if r.yaml_ok == "error")
    compile_fail = sum(1 for r in results if r.compile_ok == "error")
    compile_skip = sum(1 for r in results if r.compile_ok == "skipped")
    compile_ok = total - compile_fail - compile_skip
    compiler_label = " ".join(compiler_cmd) if compiler_cmd else "not found"

    rows = []
    for res in results:
        main_status = status_span("OK", "status-ok") if res.main_ok else status_span("ERROR", "status-err")
        yaml_status = (
            status_span("OK", "status-ok") if res.yaml_ok == "ok"
            else status_span("SKIPPED", "status-skip") if res.yaml_ok == "skipped"
            else status_span("ERROR", "status-err")
        )
        compile_status = (
            status_span("OK", "status-ok") if res.compile_ok == "ok"
            else status_span("SKIPPED", "status-skip") if res.compile_ok == "skipped"
            else status_span("ERROR", "status-err")
        )
        rows.append(
            "\n".join([
                "<tr>",
                f"<td>{html_escape(res.case.web_helper)}</td>",
                f"<td>{html_escape(res.case.encoder)}</td>",
                f"<td>{html_escape(res.case.envelope)}</td>",
                f"<td>{main_status}</td>",
                f"<td>{yaml_status}</td>",
                f"<td>{compile_status}</td>",
                f"<td><pre>{html_escape(res.main_error)}</pre></td>",
                f"<td><pre>{html_escape(res.yaml_error)}</pre></td>",
                f"<td><pre>{html_escape(res.compile_error)}</pre></td>",
                "</tr>",
            ])
        )

    html_body = "\n".join([
        "<!doctype html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        "<title>bin2shell web mode test report</title>",
        "<style>",
        "body { font-family: Arial, Helvetica, sans-serif; margin: 20px; }",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 1px solid #ccc; padding: 6px 8px; vertical-align: top; }",
        "th { background: #f2f2f2; }",
        "pre { margin: 0; white-space: pre-wrap; }",
        ".status-ok { color: #146c2e; font-weight: bold; }",
        ".status-err { color: #a40000; font-weight: bold; }",
        ".status-skip { color: #666666; font-weight: bold; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>bin2shell web mode test report</h1>",
        f"<p>Generated: {html_escape(dt.datetime.now().isoformat(timespec='seconds'))}</p>",
        f"<p>Input: {html_escape(input_path)}</p>",
        f"<p>YAML: {html_escape(yaml_path)}</p>",
        f"<p>Compiler: {html_escape(compiler_label)}</p>",
        (
            "<p>Totals: "
            f"{total} cases, {main_fail} main errors, "
            f"{yaml_fail} YAML errors, "
            f"{compile_fail} compile errors, {compile_skip} compile skipped, "
            f"{compile_ok} compile OK</p>"
        ),
        "<table>",
        "<thead>",
        "<tr>",
        "<th>Web Helper</th>",
        "<th>Encoder</th>",
        "<th>Envelope</th>",
        "<th>Main</th>",
        "<th>YAML</th>",
        "<th>Compile</th>",
        "<th>Main Error</th>",
        "<th>YAML Error</th>",
        "<th>Compile Error</th>",
        "</tr>",
        "</thead>",
        "<tbody>",
        "\n".join(rows),
        "</tbody>",
        "</table>",
        "</body>",
        "</html>",
    ])

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html_body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test bin2shell web mode across all playbook combinations.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input binary to test.")
    parser.add_argument("--yaml", dest="yaml_path", default=DEFAULT_YAML, help="Path to algos.yaml.")
    parser.add_argument("--out", dest="out_path", default=DEFAULT_REPORT, help="HTML report output path.")
    parser.add_argument("--compiler", default="", help="Compiler command (overrides CXX auto-detection).")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    yaml_path = os.path.abspath(args.yaml_path)
    out_path = os.path.abspath(args.out_path)
    main_py = os.path.join(ROOT, "main.py")

    if not os.path.isfile(input_path):
        sys.stderr.write(f"Error: input file not found: {input_path}\n")
        return 1
    if not os.path.isfile(yaml_path):
        sys.stderr.write(f"Error: YAML file not found: {yaml_path}\n")
        return 1
    if not os.path.isfile(main_py):
        sys.stderr.write(f"Error: main.py not found: {main_py}\n")
        return 1

    encoders, envelopes, web_helpers = load_specs(yaml_path)
    if not web_helpers:
        sys.stderr.write("Error: no web_helpers found in YAML playbook\n")
        return 1

    cases = build_cases(encoders, envelopes, web_helpers, input_path)
    compiler_cmd = resolve_compiler(args.compiler)

    print(f"Running {len(cases)} web mode test cases...")

    results: list[TestResult] = []
    for i, case in enumerate(cases, 1):
        print(f"  [{i}/{len(cases)}] {case.label}", end="", flush=True)
        returncode, stdout, stderr = run_main(main_py, case.args)
        main_ok = returncode == 0
        main_error = "" if main_ok else (stderr.strip() or stdout.strip())

        yaml_state = "skipped"
        yaml_error = ""
        compile_state = "skipped"
        compile_error = ""

        if main_ok:
            y_ok, y_err = validate_yaml_bundle(stdout)
            yaml_state = "ok" if y_ok else "error"
            yaml_error = y_err

            if y_ok:
                code = extract_compilable_code(stdout)
                if code and compiler_cmd:
                    c_ok, c_out = compile_cpp(compiler_cmd, code)
                    compile_state = "ok" if c_ok else "error"
                    compile_error = "" if c_ok else c_out
                elif not compiler_cmd:
                    compile_state = "skipped"
                    compile_error = "No compiler found"
        else:
            yaml_state = "skipped"
            yaml_error = "Skipped due to main.py error"
            compile_state = "skipped"
            compile_error = "Skipped due to main.py error"

        status = "OK" if main_ok and yaml_state == "ok" else "FAIL"
        print(f" ... {status}")

        command = " ".join([sys.executable, main_py] + case.args)
        results.append(
            TestResult(
                case=case,
                main_ok=main_ok,
                main_error=main_error,
                yaml_ok=yaml_state,
                yaml_error=yaml_error,
                compile_ok=compile_state,
                compile_error=compile_error,
                command=command,
            )
        )

    render_report(results, out_path, input_path, yaml_path, compiler_cmd)
    print(f"Wrote report to {out_path}")

    failures = sum(1 for r in results if not r.main_ok or r.yaml_ok == "error")
    if failures:
        print(f"\n{failures} failure(s) detected!")
        return 1
    print(f"\nAll {len(results)} cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
