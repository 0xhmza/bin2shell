# bin2shell

Convert flat binaries into C/C++ source code that reconstructs the original bytes at runtime.

Each run can apply: a reversible **encoder** (XOR, RC4, TEA, XTEA, ChaCha20…), a printable **envelope** (Base64, Base91, Hex, UUID array, IPv4 array…), and an external **carrier** that hides the payload inside a fake PNG/BMP/ICO/INI file on disk.

Ships as a Python CLI (`main.py`) and a dark-mode WinForms GUI (`bin2shell.exe`).

## Features

- **Encoder pipeline** — reversible transforms; modern entries use per-build random keys (RC4, TEA, XTEA, ChaCha20, multi-byte XOR)
- **Envelope wrapping** — render encoded bytes as printable text (Base91, Base64, Base32, Base32Hex, Hex, Base58, Ascii85, IPv4-array, MAC-array, UUID-array)
- **External-file carriers** — package the encoded payload as a valid-looking `.png` / `.bmp` / `.ico` / `.ini`; the generated C++ reads the file at runtime and extracts the inner bytes
- **Web bundle mode** — emit a YAML package with a WinHTTP/WinINet/URLMon C++ template that fetches the payload over HTTP at runtime
- **YAML-driven playbook** — encoders, envelopes, and web helpers are declared in `data/yaml/algos.yaml`; carriers live in code (`bin2shell/carriers.py`) and are auto-listed in `--help`
- **GUI** — dark-mode WinForms front-end exposing every flag, including the carrier dropdown

## Project Structure

```
bin2shell/
  main.py                  # CLI entry point
  testing.py               # Test harness (encoder×envelope matrix + carriers)
  testing_web.py           # Test harness for web bundle mode
  bin2shell/
    cli.py                 # Argument parsing, generation pipeline, output
    playbook.py            # YAML playbook loader and snippet executor
    carriers.py            # External-file carriers (ini/png/bmp/ico)
    diversify.py           # Per-run symbol renamer + seed-based RNG
    formatting.py          # C array / string formatting utilities
    utils.py               # File I/O, terminal width
  data/yaml/
    algos.yaml             # Encoder, envelope, web-helper definitions
  ui/
    Bin2ShellUI.csproj     # .NET 8 WinForms project
    MainForm.cs            # Dark-mode GUI
    Program.cs             # Entry point
```

## Requirements

- Python 3.10+
- PyYAML (`pip install pyyaml`)
- .NET 8 SDK (for the GUI only)

## CLI Usage

```
bin2shell [-h] [-e N] [-v N] [-y PATH] [-w] [-wh N]
          [-c NAME|N] [-CarrierOut FILE] [-CarrierRuntimePath EXPR]
          [-o FILE] INPUT
```

| Flag | Description |
|------|-------------|
| `INPUT` | Path to the input binary file |
| `-e, --encoder N` | Encoder index (see list below) |
| `-v, --envelope N` | Envelope index (see list below) |
| `-y, --yaml PATH` | Path to algorithms YAML (default: `data/yaml/algos.yaml`) |
| `-w, --web` | Emit YAML bundle with web-fetch C++ template |
| `-wh, --web-helper N` | Web helper index (winhttp/wininet/urlmon) |
| `-c, --carrier NAME\|N` | Wrap payload in external file (`ini`, `png`, `bmp`, `ico`) |
| `-CarrierOut FILE` | Where to write the wrapped carrier file (default: derived from `-o`) |
| `-CarrierRuntimePath EXPR` | C++ expression for the runtime carrier path (default: basename literal) |
| `-o, --output FILE` | Write output to file instead of stdout |
| `-h, --help` | Show help and list every playbook entry |

### Available Algorithms

| Encoders | Envelopes |
|----------|-----------|
| `[0]` passthrough (raw bytes, no encoding) | `[0]` bare_bytes (raw byte array) |
| `[1]` static_xor_0x42 (fixed `0x42`) | `[1]` base91 |
| `[2]` rc4_static (fixed key) | `[2]` base64 |
| `[3]` xor_static_key (fixed key) | `[3]` base32 |
| `[4]` additive_shift_13 (add-13 mod 256) | `[4]` hex |
| `[5]` bit_rotate_left_3 (ROL 3) | `[5]` base58 |
| `[6]` **rc4_dynamic** (random 16-byte key) | `[6]` base85 |
| `[7]` **xor_dynamic** (random 16-byte key) | `[7]` ipv4_array |
| `[8]` **tea_ctr** (random 128-bit key, CTR) | `[8]` mac_array |
| `[9]` **xtea_ctr** (random 128-bit key, CTR) | `[9]` uuid_array |
| `[10]` **chacha20** (random 256-bit key + 96-bit nonce) | `[10]` base32hex |

| Carriers (`--carrier`) | Web helpers (`--web -wh`) |
|------------------------|---------------------------|
| `[0]` ini  (.ini, base64 under `[Settings]`) | `[0]` winhttp |
| `[1]` png  (.png, custom ancillary chunk `wMpL`) | `[1]` wininet |
| `[2]` bmp  (.bmp, payload after declared pixel block) | `[2]` urlmon |
| `[3]` ico  (.ico, payload after declared bitmap data) | |

### Examples

```bash
# Raw byte array (no encoding)
python main.py payload.bin -o output.cpp

# ChaCha20 + Base64
python main.py -e 10 -v 2 payload.bin -o out.cpp

# ChaCha20 + Base64 + hide payload inside a PNG
python main.py -e 10 -v 2 --carrier png payload.bin -o out.cpp

# Web bundle: emits YAML that fetches the payload over HTTP at runtime
python main.py -w -wh 0 -e 8 -v 2 payload.bin -o bundle.yaml
```

## External-file carriers

Carriers move the payload out of the source and onto disk in a file that looks innocuous:

| Carrier | What it produces |
|---------|------------------|
| **ini** | A normal-looking `[Settings]` block; payload is base64 under `data=` |
| **png** | A valid 1x1 PNG that decodes correctly; payload lives in a custom ancillary `wMpL` chunk |
| **bmp** | A valid 1x1 BMP; payload is appended after the declared pixel block |
| **ico** | A valid 1x1 ICO; payload is appended after the declared bitmap data |

The generated C++ opens the file at runtime, strips the carrier framing, then continues the normal envelope-decode → encoder-inverse pipeline. The runtime file path defaults to the basename of `-CarrierOut`; override with `-CarrierRuntimePath '"C:/data/license.png"'` for absolute paths.

`--carrier` and `--web` are mutually exclusive — the carrier reads from disk, the web bundle fetches over HTTP.

## GUI

A lightweight WinForms app with a dark Rufus-style interface. All CLI options are available through the UI, including the carrier dropdown.

### Build & Run

```bash
cd ui
dotnet build                          # Debug build
dotnet publish -c Release             # Single-file release (~175 KB)
```

The published exe goes to `ui/bin/Release/net8.0-windows/win-x64/publish/bin2shell.exe`.

### Deployment

Place `bin2shell.exe` in the project root alongside `main.py` and the `bin2shell/` and `data/` directories. On startup it checks for required files and shows an error if anything is missing.

Output defaults to `output_snippets/{filename}_{timestamp}.cpp_snippet`.

## Output Contract

### Native mode (default)

The generated C++ exposes:
- `unsigned char* code_blob` — the reconstructed original binary
- `unsigned int code_blob_len` — its length in bytes

When an envelope is used, the output includes `const char code_blob_text[]` plus inline decode logic that produces `enc_buf` / `enc_len`. The encoder inverse then reconstructs `code_blob` from `enc_buf`.

When a carrier is used, `code_blob_text[]` is replaced by a file-load block; `enc_buf` / `enc_len` (or `code_blob_text` / `code_blob_text_len` when an envelope is set) are produced from the file contents instead.

Encoder keys are emitted as `unsigned char` arrays with `_len` variables, regenerated per build.

### Web bundle mode (`--web`)

Emits YAML with:
- `cpp_includes` — required headers (e.g. WinHTTP)
- `cpp_web_fetch` — fetch helper functions
- `cpp_payload_init` — runtime URL fetch + length check
- `cpp_decode` — envelope decode + encoder inverse, wrapped in a lambda
- `payload` — the encoded payload (text or hex depending on envelope)
- `options` — encoder/envelope metadata + SHA-256 checksum of the raw payload

The generated template is Windows-only (WinHTTP / WinINet / URLMon).

## Playbook Format

`data/yaml/algos.yaml` entries are validated at load time.

**Encoders** require: `name`, `index`, `python_snippet`, `cpp_inverse`. Optional: `keys_snippet` (per-run key generation), `desc`.

**Envelopes** require: `name`, `index`, `python_snippet`, `cpp_decode`.

**Web helpers** require: `name`, `index`, `cpp_includes`, `cpp_fetch_bytes`, `cpp_fetch_text`.

Carriers are defined in `bin2shell/carriers.py` rather than YAML — they need both Python wrap logic and C++ unwrap templates, and shipping them as code makes them easier to test and review than nested heredocs.

Python snippets run at generation time; C++ snippets are emitted inline. Only use playbooks from trusted sources.

## Testing

`testing.py` runs the CLI across every encoder × envelope combination plus the carrier sweep, and compiles each output with the given compiler.

```bash
python testing.py --out report.html
python testing.py --compiler "C:\Program Files\LLVM\bin\clang++.exe" --out report.html
```

`testing_web.py` covers the web bundle mode across every encoder × envelope × web-helper combination.

```bash
python testing_web.py --out report_web.html
```

## License

See [LICENSE](LICENSE) for details.


## Features

- **Encoder pipeline** — reversible transforms; modern entries use per-build random keys (RC4, TEA, XTEA, ChaCha20, multi-byte XOR)
- **Envelope wrapping** — render encoded bytes as printable text (Base91, Base64, Base32, Base32Hex, Hex, Base58, Ascii85, IPv4-array, MAC-array, UUID-array)
- **External-file carriers** — package the encoded payload as a valid-looking `.png` / `.bmp` / `.ico` / `.ini`; the generated C++ reads the file at runtime and extracts the inner bytes
- **Polymorphism** — per-run symbol-renamer so generated sources don't share signatures across builds; optional `--seed` for reproducible CI snapshots
- **Web bundle mode** — emit a YAML package with a WinHTTP/WinINet/URLMon C++ template that fetches the payload over HTTP at runtime
- **YAML-driven catalog** — encoders, envelopes, and web helpers are declared in `data/yaml/algos.yaml`; carriers live in code (`bin2shell/carriers.py`) and are auto-listed in `--help`
- **GUI** — dark-mode WinForms front-end exposing every flag, including carrier + polymorphism

## Project Structure

```
bin2shell/
  main.py                  # CLI entry point
  testing.py               # Test harness (encoder×envelope matrix + carriers)
  bin2shell/
    cli.py                 # Argument parsing, generation pipeline, output
    catalog.py             # YAML catalog loader and snippet executor
    carriers.py            # External-file carriers (ini/png/bmp/ico)
    polymorphism.py        # Per-run symbol renamer + seed-based RNG
    formatting.py          # C array / string formatting utilities
    utils.py               # File I/O, terminal width
  data/yaml/
    algos.yaml             # Encoder, envelope, web-helper definitions
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
bin2shell [-h] [-e N] [-v N] [-y PATH] [-w] [-wh N]
          [-c NAME|N] [--carrier-out FILE] [--carrier-runtime-path EXPR]
          [--seed N] [--poly L]
          [-o FILE] INPUT
```

| Flag | Description |
|------|-------------|
| `INPUT` | Path to the input binary file |
| `-e, --encoder N` | Encoder index (see list below) |
| `-v, --envelope N` | Envelope index (see list below) |
| `-y, --yaml PATH` | Path to algorithms YAML (default: `data/yaml/algos.yaml`) |
| `-w, --web` | Emit YAML bundle with web-fetch C++ template |
| `-wh, --web-helper N` | Web helper index (winhttp/wininet/urlmon) |
| `-c, --carrier NAME\|N` | Wrap payload in external file (`ini`, `png`, `bmp`, `ico`) |
| `--carrier-out FILE` | Where to write the wrapped carrier file (default: derived from `-o`) |
| `--carrier-runtime-path EXPR` | C++ expression for the runtime carrier path (default: basename literal) |
| `--seed N` | Seed the polymorphism RNG (accepts `0x…` hex) for reproducible builds |
| `--poly L` | Polymorphism level: `0` off, `1` rename internals (default), `2` + reorder, `3` + junk locals |
| `-o, --output FILE` | Write output to file instead of stdout |
| `-h, --help` | Show help and list every catalog entry |

### Available Algorithms

| Encoders | Envelopes |
|----------|-----------|
| `[0]` none (pass-through) | `[0]` none (bare byte array) |
| `[1]` xor42 (fixed `0x42`) | `[1]` base91 |
| `[2]` rc4 (fixed key, legacy) | `[2]` base64 |
| `[3]` xor_key (fixed key, legacy) | `[3]` base32 |
| `[4]` caesar (add-13) | `[4]` hex |
| `[5]` rol3 (rotate-left-3) | `[5]` base58 |
| `[6]` **rc4_random** (random 16-byte key) | `[6]` base85 |
| `[7]` **xor_random** (random 16-byte key) | `[7]` ipv4_array |
| `[8]` **tea** (random 128-bit key, CTR mode) | `[8]` mac_array |
| `[9]` **xtea** (random 128-bit key, CTR mode) | `[9]` uuid_array |
| `[10]` **chacha20** (random 256-bit key + 96-bit nonce) | `[10]` base32hex |

| Carriers (`--carrier`) | Web helpers (`--web -wh`) |
|------------------------|---------------------------|
| `[0]` ini  (.ini, base64 under `[Settings]`) | `[0]` winhttp |
| `[1]` png  (.png, custom ancillary chunk `wMpL`) | `[1]` wininet |
| `[2]` bmp  (.bmp, payload after declared pixel block) | `[2]` urlmon |
| `[3]` ico  (.ico, payload after declared bitmap data) | |

### Examples

```bash
# Raw byte array (no encoding)
python main.py payload.bin -o output_snippets/payload.cpp

# ChaCha20 + Base64
python main.py -e 10 -v 2 payload.bin -o out.cpp

# ChaCha20 + Base64 + hide payload inside a PNG (writes payload.png alongside out.cpp)
python main.py -e 10 -v 2 --carrier png payload.bin -o out.cpp

# Same, with a reproducible random seed and full polymorphism
python main.py -e 10 -v 2 --carrier png --seed 0xCAFEBABE --poly 1 payload.bin -o out.cpp

# Web bundle: emits YAML that fetches the payload over HTTP at runtime
python main.py -w -wh 0 -e 8 -v 2 payload.bin -o bundle.yaml
```

## Polymorphism

Every run defaults to `--poly 1`: a per-run-random symbol renamer rewrites internal identifiers (`enc_buf`, `enc_len`, key arrays, the bootstrap struct/lambda) to fresh names like `_b9xkz1`, `_ka2lf7`. The **public** symbols emitted at file scope — `code_blob` and `code_blob_len` — never change so downstream consumers keep working.

Add `--seed 0xDEADBEEF` (or any integer) to make the output deterministic across runs. The first line of every generated file echoes the seed so you can reproduce a specific build from its source.

`--poly 0` disables the renamer entirely.

## External-file carriers

Carriers move the payload out of the source and onto disk in a file that looks innocuous:

| Carrier | What it produces |
|---------|------------------|
| **ini** | A normal-looking `[Settings]` block; payload is base64 under `data=` |
| **png** | A valid 1x1 PNG that decodes correctly; payload lives in a custom ancillary `wMpL` chunk |
| **bmp** | A valid 1x1 BMP; payload is appended after the declared pixel block |
| **ico** | A valid 1x1 ICO; payload is appended after the declared bitmap data |

The generated C++ opens the file at runtime, strips the carrier framing, then continues the normal envelope-decode → encoder-inverse pipeline. The runtime file path defaults to the basename of `--carrier-out`; override with `--carrier-runtime-path '"C:/data/license.png"'` for absolute paths.

`--carrier` and `--web` are mutually exclusive — the carrier reads from disk, the web bundle fetches over HTTP.

## GUI

A lightweight WinForms app with a dark Rufus-style interface. All CLI options are available through the UI, including the carrier dropdown, polymorphism level, and optional seed.

### Build & Run

```bash
cd ui
dotnet build                          # Debug build
dotnet publish -c Release             # Single-file release (~175 KB)
```

The published exe goes to `ui/bin/Release/net8.0-windows/win-x64/publish/bin2shell.exe`.

### Deployment

Place `bin2shell.exe` in the project root alongside `main.py` and the `bin2shell/` and `data/` directories. On startup it checks for required files and shows an error if anything is missing.

Output defaults to `output_snippets/{filename}_{timestamp}.cpp_snippet`.

## Output Contract

### Native mode (default)

The generated C++ exposes:
- `unsigned char* code_blob` — the reconstructed original binary
- `unsigned int code_blob_len` — its length in bytes

When an envelope is used, the output includes `const char code_blob_text[]` plus inline decode logic that produces `enc_buf` / `enc_len`. The encoder inverse then reconstructs `code_blob` from `enc_buf`.

When a carrier is used, `code_blob_text[]` is replaced by a file-load block; `enc_buf` / `enc_len` (or `code_blob_text` / `code_blob_text_len` when an envelope is set) are produced from the file contents instead.

Encoder keys are emitted as `unsigned char` arrays with `_len` variables, regenerated per build.

### Web bundle mode (`--web`)

Emits YAML with:
- `cpp_includes` — required headers (e.g. WinHTTP)
- `cpp_web_fetch` — fetch helper functions
- `cpp_payload_init` — runtime URL fetch + length check
- `cpp_decode` — envelope decode + encoder inverse, wrapped in a lambda
- `payload` — the encoded payload (text or hex depending on envelope)
- `options` — encoder/envelope metadata + SHA-256 checksum of the raw payload

The generated template is Windows-only (WinHTTP / WinINet / URLMon).

## Catalog Format

`data/yaml/algos.yaml` entries are validated at load time.

**Encoders** require: `name`, `index`, `python_snippet`, `cpp_inverse`. Optional: `keys_snippet` (per-run key generation), `desc`.

**Envelopes** require: `name`, `index`, `python_snippet`, `cpp_decode`.

**Web helpers** require: `name`, `index`, `cpp_includes`, `cpp_fetch_bytes`, `cpp_fetch_text`.

Carriers are defined in `bin2shell/carriers.py` rather than YAML — they need both Python wrap logic and C++ unwrap templates, and shipping them as code makes them easier to test and review than nested heredocs.

Python snippets run at generation time; C++ snippets are emitted inline. Only use catalogs from trusted sources.

## Testing

`testing.py` runs the CLI across every encoder × envelope combination plus the carrier sweep, and compiles each output with the given compiler.

```bash
python testing.py --out report.html
python testing.py --compiler "C:\Program Files\LLVM\bin\clang++.exe" --out report.html
```

Current matrix: **148 cases** (1 simple + 11 encoders × 11 envelopes + 22 default fallbacks + 4 carrier sweeps). With `--compiler` set, every generated `.cpp` is compiled as a translation unit.

## License

See [LICENSE](LICENSE) for details.
