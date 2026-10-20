#!/usr/bin/env bash
# build-llama-metal.sh
# Builds llama.cpp natively on macOS with Metal (Apple Silicon).
# Output: $LLAMA_DIR/build/bin/llama-server  (setup-mac.sh links it into ~/.local/bin)
#
# Requirements: Xcode Command Line Tools, CMake
#   xcode-select --install
#   brew install cmake

set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
JOBS="${JOBS:-$(sysctl -n hw.logicalcpu)}"
# Pinned llama.cpp revision — the one inferstep/ATLAS v3.1.6 validates with
# Qwen3.5-9B-Q6_K. Building master gave a different binary on every setup.
# Override deliberately: LLAMA_CPP_REV=<sha> bash scripts/build-llama-metal.sh
LLAMA_CPP_REV="${LLAMA_CPP_REV:-2e97c5f96f9fe2bb26f794a348e05d7a1c74baa1}"

# ── 1. Clone and check out the pinned revision ──────────────────────────────
if [[ ! -d "$LLAMA_DIR/.git" ]]; then
  echo ">> Cloning llama.cpp to $LLAMA_DIR"
  git clone https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
fi

cd "$LLAMA_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  # Only the ATLAS patch below is expected; drop it so checkout is clean.
  git checkout -- tools/server/server-context.cpp 2>/dev/null || true
fi
if ! git cat-file -e "$LLAMA_CPP_REV^{commit}" 2>/dev/null; then
  git fetch origin
fi
echo ">> Checking out llama.cpp $LLAMA_CPP_REV"
git checkout --quiet --detach "$LLAMA_CPP_REV"

# ── 2. ATLAS patch (spec-decode safety) ────────────────────────────────────
# Prevents --embeddings flag from poisoning draft model context when spec
# decode is used. Harmless no-op when no draft model is configured (Qwen3.5).
PATCH_MARKER='// ATLAS: draft never needs embeddings'
if ! grep -q 'auto params_dft = params_base;' tools/server/server-context.cpp; then
  echo "ERROR: spec-decode patch anchor not found at $LLAMA_CPP_REV" >&2
  exit 1
fi
if ! grep -q "$PATCH_MARKER" tools/server/server-context.cpp; then
  sed -i '' '/auto params_dft = params_base;/a\
        params_dft.embedding = false;  // ATLAS: draft never needs embeddings' \
    tools/server/server-context.cpp
  echo ">> Applied ATLAS spec-decode patch"
else
  echo ">> ATLAS patch already applied, skipping"
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
echo "  mkdir -p ~/.local/bin && ln -sf $LLAMA_DIR/build/bin/llama-server ~/.local/bin/llama-server"
