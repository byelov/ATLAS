#!/usr/bin/env bash
# setup-mac.sh
# One-time setup for ATLAS on macOS Apple Silicon (Metal).
# Run from the project root: bash scripts/setup-mac.sh
#
# What this does:
#   1. Check prerequisites (Homebrew, conda, Go, cmake)
#   2. Create conda env 'atlas' with Python 3.12
#   3. Install Python deps for all services
#   4. Install the atlas CLI (pip install -e .)
#   5. Install Redis via Homebrew
#   6. Build llama-server with Metal
#   7. Download the Qwen3.5-9B-Q6_K model into HF cache
#   8. Download Geometric Lens weights (cost_field.pt, metric_tensor.pt, etc.)
#
# After this completes, run:  bash scripts/run-mac.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Colors ──────────────────────────────────────────────────────────────────
BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
step()  { echo -e "\n${BOLD}${GREEN}▶ $*${RESET}"; }
warn()  { echo -e "${YELLOW}⚠  $*${RESET}"; }
error() { echo -e "${RED}✗  $*${RESET}"; exit 1; }
ok()    { echo -e "${GREEN}✓  $*${RESET}"; }

# ── 1. Prerequisites ─────────────────────────────────────────────────────────
step "Checking prerequisites"

command -v brew  &>/dev/null || error "Homebrew not found. Install from https://brew.sh"
command -v conda &>/dev/null || error "conda not found. Install miniforge: brew install --cask miniforge"
command -v go    &>/dev/null || error "Go not found. Install: brew install go"
command -v cmake &>/dev/null || { warn "cmake not found — installing via brew"; brew install cmake; }
command -v git   &>/dev/null || error "git not found. Run: xcode-select --install"
ok "Prerequisites OK"

# ── 2. Conda environment ─────────────────────────────────────────────────────
step "Setting up conda environment 'atlas' (Python 3.12)"

if conda env list | grep -q '^atlas '; then
    ok "Conda env 'atlas' already exists — skipping create"
else
    conda create -n atlas python=3.12 -y
    ok "Created conda env 'atlas'"
fi

# Activate — works even when conda hasn't been shell-inited yet
CONDA_BASE=$(conda info --base)
# shellcheck source=/dev/null
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate atlas

ok "Activated atlas env ($(python3 --version))"

# ── 3. Python dependencies ───────────────────────────────────────────────────
step "Installing Python dependencies"

pip install -q huggingface_hub

echo "  geometric-lens…"
pip install -q -r geometric-lens/requirements.txt

echo "  sandbox…"
pip install -q fastapi uvicorn pydantic

echo "  v3-service (torch — may take a while)…"
pip install -q torch

echo "  atlas CLI…"
pip install -q -e .

ok "Python dependencies installed"

# ── 4. Redis ─────────────────────────────────────────────────────────────────
step "Installing Redis"

if brew list redis &>/dev/null; then
    ok "Redis already installed"
else
    brew install redis
    ok "Redis installed"
fi

# ── 5. Build llama-server with Metal ─────────────────────────────────────────
step "Building llama-server with Metal"

bash scripts/build-llama-metal.sh

# Symlink so llama-server is on PATH
LLAMA_BIN="$HOME/llama.cpp/build/bin/llama-server"
if [[ -x "$LLAMA_BIN" ]]; then
    sudo ln -sf "$LLAMA_BIN" /usr/local/bin/llama-server
    ok "llama-server symlinked to /usr/local/bin/llama-server"
fi

# ── 6. Download model ────────────────────────────────────────────────────────
step "Downloading Qwen3.5-9B-Q6_K model"

python3 -c "
from huggingface_hub import hf_hub_download
print('Resolving model (downloads if not cached)...')
path = hf_hub_download('unsloth/Qwen3.5-9B-GGUF', 'Qwen3.5-9B-Q6_K.gguf')
print(f'Model ready at: {path}')
"

# ── 7. Download Geometric Lens weights ───────────────────────────────────────
step "Downloading Geometric Lens weights"

python3 - <<'EOF'
from huggingface_hub import hf_hub_download
import shutil, os

dest = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '..', 'geometric-lens', 'geometric_lens', 'models')
dest = os.path.normpath(dest)
os.makedirs(dest, exist_ok=True)

files = [
    'models/cost_field.pt',
    'models/metric_tensor.pt',
    'models/gx_xgboost.pkl',
    'models/gx_weights.json',
]
for fpath in files:
    fname = os.path.basename(fpath)
    out = os.path.join(dest, fname)
    if os.path.exists(out):
        print(f'  Already present: {fname}')
        continue
    try:
        path = hf_hub_download('itigges22/ATLAS', fpath, repo_type='dataset')
        shutil.copy(path, out)
        print(f'  Downloaded: {fname}')
    except Exception as e:
        print(f'  Skipped {fname}: {e}')
EOF

# ── 8. Build proxy ────────────────────────────────────────────────────────────
step "Building proxy (Go)"

cd proxy
mkdir -p "$HOME/.local/bin"
go build -o "$HOME/.local/bin/atlas-proxy" .
cd ..

# Ensure ~/.local/bin is on PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "Add ~/.local/bin to your PATH:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zprofile"
fi

ok "atlas-proxy built → ~/.local/bin/atlas-proxy"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✓ Setup complete!${RESET}"
echo ""
echo "  Start all services with:"
echo -e "    ${BOLD}bash scripts/run-mac.sh${RESET}"
echo ""
