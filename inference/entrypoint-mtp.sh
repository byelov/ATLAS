#!/bin/bash
# V3.1 MTP: Qwen3.5-9B with Multi-Token Prediction
#
# Uses inline MTP (not speculative framework) for ~1.5-2x speedup.
# MTP head predicts next token in parallel with main generation.

SLOT_SAVE_PATH="${SLOT_SAVE_PATH:-/tmp/slots}"
mkdir -p "$SLOT_SAVE_PATH"

CTX_LENGTH="${CONTEXT_LENGTH:-40960}"
KV_CACHE_K="${KV_CACHE_TYPE_K:-q8_0}"
KV_CACHE_V="${KV_CACHE_TYPE_V:-q4_0}"
KV_FLAGS="-ctk $KV_CACHE_K -ctv $KV_CACHE_V"
PARALLEL="${PARALLEL_SLOTS:-4}"
MODEL_FILE="${MODEL_PATH:-/models/Qwen3.5-9B-MTP-Q4_K_M-F16mtp.gguf}"

# Backend-specific runtime tuning (V3.1.1 multi-backend). Mirrors the
# block in entrypoint-v3.1.sh; kept inline rather than sourced so this
# experimental MTP path stays self-contained. Refactor candidate for
# V3.1.2 once we add a fourth backend (Metal).
ATLAS_BACKEND="${ATLAS_BACKEND:-cuda}"
case "$ATLAS_BACKEND" in
  cuda)
    export GGML_CUDA_NO_PINNED="${GGML_CUDA_NO_PINNED:-0}"
    export CUDA_DEVICE_MAX_CONNECTIONS="${CUDA_DEVICE_MAX_CONNECTIONS:-1}"
    export CUDA_MODULE_LOADING="${CUDA_MODULE_LOADING:-LAZY}"
    if [ -n "$ATLAS_GPU_INDEX" ] && [ -z "$CUDA_VISIBLE_DEVICES" ]; then
      export CUDA_VISIBLE_DEVICES="$ATLAS_GPU_INDEX"
    fi
    ;;
  rocm)
    export GGML_CUDA_NO_PINNED="${GGML_CUDA_NO_PINNED:-0}"
    if [ -n "$ATLAS_GPU_INDEX" ] && [ -z "$HIP_VISIBLE_DEVICES" ]; then
      export HIP_VISIBLE_DEVICES="$ATLAS_GPU_INDEX"
      export ROCR_VISIBLE_DEVICES="${ROCR_VISIBLE_DEVICES:-$ATLAS_GPU_INDEX}"
    fi
    if [ -n "$ATLAS_HSA_OVERRIDE_GFX_VERSION" ]; then
      export HSA_OVERRIDE_GFX_VERSION="$ATLAS_HSA_OVERRIDE_GFX_VERSION"
    fi
    ;;
  *)
    export GGML_CUDA_NO_PINNED="${GGML_CUDA_NO_PINNED:-0}"
    export CUDA_DEVICE_MAX_CONNECTIONS="${CUDA_DEVICE_MAX_CONNECTIONS:-1}"
    export CUDA_MODULE_LOADING="${CUDA_MODULE_LOADING:-LAZY}"
    ;;
esac

echo "=== V3.1 MTP: Qwen3.5-9B — Generation + MTP + Self-Embeddings ==="
echo "  Backend: $ATLAS_BACKEND${ATLAS_GPU_INDEX:+ (GPU index=$ATLAS_GPU_INDEX)}"
echo "  Model: $MODEL_FILE"
echo "  Context: $CTX_LENGTH | KV: K=$KV_CACHE_K V=$KV_CACHE_V | Parallel: $PARALLEL"
echo "  MTP: ENABLED (inline, 1 draft token per step)"
echo "  Embeddings: ENABLED (4096-dim Qwen3.5 self-embeddings)"

exec /usr/local/bin/llama-server \
  -m "$MODEL_FILE" \
  -c $CTX_LENGTH \
  $KV_FLAGS \
  --parallel $PARALLEL \
  --cont-batching \
  -ngl 99 \
  --host 0.0.0.0 \
  --port 8000 \
  --flash-attn on \
  --mlock \
  -b 4096 \
  -ub 2 \
  --slot-save-path "$SLOT_SAVE_PATH" \
  --ctx-checkpoints 0 \
  --no-cache-prompt \
  --embeddings \
  --jinja \
  --no-warmup
