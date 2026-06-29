#!/bin/bash
export LLAMA_NO_MTP=1
MODEL="${MODEL_PATH:?MODEL_PATH must point to the selected GGUF}"
PORT="${PORT:-8080}"
CTX_LENGTH="${CONTEXT_LENGTH:-32768}"
KV_CACHE_K="${KV_CACHE_TYPE_K:-q8_0}"
KV_CACHE_V="${KV_CACHE_TYPE_V:-q4_0}"
PARALLEL="${PARALLEL_SLOTS:-1}"
BATCH_SIZE="${BATCH_SIZE:-2048}"
UBATCH_SIZE="${UBATCH_SIZE:-1024}"
echo "=== ATLAS llama-server — No MTP, Parallel $PARALLEL ==="
exec /usr/local/bin/llama-server \
  -m "$MODEL" -c "$CTX_LENGTH" \
  -ctk "$KV_CACHE_K" -ctv "$KV_CACHE_V" \
  --parallel "$PARALLEL" --cont-batching -ngl 99 \
  --host 0.0.0.0 --port $PORT \
  --flash-attn on --mlock \
  -b "$BATCH_SIZE" -ub "$UBATCH_SIZE" \
  --ctx-checkpoints 0 --no-cache-prompt \
  --embeddings --jinja --no-warmup 2>&1
