# bin2shell

bin2shell converts a flat binary into C/C++ source that reconstructs the bytes at runtime. It can optionally
encode the data and wrap it in a printable envelope, and it can emit a YAML bundle for web fetch scenarios.

## Requirements
- Python 3.10+
- PyYAML (`pip install pyyaml`)

## How it works
1. Encode (optional): reversible transform using per-run keys (XOR/ARX).
2. Envelope (optional): render bytes as printable text (Base91/Base64/Base32).
3. Emit C++ that reverses the pipeline and exposes `code_blob` and `code_blob_len`.

Encoders and envelopes are defined in `data/yaml/algos.yaml`. Each entry includes a Python snippet for the
forward transform and a matching C++ snippet for the inverse/decode.

## CLI reference
```text
Usage:
  python main.py [options] <input_file>

Arguments:
  input_file                 Path to the input binary file.

Options:
  -y, --yaml <yaml_path>             Path to algorithms YAML (default: data/yaml/algos.yaml)
  -e, --encoding <encoder_index>     Encoder index
  -env, --envelope <envelope_index>  Envelope index (alias: --envelop)
  -w, --web                          Emit YAML bundle with web-fetch C++ template
  -h, --help                         Show help and list available algorithms
```

`python main.py -h` prints the full help block and the catalog entries.

## Examples
- Minimal output (raw byte array):
```bash
python main.py messagebox.bin > payload.cpp
```

- XOR + Base91:
```bash
python main.py --encoding 1 --envelope 1 messagebox.bin > payload.cpp
```

- Custom YAML:
```bash
python main.py --yaml ./config/algos.yaml --encoding 2 --envelope 3 payload.bin > payload.cpp
```

- Web bundle output:
```bash
python main.py --web --encoding 1 --envelope 2 payload.bin > bundle.yaml
```

## Output contract (native mode)
- `unsigned char code_blob[]` and `unsigned int code_blob_len`.
- When an envelope is used, output includes `const char code_blob_text[]` plus inline decode logic
  that fills `enc_buf` and `enc_len`.
- Encoder keys are emitted as byte arrays with accompanying `<name>_len` variables.
- The inverse encoder logic reconstructs `code_blob` from `enc_buf`.

## Web bundle output
`--web` emits YAML with the following fields:
- `code_template`: C++ template that fetches the payload and reconstructs `code_blob`.
- `payload`: encoded payload (text or hex, depending on envelope).
- `payload_checksum`: SHA-256 checksum of the payload.
- `options`: encoder/envelope metadata and the web flag.

The generated template uses WinHTTP and is Windows-only.

## Catalog format
`data/yaml/algos.yaml` entries are validated at runtime.

Encoders must include:
- `name`, `index`, `python_snippet`, `cpp_inverse`

Envelopes must include:
- `name`, `index`, `python_snippet`, `cpp_decode`

Optional fields:
- `keys_snippet`: Python generator for per-run keys.
- `emit`: metadata for downstream tooling.
- `args`: argument names for help output.

## Security note
Python snippets from the YAML are executed. Only use catalogs from trusted sources.

## Testing
`testing.py` runs the CLI across every encoder/envelope combination and compiles the emitted C++ (object-only).
It writes an HTML report with per-case execution and compilation errors.
```bash
python testing.py --out report.html
```
