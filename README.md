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
- **GUI**: A simple dark not very cute Winforms, in case you like buttons over CLI (you rather not).

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
### Example Output

```powershell
python .\main.py .\messagebox.bin -e 7
```

```c
// Random XOR key
unsigned char xor_key[] = { 0xda, 0xb2, 0x84, 0xe3, 0x8a, 0x0e, 0x3a, 0xfa, 0x30, 0xc8, 0x39, 0xff, 0xc1, 0xb7, 0xb7, 0x75
};
unsigned int xor_key_len = 16;
unsigned int code_blob_expected_len = 433;

// Encoded payload - Encoded using "[7] xor_dynamic" from the playbook.
unsigned char enc_buf[] = { 0x92, 0x31, 0x68, 0xcb, 0xc2, 0x8d, 0xde, 0x0a, 0x78, 0x45, 0x2c, 0x99, 0xc1, 0xb7, 0xb7, 0x3d, 0x57, 0xbf, 0xd6, 0xe3, 0x8a, 0x0e, 0xd2, 0x64, 0x30, 0xc8, 0x39, 0xb3, 0x4a, 0x4f,
  0xff, 0xf8, 0xd7, 0xef, 0x84, 0xe3, 0x8a, 0xf1, 0xea, 0xb2, 0xbd, 0xdd, 0x66, 0xff, 0xc1, 0xb7, 0xff, 0xf8, 0xd7, 0xff, 0x84, 0xe3, 0x8a, 0xe6, 0x45, 0xfa, 0x30, 0xc8, 0x74, 0xcc, 0x08, 0xfb, 0x3a, 0x70,
  0xbb, 0xb2, 0x84, 0xe3, 0xc2, 0x83, 0x2f, 0xb4, 0x30, 0xc8, 0x39, 0xb7, 0xf2, 0x7e, 0x48, 0xa5, 0x92, 0x3f, 0x91, 0xb5, 0x8a, 0x0e, 0x3a, 0xb2, 0xbd, 0xc5, 0x33, 0xff, 0xc1, 0xb7, 0x5f, 0x23, 0xda, 0xb2,
  0x84, 0xab, 0xb9, 0xc7, 0xc5, 0x2a, 0x7b, 0x8d, 0x6b, 0xb1, 0x84, 0xfb, 0x84, 0x47, 0xf4, 0xf6, 0xc8, 0xaf, 0x8a, 0x42, 0x55, 0x9b, 0x54, 0x84, 0x50, 0x9d, 0xb3, 0xd6, 0xc5, 0x0c, 0x9b, 0xb2, 0xd1, 0xb0,
  0xcf, 0x5c, 0x09, 0xc8, 0x1e, 0x8c, 0x75, 0xb3, 0xc1, 0xfa, 0xd2, 0x06, 0xa9, 0xd3, 0xe3, 0x86, 0xc8, 0x61, 0x42, 0xbb, 0x30, 0x80, 0x5c, 0x93, 0xad, 0xd8, 0x97, 0x02, 0xb5, 0xc0, 0xe8, 0x87, 0x8a, 0x43,
  0x5f, 0x89, 0x43, 0xa9, 0x5e, 0x9a, 0xc1, 0xf2, 0xcf, 0x1c, 0xae, 0xe2, 0xf6, 0x8c, 0xe9, 0x6b, 0x49, 0x89, 0x30, 0x80, 0xba, 0x13, 0xe9, 0xd2, 0xfb, 0xfe, 0xde, 0x97, 0xe4, 0xe3, 0x8a, 0x0e, 0x77, 0x71,
  0x70, 0xd0, 0x74, 0x72, 0xa1, 0xa7, 0xfa, 0xfe, 0xde, 0x96, 0x78, 0xaa, 0x01, 0x76, 0x5a, 0xb2, 0xbb, 0x39, 0x95, 0x7b, 0x01, 0xc3, 0x91, 0xff, 0xfd, 0x32, 0x78, 0x82, 0xf6, 0x0d, 0xba, 0x16, 0x10, 0xf2,
  0xd9, 0x8a, 0xc9, 0xff, 0x48, 0xb2, 0x92, 0x4d, 0x43, 0x08, 0x6f, 0x43, 0xb1, 0xfa, 0x7d, 0xf3, 0xfd, 0x8a, 0x17, 0xff, 0x84, 0xb5, 0x33, 0x15, 0x84, 0xe3, 0x8a, 0x47, 0xb1, 0xa2, 0x00, 0x8c, 0xb2, 0xb4,
  0xfd, 0xfb, 0xb4, 0xbe, 0x93, 0x33, 0x45, 0x6b, 0x8a, 0x0e, 0x3a, 0xbf, 0xbb, 0xe1, 0x74, 0x7a, 0x2c, 0xc2, 0xbf, 0x3d, 0xe9, 0x72, 0x6d, 0x66, 0x8a, 0x0e, 0x3a, 0xb4, 0xbd, 0xcc, 0x12, 0xba, 0x4a, 0xc6,
  0xb3, 0x38, 0xd9, 0x47, 0xc5, 0x68, 0xc2, 0x16, 0x7f, 0x71, 0x60, 0xe8, 0x75, 0xfc, 0x12, 0x48, 0x7e, 0x38, 0x57, 0xbe, 0x0e, 0xa2, 0x01, 0x37, 0x72, 0xf9, 0xcb, 0x80, 0xb2, 0x0d, 0x67, 0xc2, 0xbf, 0xff,
  0xdc, 0x36, 0x44, 0x97, 0x83, 0xe5, 0xcf, 0x18, 0xd6, 0x80, 0x0a, 0x3f, 0x2a, 0xf9, 0xf2, 0xfe, 0x92, 0x96, 0xc8, 0xe0, 0x41, 0x68, 0x7b, 0x71, 0x3c, 0x81, 0x7c, 0x74, 0x89, 0xab, 0xfb, 0x76, 0x11, 0xf3,
  0x0f, 0xe7, 0x03, 0x47, 0x01, 0x3f, 0x4c, 0xe7, 0x70, 0xc4, 0x07, 0xc4, 0x9d, 0x3d, 0x57, 0x86, 0x9c, 0xab, 0x07, 0x72, 0x1e, 0xca, 0x7c, 0x43, 0xde, 0x5b, 0x41, 0x89, 0x99, 0x00, 0x20, 0x16, 0x43, 0xe4,
  0xce, 0x42, 0x76, 0xfa, 0x79, 0x43, 0xf5, 0xbe, 0x3e, 0x60, 0xfe, 0xfe, 0x16, 0xfa, 0x0f, 0x35, 0x63, 0x1a, 0xc5, 0x05, 0xcf, 0x80, 0x3a, 0x3c, 0x89, 0x34, 0x73, 0x5d, 0x19
}; 
unsigned int enc_len = 433;

struct Bin2ShellPayload {
    unsigned char* code_blob;
    unsigned int code_blob_len;
};

// Payload decoding - Decoded using "[7] xor_dynamic" decoding .c code from the playbook.
static Bin2ShellPayload bin2shell_payload = []() {

    // ---- inline inverse encoding ----
    // Multi-byte XOR with random per-build key
    for (unsigned int i = 0; i < enc_len; ++i) {
        enc_buf[i] ^= xor_key[i % xor_key_len];
    }

    // Assign the decoded buffer to code_blob
    unsigned char* code_blob = enc_buf;
    unsigned int code_blob_len = enc_len;

    return Bin2ShellPayload{code_blob, code_blob_len};
}();

// The payload you can use later in your loader
unsigned char* code_blob = bin2shell_payload.code_blob; // Array of the decoded bytes 
unsigned int code_blob_len = bin2shell_payload.code_blob_len; // Array's length (nececssary for memory reservation)
```

One more example, the same messagebox.bin will be xor encrypted, but also will be converted into base91. So we have two passes: .bin -> xor -> base91

```bash
python .\main.py .\messagebox.bin -e 7 -v 1
```

```c
unsigned char xor_key[] = { 0x3e, 0x7d, 0xb7, 0xae, 0x9d, 0xed, 0x1c, 0xe6, 0x41, 0x97, 0xad, 0x19, 0x12, 0xa3, 0x81, 0x94
};
unsigned int xor_key_len = 16;
unsigned int code_blob_expected_len = 433;

//base91(random_xor(messagebox.bin)):
const char code_blob_text[] =
"#`I1N8ovEx4k>{tG3E]{X?/^&.o:zQR1~8\"@1zoR9y$%nd*,9ju4WSZRq@?,@@n9.P%1fudDy0c(:L3hH&>lJ)Tty4L$<Odl6MkK0Y3>+p>$tf`6^y<k$uv:Xg}%hjbT)yA\"m9uQcdY@xhv3U3liJ$T&|Q/.U~LsG_1{0hF~Q]+ed)t@KnsCd1PQ!!dC:JmpNj([15U!9@?t"
"39,R<e~3,,5>R6ZHD<Pwb8Z/|g79>?&syC&;t^jr@<m_rnN,[0QL}+M:JQ.+9ez2d4F:FWSZ~|F{#n#o%L}83i<*X~1j`W7HaFd1ak5lW<S&pf:gj}n9~Mf6\"?kmoOh&v_}p8$@ZI=uR5jFu8`2;Z@%X5&I:+pm4)qdvf,Bp|!hug}(dFWpm[$=$,tEvT^]*q[FI26P%d((!/"
"f<NfB6|p:I6>/sndnDkW(W*V!i;eg.#p9@S+J8zS}2`#]=)_d)ytjtVZNGD=4a,5<u&MKBzu!TBL0lP%.iv]T!nR.UO|,$(GR,#MFQL(9aF^[gWyE7sRe{fmOFn#"
;
unsigned int code_blob_text_len = 533;

struct Bin2ShellPayload {
    unsigned char* code_blob;
    unsigned int code_blob_len;
};

static Bin2ShellPayload bin2shell_payload = []() {

    // ---- inline envelope decode ----
    const char* B91_ALPH = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,./:;<=>?@[]^_`{|}~\"";
    int b91_dec[256];
    for (int i = 0; i < 256; ++i) b91_dec[i] = -1;
    for (int i = 0; i < 91; ++i) b91_dec[(unsigned char)B91_ALPH[i]] = i;

    unsigned int enc_cap = (code_blob_text_len * 13u) / 14u + 8u;
    unsigned char* enc_buf = new unsigned char[enc_cap];
    unsigned int enc_len = 0;

    unsigned int b = 0, n = 0;
    int v = -1;
    for (unsigned int i = 0; i < code_blob_text_len; ++i) {
        unsigned char c = (unsigned char)code_blob_text[i];
        int d = (c < 256) ? b91_dec[c] : -1;
        if (d < 0) continue;
        if (v < 0) v = d;
        else {
            v += d * 91;
            b |= (unsigned int)v << n;
            n += ((v & 8191) > 88) ? 13u : 14u;
            do {
                enc_buf[enc_len++] = (unsigned char)(b & 0xFFu);
                b >>= 8u;
                n -= 8u;
            } while (n > 7u);
            v = -1;
        }
    }
    if (v >= 0) {
        enc_buf[enc_len++] = (unsigned char)((b | (unsigned int)v << n) & 0xFFu);
    }

    // ---- inline inverse encoding ----
    // Multi-byte XOR with random per-build key
    for (unsigned int i = 0; i < enc_len; ++i) {
        enc_buf[i] ^= xor_key[i % xor_key_len];
    }

    // Assign the decoded buffer to code_blob
    unsigned char* code_blob = enc_buf;
    unsigned int code_blob_len = enc_len;

    return Bin2ShellPayload{code_blob, code_blob_len};
}();

unsigned char* code_blob = bin2shell_payload.code_blob;
unsigned int code_blob_len = bin2shell_payload.code_blob_len;
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
