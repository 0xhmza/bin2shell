# bin2shell

**bin2shell** takes a flat binary as input and generates C/C++ source that reconstructs it at runtime.

You can optionally encode the bytes and wrap them in an envelope (for example Base91 or Base64) before embedding. The YAML catalog (default `data/yaml/algos.yaml`) keeps the system extensible: add or modify encoders and envelopes without touching the Python.

---

## Usage
```bash
python main.py [-y <yaml>] [-e <enc_idx>] [-env <env_idx>] <file>
```

## Options
- `-y, --yaml <path>`  
  Path to the algorithms YAML (default: `data\yaml\algos.yaml` relative to the current working directory).
- `-e, --encoding <idx>`  
  Encoder index (see the catalog listing below).
- `-env, --envelop <idx>`  
  Envelope index.
- `-h, --help`  
  Show help.

---

## YAML-driven catalog (default entries)
> Index numbers come from the default YAML and line up with the CLI flags.

**Encoders**
```
[0] none   - Pass-through
[1] xor
[2] xor2
[3] arx8
[4] arx82
```

**Envelopes**
```
[0] none   - Emit raw byte array
[1] base91
[2] base64
[3] base32
```

---

## Examples

- Minimal (defaults to encoder 0 / envelope 0):
```bash
python main.py payload.bin
```

- Encode with XOR and wrap in Base91:
```bash
python main.py -e 1 -env 1 payload.bin
```

- Use a custom YAML and Base32 envelope:
```bash
python main.py -y ./config/algos.yaml -e 2 -env 3 payload.bin
```

---

## Notes
- The YAML catalog stores both metadata and C++ snippets. Edit it to swap or add encoders/envelopes.
- If an algorithm feels weak or fingerprintable, replace it in the YAML or add your own entry.
