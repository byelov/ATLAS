# Running ATLAS natively on macOS (Metal)

No Docker, no CUDA. Apple Silicon GPU via Metal.

## Stack at a glance

```
atlas-proxy :8090  (Go)      ← grammar / agent loop / Aider format
     │
     └── llama-server :8080  (C++, Metal)  ← Qwen3.5-9B-Q6_K.gguf
     │
     └── geometric-lens :8099 (Python)     ← C(x) / G(x) scoring
     │
     └── sandbox :8020        (Python)     ← isolated code exec
```

Grammar-constrained decoding (`json_schema`) is **not a build flag** — it is part of
llama.cpp's built-in server and works identically on Metal and CUDA.
The atlas-proxy constructs the schema at request time ([atlas-proxy/grammar.go](../atlas-proxy/grammar.go)).

---

## Python version

**Use Python 3.12** (via conda — see below).

All three Python services are **asyncio-based** (FastAPI + uvicorn). The
free-threaded CPython builds in 3.13t/3.14t remove the GIL to help
*CPU-bound multi-threaded* code. Async I/O is already concurrent without the
GIL — there is nothing to gain here. Additionally, `tree-sitter` C extensions
and the PyTorch MPS backend are not yet certified free-threaded-safe.

| Python | Verdict for ATLAS |
|--------|-------------------|
| 3.11 | Fine, slightly slower |
| **3.12** | **Recommended** — 10–15% faster than 3.11, all deps tested, full arm64 conda support |
| 3.13 (GIL mode) | Works, no advantage over 3.12 |
| 3.13t / 3.14t (free-threaded) | `tree-sitter` + MPS not safe — avoid |

---

## Conda environment

Create a dedicated `atlas` env to keep ATLAS deps isolated:

```bash
conda create -n atlas python=3.12 -y
conda activate atlas

# Install huggingface_hub so you can use huggingface-cli and resolve model paths
pip install huggingface_hub
```

All `pip install` and `python` commands in this guide assume the `atlas` env
is active. Add `conda activate atlas` to each new terminal, or set it as the
default in your IDE.

---

## Model — using your HuggingFace cache

Models already downloaded via `huggingface-cli` or the `huggingface_hub` library
live under `~/.cache/huggingface/hub/` and can be reused without re-downloading.

```bash
# Downloads into HF cache — skips download if the file is already present
huggingface-cli download unsloth/Qwen3.5-9B-GGUF Qwen3.5-9B-Q6_K.gguf

# Resolve the cached path once and export it
export MODEL_PATH=$(python3 -c "
from huggingface_hub import hf_hub_download
print(hf_hub_download('unsloth/Qwen3.5-9B-GGUF', 'Qwen3.5-9B-Q6_K.gguf'))
")
echo "Model at: $MODEL_PATH"
```

To persist across sessions, add to `~/.zprofile`:

```bash
echo 'export MODEL_PATH=$(python3 -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(\"unsloth/Qwen3.5-9B-GGUF\", \"Qwen3.5-9B-Q6_K.gguf\"))")' \
  >> ~/.zprofile
```

> If you already have the file at a fixed path (e.g. `~/models/Qwen3.5-9B-Q6_K.gguf`)
> you can just `export MODEL_PATH=~/models/Qwen3.5-9B-Q6_K.gguf` instead.

---

## 1 · Build llama-server with Metal

```bash
bash scripts/build-llama-metal.sh
# then optionally:
sudo ln -sf ~/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
```

What changed vs the CUDA Dockerfile:

| CUDA | Metal |
|------|-------|
| `-DGGML_CUDA=ON` | `-DGGML_METAL=ON` |
| `-DCMAKE_CUDA_ARCHITECTURES=120` | *(removed)* |
| `nvidia/cuda:12.8` base image | native macOS toolchain |

---

## 2 · Run llama-server

```bash
# No MODEL_PATH needed — auto-resolves from HF cache (unsloth/Qwen3.5-9B-GGUF)
CONTEXT_LENGTH=65536 PARALLEL_SLOTS=4 bash inference/entrypoint-metal.sh
```

To use a different model:
```bash
export MODEL_PATH=~/.cache/huggingface/hub/models--HauhauCS--Qwen3.5-9B-Uncensored-HauhauCS-Aggressive/snapshots/335e9ef38ada3edf9f9a3a6c2836022c1ab76ea1/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf
CONTEXT_LENGTH=65536 PARALLEL_SLOTS=4 bash inference/entrypoint-metal.sh
```

Key flags (same as CUDA, different backend):

| Flag | Purpose |
|------|---------|
| `-ngl 99` | offload all 35 layers to Metal GPU |
| `--flash-attn on` | fused attention kernels (Metal ≥ b3900) |
| `-ctk q8_0 -ctv q4_0` | KV cache quantisation — saves unified memory |
| `--embeddings` | expose `/v1/embeddings` for Geometric Lens |
| `--jinja` | Qwen3.5 chat template via jinja2 |
| `--mlock` | pin model in RAM (no swap) |

**CUDA env vars removed entirely** (`GGML_CUDA_NO_PINNED`,
`CUDA_DEVICE_MAX_CONNECTIONS`, `CUDA_MODULE_LOADING`) — Apple unified memory
has no pinned-vs-pageable distinction.

Memory budget on common Mac configs:

| Chip | RAM | Fits? |
|------|-----|-------|
| M2 / M3 (8 GB) | 8 GB | No — model alone is 7.5 GB |
| M2 / M3 (16 GB) | 16 GB | Yes — ~6 GB headroom for KV + OS |
| M2 Max / M3 Max (32 GB) | 32 GB | Comfortable, raise `PARALLEL_SLOTS=4` |
| M1 Ultra / M2 Ultra (64 GB+) | 64 GB | Raise `CONTEXT_LENGTH=65536`, `PARALLEL_SLOTS=4` |

---

## 3 · Run the rest of the stack

Make sure the `atlas` conda env is active in each terminal (`conda activate atlas`).

### Redis (required by Geometric Lens)
```bash
brew install redis
brew services start redis   # starts now and on login
redis-cli ping              # → PONG
```

### Geometric Lens (Python)
```bash
cd geometric-lens
pip install -r requirements.txt
LLAMA_URL=http://localhost:8080 \
LLAMA_EMBED_URL=http://localhost:8080 \
GEOMETRIC_LENS_ENABLED=true \
PROJECT_DATA_DIR=/tmp/atlas-projects \
REDIS_URL=redis://localhost:6379 \
  python -m uvicorn main:app --host 0.0.0.0 --port 8099
```

### V3 Service
```bash
cd v3-service
pip install torch
ATLAS_INFERENCE_URL=http://localhost:8080 \
ATLAS_LENS_URL=http://localhost:8099 \
ATLAS_SANDBOX_URL=http://localhost:8020 \
  python main.py
```

### Sandbox
```bash
cd sandbox
pip install fastapi uvicorn pydantic
python executor_server.py
```

### atlas-proxy (Go)
```bash
cd atlas-proxy
go build -o ~/.local/bin/atlas-proxy .
atlas-proxy
```
Default env vars already point to `localhost`, so no overrides needed for dev.

---

## 4 · Verify

```bash
# Model health
curl -s http://localhost:8080/health | python3 -m json.tool

# Grammar-constrained completion (JSON schema mode)
curl -s http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen3.5-9B-Q6_K",
    "messages": [{"role":"user","content":"hello"}],
    "json_schema": {"type":"object","properties":{"reply":{"type":"string"}},"required":["reply"]}
  }' | python3 -m json.tool

# Proxy health
curl -s http://localhost:8090/health
```

---

## Environment variables (entrypoint-metal.sh)

| Variable | Default | Notes |
|----------|---------|-------|
| `MODEL_PATH` | *(auto from HF cache)* | override to use a different model file |
| `CONTEXT_LENGTH` | `32768` | raise to `65536` on ≥32 GB |
| `PARALLEL_SLOTS` | `1` | raise to `4` on M1/M2 Ultra (64 GB) |
| `KV_CACHE_TYPE_K` | `q8_0` | |
| `KV_CACHE_TYPE_V` | `q4_0` | |
| `LLAMA_SERVER` | auto-detected | override if binary is elsewhere |
