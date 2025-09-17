# bin2shell

**bin2shell** takes a flat binary as an input and generates C/C++ source that reconstructs the flat binary at runtime.  

You can optionally compress, encode and envelope the binary's binary code. You can also add some anti-emulation techniques. 

All available algorithms and small C++ snippets live in a YAML catalog (by default under `data/yaml/algos.yaml`). The YAML makes the system fully **extensible** — add or modify encoders, compressors, envelopes, and anti-emulation snippets without changing the core script.

---

## Usage
```bash
python main.py [-y <yaml>] [-e <enc_idx>]  [-c <comp_idx>]  [-env <env_idx>] [-ae <method>] [a:b:c:..] <file>
```

## Options
- `-y, --yaml <path>`  
  Path to algorithms YAML (default: `data\yaml\algos.yaml` relative to current working directory).
- `-e, --encoding <idx>`  
  Encoder index (select an encoder from the YAML table).
- `-c, --compression <idx>`  
  Compressor index.
- `-env, --envelop <idx>`  
  Envelope index.
- `-ae, --entiemulation <method>`  
  Select a YAML snippet under the `anti-emulation` section. Inserted into the emitted code as `{ANTI-EMULATION-SNIPPET}`.
- `[a:b:c:..]`  
  Colon-separated arguments for the selected YAML snippet (must match the snippet's declared `args`).
- `-h, --help`  
  Show help.

---

## Arguments
Use `--args` to pass runtime values into YAML snippets that contain placeholders. Format: `--args a:b[:c]`.

Examples:
- Inject a sleep duration:
  ```bash
  python main.py -s thread_ms --args 3000 payload.bin
  ```
- Configure the `siralloc` stub:
  ```bash
  python main.py -s siralloc --args 32:10 payload.bin
  ```
  In this case `PAYLOAD_LEN` in the snippet maps to `code_blob_len` — see the YAML snippet for the exact placeholder names.

---

## YAML-driven catalog (available items)
> The following list comes from the default YAML catalog. Index numbers are the YAML indices used by CLI flags.

**Encoders**
```
[0] none   — No encoding (pass-through)
[1] xor
[2] xor2
[3] arx8
[4] arx82
```

**Compressors**
```
[0] none
[1] pair
```

**Envelopes**
```
[0] none   — Emit raw byte array (no envelope)
[1] base91
[2] base64
[3] base32
```

**Anti-Emulation**
- `[1] spin`  
  Busy-wait loop for N iterations.  
  **Args:** `duration` (iterations)  
- `[2] siralloc`  
  Allocate `SIR_ALLOC_COUNT` heap buffers of `PAYLOAD_LEN` bytes and repeat writes for `SIR_ITERATION_COUNT` iterations.  
  **Args:** `SIR_ALLOC_COUNT:SIR_ITERATION_COUNT`  
  Note: `PAYLOAD_LEN` in the snippet maps to the generated `code_blob_len`.

---

## Examples

- Minimal (use defaults: none for enc/compr/env):
```bash
python main.py payload.bin
```

- Compress with index `1`, encode with XOR (index `1`), and envelope with Base91 (index `1`):
```bash
python main.py -c 1 -e 1 -env 1 payload.bin
```

- Use a custom YAML and inject a sleep snippet with args:
```bash
python main.py -y ./config/algos.yaml -e 2 -c 1 -env 3 -s siralloc --args 16:5 payload.bin
```

---

## Notes & tips
- The YAML catalog contains both algorithm metadata and small C/C++ snippets used in the emitted code (check the `sleeps` section for examples).  
- To add a new algorithm or snippet, edit the YAML and follow the existing entries' structure (name, index, args, and snippet code).  
- If an algorithm appears weak or fingerprintable, replace or modify it in the YAML or add your own custom encoder/compressor/envelope entry.
