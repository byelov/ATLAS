#!/usr/bin/env bash
# build-llama-metal.sh
# Builds llama.cpp natively on macOS with Metal (Apple Silicon).
# Output: ./llama.cpp/build/bin/llama-server  (symlinked to /usr/local/bin optional)
#
# Requirements: Xcode Command Line Tools, CMake
#   xcode-select --install
#   brew install cmake

set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
JOBS="${JOBS:-$(sysctl -n hw.logicalcpu)}"

# ── 1. Clone or update ──────────────────────────────────────────────────────
if [[ -d "$LLAMA_DIR/.git" ]]; then
  echo ">> Updating existing llama.cpp at $LLAMA_DIR"
  git -C "$LLAMA_DIR" pull --ff-only
else
  echo ">> Cloning llama.cpp to $LLAMA_DIR"
  git clone https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
fi

cd "$LLAMA_DIR"

# ── 2. ATLAS patch (spec-decode safety) ────────────────────────────────────
# Prevents --embeddings flag from poisoning draft model context when spec
# decode is used. Harmless no-op when no draft model is configured (Qwen3.5).
if grep -q 'auto params_dft = params_base;' tools/server/server-context.cpp 2>/dev/null; then
  PATCH_MARKER='// ATLAS: draft never needs embeddings'
  if ! grep -q "$PATCH_MARKER" tools/server/server-context.cpp; then
    sed -i '' '/auto params_dft = params_base;/a\
        params_dft.embedding = false;  // ATLAS: draft never needs embeddings' \
      tools/server/server-context.cpp
    echo ">> Applied ATLAS spec-decode patch"
  else
    echo ">> ATLAS patch already applied, skipping"
  fi
fi

# ── 3. Configure ────────────────────────────────────────────────────────────
# GGML_METAL=ON   → GPU kernels via Metal (auto-detected on macOS, but explicit)
# BUILD_SHARED_LIBS=OFF → single static binary, no .dylib dependency hell
cmake -B build \
  -DGGML_METAL=ON \
  -DBUILD_SHARED_LIBS=OFF \
  -DCMAKE_BUILD_TYPE=Release

# ── 4. Build ─────────────────────────────────────────────────────────────── 
echo ">> Building with $JOBS parallel jobs…"
cmake --build build --config Release -j"$JOBS"

echo ""
echo "✓ Build complete: $LLAMA_DIR/build/bin/llama-server"
echo ""
echo "Optional — symlink to PATH:"
echo "  sudo ln -sf $LLAMA_DIR/build/bin/llama-server /usr/local/bin/llama-server"
