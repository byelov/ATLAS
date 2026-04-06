#!/usr/bin/env bash
# entrypoint-metal.sh
# Run llama-server natively on macOS with Metal (Apple Silicon).
# Drop-in replacement for the CUDA Docker entrypoints — same flags where
# they apply, CUDA-specific knobs removed.
#
# Usage:
#   MODEL_PATH=~/models/Qwen3.5-9B-Q6_K.gguf ./inference/entrypoint-metal.sh
#
# Or with the symlinked binary after build-llama-metal.sh:
#   MODEL_PATH=~/models/Qwen3.5-9B-Q6_K.gguf bash inference/entrypoint-metal.sh

set -euo pipefail

# ── Model ───────────────────────────────────────────────────────────────────
# Resolve MODEL_PATH: env var > HF cache (glob) > conda python > ~/models fallback
if [[ -z "${MODEL_PATH:-}" ]]; then
    # 1. Try direct glob in HF cache (no Python needed)
    HF_GLOB=$(ls ~/.cache/huggingface/hub/models--unsloth--Qwen3.5-9B-GGUF/snapshots/*/Qwen3.5-9B-Q6_K.gguf 2>/dev/null | head -1)
    if [[ -f "${HF_GLOB:-}" ]]; then
        MODEL_PATH="$HF_GLOB"
    else
        # 2. Try conda atlas env python
        CONDA_PY="${HOME}/opt/homebrew/Caskroom/miniforge/base/envs/atlas/bin/python3"
        [[ ! -x "$CONDA_PY" ]] && CONDA_PY="/opt/homebrew/Caskroom/miniforge/base/envs/atlas/bin/python3"
        MODEL_PATH=$("$CONDA_PY" -c "
from huggingface_hub import hf_hub_download
print(hf_hub_download('unsloth/Qwen3.5-9B-GGUF', 'Qwen3.5-9B-Q6_K.gguf'))
" 2>/dev/null) || MODEL_PATH="$HOME/models/Qwen3.5-9B-Q6_K.gguf"
    fi
fi
MODEL_FILE="${MODEL_PATH}"

# ── Context / KV cache ──────────────────────────────────────────────────────
# Mac unified memory: GPU and CPU share the same pool.
# Q6_K  ≈ 7.5 GB model weight + ~1.5 GB KV at 32 K ctx → fits in 16 GB M2.
# Raise to 65536 on M2 Max/Ultra (32–64 GB).
CTX_LENGTH="${CONTEXT_LENGTH:-32768}"
KV_CACHE_K="${KV_CACHE_TYPE_K:-q8_0}"   # key cache quantization
KV_CACHE_V="${KV_CACHE_TYPE_V:-q4_0}"   # value cache quantization

# ── Parallelism ─────────────────────────────────────────────────────────────
# 1–2 slots is comfortable for dev on a 16 GB machine.
# Bump to 4 on M2 Max/Ultra (≥32 GB).
PARALLEL="${PARALLEL_SLOTS:-1}"

# ── Binary ──────────────────────────────────────────────────────────────────
# Prefers symlinked system binary; falls back to common build path.
LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server 2>/dev/null || echo "$HOME/llama.cpp/build/bin/llama-server")}"

if [[ ! -x "$LLAMA_SERVER" ]]; then
  echo "ERROR: llama-server not found at $LLAMA_SERVER"
  echo "Run:  bash scripts/build-llama-metal.sh"
  exit 1
fi

echo "=== ATLAS: Qwen3.5-9B Q6_K — Metal (macOS native) ==="
echo "  Binary : $LLAMA_SERVER"
echo "  Model  : $MODEL_FILE"
echo "  Context: $CTX_LENGTH tokens"
echo "  KV     : K=$KV_CACHE_K  V=$KV_CACHE_V"
echo "  Slots  : $PARALLEL"
echo "  Backend: Metal (GPU layers = 99, unified memory)"
echo "  Grammar: JSON-schema constrained decoding via atlas-proxy"
echo ""

# ── CUDA differences ─────────────────────────────────────────────────────────
# REMOVED: GGML_CUDA_NO_PINNED, CUDA_DEVICE_MAX_CONNECTIONS, CUDA_MODULE_LOADING
# Unified memory on Apple Silicon has no pinned-memory distinction.
#
# REMOVED: -DCMAKE_CUDA_ARCHITECTURES, nvidia device mounts
#
# KEPT:  -ngl 99           → offload all layers to Metal GPU
# KEPT:  --flash-attn on   → works on Metal (llama.cpp ≥ b3900)
# KEPT:  -ctk/-ctv         → KV cache quant is backend-agnostic
# KEPT:  --embeddings       → Qwen3.5 self-embeddings (4096-dim) for Lens C(x)
# KEPT:  --jinja            → prompt template rendering
# KEPT:  --cont-batching    → continuous batching for multi-slot
#
# --mlock: keeps the model in physical RAM (no swap).
#   On macOS this requires the process to have the right limits.
#   If you hit "mlock failed", either run with sudo or omit the flag.

exec "$LLAMA_SERVER" \
  -m "$MODEL_FILE" \
  -c "$CTX_LENGTH" \
  -ctk "$KV_CACHE_K" \
  -ctv "$KV_CACHE_V" \
  --parallel  "$PARALLEL" \
  --cont-batching \
  -ngl 99 \
  --host 0.0.0.0 \
  --port 8080 \
  --flash-attn on \
  --mlock \
  -b 4096 \
  -ub 4096 \
  --no-cache-prompt \
  --embeddings \
  --jinja \
  --reasoning-format none \
  --no-warmup
