# ATLAS Setup — macOS Native (Apple Silicon + Metal)

Run all five ATLAS services as local processes on macOS.  
No Docker, no CUDA, no NVIDIA driver.

**Tested configuration:** M1, 64 GB unified memory, macOS 14+

---

## Architecture

```
atlas-proxy :8090   (Go binary)
  ├── llama-server :8080   (C++ — Metal GPU, Qwen3.5-9B-Q6_K)
  ├── geometric-lens :8099 (Python — FastAPI, RAG, C(x)/G(x) scoring)
  ├── v3-service :8070     (Python — V3 pipeline, PlanSearch, etc.)
  └── sandbox :8020        (Python — isolated code execution)
```

Grammar-constrained decoding (`json_schema`) is handled entirely inside
llama-server's HTTP layer. The Go proxy builds the schema at request time —
no Metal-specific changes needed anywhere except the build step.

---

## Prerequisites

| Tool | Install |
|------|---------|
| Xcode Command Line Tools | `xcode-select --install` |
| [Homebrew](https://brew.sh) | `/bin/bash -c "$(curl -fsSL https://brew.sh/install.sh)"` |
| CMake | `brew install cmake` |
| Go 1.24+ | `brew install go` |
| [Miniconda](https://docs.anaconda.com/miniconda/) (arm64) | `brew install --cask miniconda` |
| Redis | `brew install redis` |
| Node.js 20+ | `brew install node` (sandbox — JS/TS execution) |
| Rust | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` (sandbox — Rust execution) |

**Python version:** Use **3.12** via conda. The ATLAS services are all asyncio-based
(FastAPI/uvicorn), so free-threaded 3.13t/3.14t provides no benefit and `tree-sitter`
C extensions are not yet free-threaded-safe. See [MAC_METAL.md](MAC_METAL.md#python-version)
for the full comparison.

Verify:
```bash
cmake --version       # 3.x+
go version            # go1.24+
redis-cli --version
node --version        # v20+
rustc --version
```

---

## Step 1 — Clone ATLAS

```bash
git clone https://github.com/itigges22/ATLAS.git
cd ATLAS
```

All subsequent paths are relative to this directory.

---

## Step 1b — Create the `atlas` Conda Environment

```bash
conda create -n atlas python=3.12 -y
conda activate atlas
pip install huggingface_hub   # provides huggingface-cli
```

Activate this env in **every** new terminal before running any Python service:
```bash
conda activate atlas
```

---

## Step 2 — Get the Model (reuses HuggingFace cache)

If you have previously downloaded any HF models, `huggingface-cli` reuses what
is already in `~/.cache/huggingface/hub/` and only fetches what is missing.

```bash
# Download into HF cache (skips if already present — ~7.5 GB)
huggingface-cli download unsloth/Qwen3.5-9B-GGUF Qwen3.5-9B-Q6_K.gguf

# Resolve the cached path and export it
export MODEL_PATH=$(python3 -c "
from huggingface_hub import hf_hub_download
print(hf_hub_download('unsloth/Qwen3.5-9B-GGUF', 'Qwen3.5-9B-Q6_K.gguf'))
")
echo "Model: $MODEL_PATH"

export MODEL_PATH=~/.cache/huggingface/hub/models--HauhauCS--Qwen3.5-9B-Uncensored-HauhauCS-Aggressive/snapshots/335e9ef38ada3edf9f9a3a6c2836022c1ab76ea1/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf
bash inference/entrypoint-metal.sh

```

Persist the variable so you don't re-export every session:
```bash
echo 'export MODEL_PATH=$(python3 -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(\"unsloth/Qwen3.5-9B-GGUF\", \"Qwen3.5-9B-Q6_K.gguf\"))")' \
  >> ~/.zprofile
```

> If you prefer a fixed path, copy the file anywhere and just set
> `export MODEL_PATH=~/models/Qwen3.5-9B-Q6_K.gguf`.

---

## Step 3 — Build llama-server (Metal)

```bash
bash scripts/build-llama-metal.sh
```

This clones llama.cpp to `~/llama.cpp`, applies the ATLAS spec-decode patch,
and builds with `-DGGML_METAL=ON`. Takes 3–5 minutes on M1.

Symlink the binary so it is on your PATH:
```bash
sudo ln -sf ~/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
```

Verify:
```bash
llama-server --version
# Should print version + "Metal" in the backend list
```

---

## Step 4 — Install the ATLAS Python CLI

```bash
conda activate atlas
pip install -e .
```

---

## Step 5 — Install Python Dependencies

```bash
conda activate atlas

# Geometric Lens (includes torch CPU wheel)
pip install -r geometric-lens/requirements.txt

# V3 Service
# 'pip install torch' on Apple Silicon automatically selects the MPS-capable
# wheel. V3 runs pure Python and never calls MPS kernels directly, but the
# MPS wheel is correct for the atlas env regardless.
pip install torch
```

---

## Step 6 — Build atlas-proxy (Go)

```bash
cd atlas-proxy
go build -o ~/.local/bin/atlas-proxy .
cd ..
```

Make sure `~/.local/bin` is on your PATH:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

Verify:
```bash
atlas-proxy --help 2>&1 | head -5   # or: which atlas-proxy
```

---

## Step 7 — Start Redis

Geometric Lens needs Redis for project metadata caching.

```bash
brew services start redis
# or for a one-off foreground instance:
redis-server
```

Verify:
```bash
redis-cli ping   # → PONG
```

---

## Step 8 — Start All Services

Open **five terminal tabs** (or use `tmux`), one per service.

### Terminal 1 — llama-server (Metal GPU)

```bash
# MODEL_PATH must be set (see Step 2); no conda env needed for the C++ binary
CONTEXT_LENGTH=65536 \
PARALLEL_SLOTS=4 \
  bash inference/entrypoint-metal.sh
```

M1 64 GB budget at these settings:
- Model Q6_K: ~7.5 GB
- KV cache (4 slots × 65 K ctx, q8_0/q4_0): ~8 GB
- OS + other services: ~4 GB
- **Total: ~20 GB / 64 GB** — very comfortable

Wait for the line:
```
llama server listening at http://0.0.0.0:8080
```

### Terminal 2 — Geometric Lens

```bash
conda activate atlas
cd geometric-lens
LLAMA_URL=http://localhost:8080 \
LLAMA_EMBED_URL=http://localhost:8080 \
GEOMETRIC_LENS_ENABLED=true \
PROJECT_DATA_DIR=/tmp/atlas-projects \
REDIS_URL=redis://localhost:6379 \
  python -m uvicorn main:app --host 0.0.0.0 --port 8099
```

### Terminal 3 — V3 Pipeline Service

```bash
conda activate atlas
cd v3-service
ATLAS_INFERENCE_URL=http://localhost:8080 \
ATLAS_LENS_URL=http://localhost:8099 \
ATLAS_SANDBOX_URL=http://localhost:8020 \
ATLAS_MODEL_NAME=Qwen3.5-9B-Q6_K \
  python main.py
```

### Terminal 4 — Sandbox

```bash
conda activate atlas
cd sandbox
python executor_server.py
```

Runs on port **8020** in bare-metal mode (no Docker port remapping).

### Terminal 5 — atlas-proxy

```bash
ATLAS_PROXY_PORT=8090 \
ATLAS_INFERENCE_URL=http://localhost:8080 \
ATLAS_LLAMA_URL=http://localhost:8080 \
ATLAS_LENS_URL=http://localhost:8099 \
ATLAS_SANDBOX_URL=http://localhost:8020 \
ATLAS_V3_URL=http://localhost:8070 \
ATLAS_AGENT_LOOP=1 \
ATLAS_MODEL_NAME=Qwen3.5-9B-Q6_K \
  atlas-proxy
```

---

## Step 9 — Verify

Run these after all five services are up:

```bash
# 1. llama-server
curl -s http://localhost:8080/health | python3 -m json.tool

# 2. Geometric Lens
curl -s http://localhost:8099/health | python3 -m json.tool

# 3. V3 Service
curl -s http://localhost:8070/health | python3 -m json.tool

# 4. Sandbox
curl -s http://localhost:8020/health | python3 -m json.tool

# 5. atlas-proxy
curl -s http://localhost:8090/health | python3 -m json.tool

# 6. Grammar-constrained completion (sanity check)
curl -s http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen3.5-9B-Q6_K",
    "messages": [{"role":"user","content":"Say hi"}],
    "json_schema": {
      "type": "object",
      "properties": {"reply": {"type": "string"}},
      "required": ["reply"]
    }
  }' | python3 -m json.tool
```

All health endpoints should return `{"status":"ok"}` or `{"status":"healthy"}`.

---

## Step 10 — Launch ATLAS

```bash
atlas
```

---

## Tuning for M1 64 GB

| Variable | Default | M1 64 GB recommendation |
|----------|---------|--------------------------|
| `CONTEXT_LENGTH` | 32768 | **65536** — 64 K context per slot |
| `PARALLEL_SLOTS` | 1 | **4** — 4 concurrent request slots |
| `KV_CACHE_TYPE_K` | `q8_0` | keep `q8_0` |
| `KV_CACHE_TYPE_V` | `q4_0` | keep `q4_0` |

With 4 slots × 65 K context the total KV footprint is ~8 GB.
You have ~40 GB of headroom for OS, other apps, and future larger models.

---

## Geometric Lens Weights (Optional)

The Lens service runs without trained weights — returns neutral scores,
V3 pipeline falls back to sandbox-only verification.

To enable full C(x)/G(x) scoring, download weights from HuggingFace:

```bash
# Place weight files here:
ls geometric-lens/geometric_lens/models/
```

See [SETUP.md — Geometric Lens Weights](SETUP.md#geometric-lens-weights-optional)
for download instructions.

---

## Stopping Services

```bash
# If running in foreground tabs:
Ctrl+C in each terminal

# If you backgrounded them:
pkill -f llama-server
pkill -f "uvicorn main:app"
pkill -f "python main.py"
pkill -f executor_server
pkill -f atlas-proxy

# Stop Redis (if brew service):
brew services stop redis
```

---

## Next Steps

- [CLI.md](CLI.md) — How to use ATLAS once it's running
- [CONFIGURATION.md](CONFIGURATION.md) — All environment variables and tuning options
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Common issues and solutions
- [MAC_METAL.md](MAC_METAL.md) — Build flag reference and architecture comparison
