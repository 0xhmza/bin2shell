# bin2shell

A flat binary to C++ code reconstructor, powered by templates and playbooks.

Each run can apply: a reversible **encoder** (XOR, RC4, TEA, XTEA, ChaCha20…), a printable **envelope** (Base64, Base91, Hex, UUID array, IPv4 array…), and an external **carrier** that hides the payload inside a fake PNG/BMP/ICO/INI file on disk.

Ships as a Python CLI (`main.py`) and a basic WinForms GUI (`bin2shell.exe`).

## Features

- **Encoder pipeline**: Reversible transforms; modern entries use per-build random keys (RC4, TEA, XTEA, ChaCha20, multi-byte XOR)
- **Envelope wrapping**: Render encoded bytes as printable text (Base91, Base64, Base32, Base32Hex, Hex, Base58, Ascii85, IPv4-array, MAC-array, UUID-array)
- **External-file carriers**: Package the encoded payload as a valid-looking `.png` / `.bmp` / `.ico` / `.ini`; the generated C++ reads the file at runtime and extracts the inner bytes
- **Web bundle mode**: Emit a YAML package with a WinHTTP/WinINet/URLMon C++ template that fetches the payload over HTTP at runtime
- **YAML-driven playbook**: Declare encoders, envelopes, and web helpers in data/yaml/algos.yaml. Carriers reside in bin2shell/carriers.py and are automatically listed in --help. You can add your own code—just follow the YAML structure to reuse your functions and automate your pipeline with ease.
- **GUI** — dark-mode WinForms front-end exposing every flag, including the carrier dropdown

## Requirements

- Python 3.10+
- PyYAML (`pip install pyyaml`)
- .NET 8 SDK (for the GUI)

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

You can easily add your own entries into the .yaml file! And thanks to LLMs, it's never been easier :)

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

`--carrier` and `--web` are mutually exclusive. The carrier reads from disk, the web bundle fetches over HTTP.

## GUI

A lightweight WinForms app. All CLI options are available through the UI, including the carrier dropdown.

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

The generated template is ofc Windows-only (WinHTTP / WinINet / URLMon).

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

### Disclaimer: For Educational & Authorized Use Only

This project is designed solely for educational purposes and legitimate red teaming engagements with explicit written authorization from the target system owner. Its goal is to help security professionals automate common red team workflows. Unauthorized use is illegal. You assume all liability.

### License: PolyForm Noncommercial License 1.0.0
