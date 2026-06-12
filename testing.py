#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import shlex
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
DEFAULT_REPORT = os.path.join(ROOT, "report.html")


@dataclass
class AlgoSpec:
    index: int
    name: str


@dataclass
class TestCase:
    label: str
    args: list[str]
    mode: str
    encoder: str
    envelope: str
    input_path: str


@dataclass
class TestResult:
    case: TestCase
    main_ok: bool
    main_error: str
    compile_ok: str
    compile_error: str
    command: str


def load_specs(yaml_path: str) -> tuple[list[AlgoSpec], list[AlgoSpec]]:
    with open(yaml_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    encoders = []
    for spec in data.get("encoders", []):
        encoders.append(AlgoSpec(index=int(spec["index"]), name=str(spec.get("name", ""))))
    envelopes = []
    for spec in data.get("envelopes", []):
        envelopes.append(AlgoSpec(index=int(spec["index"]), name=str(spec.get("name", ""))))
    encoders.sort(key=lambda s: s.index)
    envelopes.sort(key=lambda s: s.index)
    return encoders, envelopes


def parse_compiler_spec(spec: str) -> list[str]:
    if not spec:
        return []
    return shlex.split(spec, posix=os.name != "nt")


def compiler_style(compiler_cmd: list[str]) -> str:
    if not compiler_cmd:
        return ""
    base = os.path.basename(compiler_cmd[0]).lower()
    if base in ("cl", "cl.exe") or "clang-cl" in base:
        return "msvc"
    return "gcc"


def resolve_compiler(user_spec: str | None) -> list[str]:
    if user_spec:
        return parse_compiler_spec(user_spec)
    env_spec = os.environ.get("CXX", "")
    if env_spec:
        return parse_compiler_spec(env_spec)
    for candidate in ("g++", "clang++", "clang-cl", "cl"):
        path = shutil.which(candidate)
        if path:
            return [path]
    return []


def run_main(main_py: str, args: list[str]) -> tuple[int, str, str]:
    cmd = [sys.executable, main_py] + args
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


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


CARRIER_NAMES = ["ini", "png", "bmp", "ico"]


def build_cases(encoders: list[AlgoSpec], envelopes: list[AlgoSpec], input_path: str) -> list[TestCase]:
    cases: list[TestCase] = []
    cases.append(
        TestCase(
            label="simple",
            args=[input_path],
            mode="simple",
            encoder="none",
            envelope="none",
            input_path=input_path,
        )
    )
    for enc in encoders:
        for env in envelopes:
            cases.append(
                TestCase(
                    label=f"enc={enc.index} env={env.index}",
                    args=["--encoder", str(enc.index), "--envelope", str(env.index), input_path],
                    mode="playbook",
                    encoder=f"{enc.index}:{enc.name}",
                    envelope=f"{env.index}:{env.name}",
                    input_path=input_path,
                )
            )
    default_enc = encoders[0] if encoders else None
    default_env = envelopes[0] if envelopes else None
    if default_enc and default_env:
        for enc in encoders:
            cases.append(
                TestCase(
                    label=f"enc={enc.index} env=default",
                    args=["--encoder", str(enc.index), input_path],
                    mode="playbook-default-env",
                    encoder=f"{enc.index}:{enc.name}",
                    envelope=f"{default_env.index}:{default_env.name}",
                    input_path=input_path,
                )
            )
        for env in envelopes:
            cases.append(
                TestCase(
                    label=f"enc=default env={env.index}",
                    args=["--envelope", str(env.index), input_path],
                    mode="playbook-default-enc",
                    encoder=f"{default_enc.index}:{default_enc.name}",
                    envelope=f"{env.index}:{env.name}",
                    input_path=input_path,
                )
            )

    # Carrier sweep — one representative encoder × one envelope per carrier.
    # The carrier code path is independent of which encoder/envelope feeds it,
    # so we don't multiply by the full matrix.
    pick_enc = next((e for e in encoders if e.name == "chacha20"), default_enc)
    pick_env = next((e for e in envelopes if e.name == "base64"), default_env)
    if pick_enc and pick_env:
        carrier_out_dir = os.path.join(ROOT, ".test-carrier-out")
        os.makedirs(carrier_out_dir, exist_ok=True)
        for carrier_name in CARRIER_NAMES:
            carrier_file = os.path.join(carrier_out_dir, f"payload.{carrier_name}")
            cases.append(
                TestCase(
                    label=f"carrier={carrier_name}",
                    args=[
                        "--encoder", str(pick_enc.index),
                        "--envelope", str(pick_env.index),
                        "--carrier", carrier_name,
                        "--carrier-out", carrier_file,
                        input_path,
                    ],
                    mode=f"carrier-{carrier_name}",
                    encoder=f"{pick_enc.index}:{pick_enc.name}",
                    envelope=f"{pick_env.index}:{pick_env.name}",
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
    compile_fail = sum(1 for r in results if r.compile_ok == "error")
    compile_skip = sum(1 for r in results if r.compile_ok == "skipped")
    compile_ok = total - compile_fail - compile_skip
    compiler_label = " ".join(compiler_cmd) if compiler_cmd else "not found"

    rows = []
    for res in results:
        if res.main_ok:
            main_status = status_span("OK", "status-ok")
        else:
            main_status = status_span("ERROR", "status-err")
        if res.compile_ok == "ok":
            compile_status = status_span("OK", "status-ok")
        elif res.compile_ok == "skipped":
            compile_status = status_span("SKIPPED", "status-skip")
        else:
            compile_status = status_span("ERROR", "status-err")
        rows.append(
            "\n".join(
                [
                    "<tr>",
                    f"<td>{html_escape(res.case.input_path)}</td>",
                    f"<td>{html_escape(res.case.mode)}</td>",
                    f"<td>{html_escape(res.case.encoder)}</td>",
                    f"<td>{html_escape(res.case.envelope)}</td>",
                    f"<td>{html_escape(' '.join(res.case.args))}</td>",
                    f"<td>{main_status}</td>",
                    f"<td>{compile_status}</td>",
                    f"<td><pre>{html_escape(res.main_error)}</pre></td>",
                    f"<td><pre>{html_escape(res.compile_error)}</pre></td>",
                    "</tr>",
                ]
            )
        )

    html_body = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>bin2shell test report</title>",
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
            "<h1>bin2shell test report</h1>",
            f"<p>Generated: {html_escape(dt.datetime.now().isoformat(timespec='seconds'))}</p>",
            f"<p>Input: {html_escape(input_path)}</p>",
            f"<p>YAML: {html_escape(yaml_path)}</p>",
            f"<p>Compiler: {html_escape(compiler_label)}</p>",
            (
                "<p>Totals: "
                f"{total} cases, {main_fail} main errors, "
                f"{compile_fail} compile errors, {compile_skip} compile skipped, "
                f"{compile_ok} compile OK</p>"
            ),
            "<table>",
            "<thead>",
            "<tr>",
            "<th>Input</th>",
            "<th>Mode</th>",
            "<th>Encoder</th>",
            "<th>Envelope</th>",
            "<th>Arguments</th>",
            "<th>Main</th>",
            "<th>Compile</th>",
            "<th>Main Error</th>",
            "<th>Compile Error</th>",
            "</tr>",
            "</thead>",
            "<tbody>",
            "\n".join(rows),
            "</tbody>",
            "</table>",
            "</body>",
            "</html>",
        ]
    )

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html_body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bin2shell across all playbook inputs and compile the output.")
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

    encoders, envelopes = load_specs(yaml_path)
    cases = build_cases(encoders, envelopes, input_path)
    compiler_cmd = resolve_compiler(args.compiler)

    results: list[TestResult] = []
    for case in cases:
        returncode, stdout, stderr = run_main(main_py, case.args)
        main_ok = returncode == 0
        main_error = "" if main_ok else (stderr.strip() or stdout.strip())
        compile_state = "skipped"
        compile_error = ""
        if main_ok:
            ok, compile_output = compile_cpp(compiler_cmd, stdout)
            if compiler_cmd:
                compile_state = "ok" if ok else "error"
            else:
                compile_state = "skipped"
            compile_error = "" if ok else compile_output
        else:
            compile_state = "skipped"
            compile_error = "Skipped due to main.py error"
        command = " ".join([sys.executable, main_py] + case.args)
        results.append(
            TestResult(
                case=case,
                main_ok=main_ok,
                main_error=main_error,
                compile_ok=compile_state,
                compile_error=compile_error,
                command=command,
            )
        )

    render_report(results, out_path, input_path, yaml_path, compiler_cmd)
    print(f"Wrote report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
