# bin2shell

Convert flat binaries into C/C++ source code that reconstructs the original bytes at runtime. Optionally encode the data with per-run keys and wrap it in a printable envelope. Includes a GUI for Windows.

## Features

- **Encoder pipeline** - reversible transforms using random per-run keys (XOR, double-XOR, ARX, double-ARX)
- **Envelope wrapping** - render encoded bytes as printable text (Base91, Base64, Base32)
- **C++ code generation** - emits self-contained code with `code_blob` / `code_blob_len` that reverses the full pipeline
- **Web bundle mode** - outputs a YAML package with a WinHTTP-based C++ template and payload metadata
- **YAML-driven catalog** - encoders, envelopes, and their C++ inverse snippets are all defined in `data/yaml/algos.yaml`
- **GUI** - dark-mode WinForms app (Rufus-style) with all options exposed

## Project Structure

```
bin2shell/
  main.py                  # CLI entry point
  testing.py               # Test harness (all encoder x envelope combos)
  bin2shell/
    cli.py                 # Argument parsing, C++ generation, output
    catalog.py             # YAML catalog loader and snippet executor
    formatting.py          # C array / string formatting utilities
    utils.py               # File I/O, terminal width
  data/yaml/
    algos.yaml             # Encoder and envelope definitions
  ui/
    Bin2ShellUI.csproj     # .NET 8 WinForms project
    MainForm.cs            # Dark-mode GUI
    Program.cs             # Entry point
  output_snippets/         # Default output directory (gitignored)
```

## Requirements

- Python 3.10+
- PyYAML (`pip install pyyaml`)
- .NET 8 SDK (for the GUI only)

## CLI Usage

```
bin2shell [-h] [-e N] [-v N] [-y PATH] [-w] [-o FILE] INPUT
```

| Flag | Description |
|------|-------------|
| `INPUT` | Path to the input binary file |
| `-e, --encoder N` | Encoder index (see `--help` for list) |
| `-v, --envelope N` | Envelope index (see `--help` for list) |
| `-y, --yaml PATH` | Path to algorithms YAML (default: `data/yaml/algos.yaml`) |
| `-w, --web` | Emit YAML bundle with web-fetch C++ template |
| `-o, --output FILE` | Write output to file instead of stdout |
| `-h, --help` | Show help and list available algorithms |

### Available Algorithms

| Encoders | Envelopes |
|----------|-----------|
| `[0]` none (pass-through) | `[0]` none (bare byte array) |
| `[1]` xor (single 16-byte key) | `[1]` base91 |
| `[2]` xor2 (double XOR, two keys) | `[2]` base64 |
| `[3]` arx8 (add-rotate-XOR) | `[3]` base32 |
| `[4]` arx82 (double ARX) | |

### Examples

```bash
# Raw byte array (no encoding)
python main.py payload.bin -o output_snippets/payload.cpp_snippet

# XOR encoder + Base91 envelope
python main.py -e 1 -v 1 payload.bin -o output_snippets/payload.cpp_snippet

# Double ARX + Base64, write to file
python main.py -e 4 -v 2 -o out.cpp payload.bin

# Web bundle mode
python main.py -w -e 1 -v 2 payload.bin -o bundle.yaml
```

## GUI

A lightweight WinForms app with a dark Rufus-style interface. All CLI options are available through the UI.

### Build & Run

```bash
cd ui
dotnet build                          # Debug build
dotnet publish -c Release             # Single-file release (~174 KB)
```

The published exe goes to `ui/bin/Release/net8.0-windows/win-x64/publish/bin2shell.exe`.

### Deployment

Place `bin2shell.exe` in the project root alongside `main.py` and the `bin2shell/` and `data/` directories. On startup it checks for required files and shows an error if anything is missing.

Output defaults to `output_snippets/{filename}_{timestamp}.cpp_snippet`.

## Output Contract

### Native mode (default)

The generated C++ exposes:
- `unsigned char* code_blob` - the reconstructed original binary
- `unsigned int code_blob_len` - its length in bytes

When an envelope is used, the output includes `const char code_blob_text[]` plus inline decode logic that produces `enc_buf` / `enc_len`. The encoder inverse then reconstructs `code_blob` from `enc_buf`.

Encoder keys are emitted as `unsigned char` arrays with `_len` variables.

### Web bundle mode (`--web`)

Emits YAML with:
- `code_template` - C++ template using WinHTTP to fetch the payload at runtime
- `payload` - the encoded payload (text or hex depending on envelope)
- `payload_checksum` - SHA-256 of the raw payload bytes
- `options` - encoder/envelope metadata

The generated template is Windows-only (WinHTTP).

## Catalog Format

`data/yaml/algos.yaml` entries are validated at load time.

**Encoders** require: `name`, `index`, `python_snippet`, `cpp_inverse`

**Envelopes** require: `name`, `index`, `python_snippet`, `cpp_decode`

Optional fields: `keys_snippet` (per-run key generation), `desc`, `emit`, `args`

Python snippets run at generation time; C++ snippets are emitted inline. Only use catalogs from trusted sources.

## Testing

`testing.py` runs the CLI across every encoder/envelope combination and compiles the output (object-only). Writes an HTML report.

```bash
python testing.py --out report.html
python testing.py --compiler g++ --input payload.bin
```

## License

See [LICENSE](LICENSE) for details.
