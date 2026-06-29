#!/usr/bin/env bash
# run-mac.sh
# Start all ATLAS services on macOS (Metal) and launch the CLI.
# Run from the project root: bash scripts/run-mac.sh
#
# Services started (each in its own background process, log to /tmp/atlas-logs/):
#   llama-server  :8080  (Metal GPU)
#   geometric-lens :8099 (Python / FastAPI)
#   sandbox        :8020 (Python / FastAPI)
#   redis          :6379 (via brew services)
#
# Optional (set ATLAS_RUN_PROXY=1 to also start the proxy):
#   proxy          :8090 (Go — grammar-constrained agent loop)
#
# After all services are healthy, launches:
#   atlas  (interactive REPL)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="/tmp/atlas-logs"
mkdir -p "$LOG_DIR"

# ── Colors ──────────────────────────────────────────────────────────────────
BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; CYAN='\033[36m'; RESET='\033[0m'
step()  { echo -e "\n${BOLD}${CYAN}▶ $*${RESET}"; }
ok()    { echo -e "${GREEN}✓  $*${RESET}"; }
warn()  { echo -e "${YELLOW}⚠  $*${RESET}"; }
error() { echo -e "${RED}✗  $*${RESET}"; exit 1; }

# ── Activate conda ───────────────────────────────────────────────────────────
CONDA_BASE=$(conda info --base 2>/dev/null) || error "conda not found. Run setup-mac.sh first."
# shellcheck source=/dev/null
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate atlas
# Another auto-activated env can stay ahead of atlas on PATH; force atlas first.
ATLAS_ENV="$CONDA_BASE/envs/atlas"
[[ -x "$ATLAS_ENV/bin/python" ]] || error "conda env 'atlas' not found. Run setup-mac.sh first."
export PATH="$ATLAS_ENV/bin:$PATH"
[[ "$(command -v python)" == "$ATLAS_ENV/bin/python" ]] || error "failed to activate atlas env (python=$(command -v python))"

# ── Configuration ─────────────────────────────────────────────────────────────
CONTEXT_LENGTH="${CONTEXT_LENGTH:-65536}"
PARALLEL_SLOTS="${PARALLEL_SLOTS:-4}"
# The lens couples its artifacts to a model identity; the proxy/CLI tag requests
# with it too. Override to match a model-specific lens artifact if you retrain.
ATLAS_MODEL_NAME="${ATLAS_MODEL_NAME:-Qwen3.5-9B-Q6_K}"
export ATLAS_MODEL_NAME

# ── Cleanup on exit ───────────────────────────────────────────────────────────
PIDS=()
cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping ATLAS services…${RESET}"
    # Kill entire process groups so subshell children (uvicorn, llama-server, etc.)
    # are also terminated — not just the subshell wrapper.
    for pid in "${PIDS[@]}"; do
        kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    done
    # Belt-and-suspenders: clean up by port in case any process survived
    for port in 8080 8099 8020 8090; do
        survivor=$(lsof -ti :"$port" 2>/dev/null) || true
        [[ -n "$survivor" ]] && kill -9 $survivor 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo -e "${GREEN}All services stopped.${RESET}"
}
trap cleanup EXIT INT TERM

# ── Wait-for-health helper ────────────────────────────────────────────────────
wait_healthy() {
    local name="$1" url="$2" retries="${3:-30}" delay="${4:-2}"
    echo -n "  Waiting for $name"
    for ((i=0; i<retries; i++)); do
        if curl -sf "$url" &>/dev/null; then
            echo -e " ${GREEN}ready${RESET}"
            return 0
        fi
        echo -n "."
        sleep "$delay"
    done
    echo -e " ${RED}timeout${RESET}"
    warn "$name did not become healthy at $url — check $LOG_DIR/${name}.log"
    return 1
}

# ── 1. Redis ─────────────────────────────────────────────────────────────────
step "Redis"
if redis-cli ping &>/dev/null; then
    ok "Redis already running"
else
    brew services start redis
    sleep 1
    redis-cli ping &>/dev/null && ok "Redis started" || error "Redis failed to start"
fi

# ── 2. llama-server ───────────────────────────────────────────────────────────
step "llama-server (Metal, port 8080)"

# Kill any existing instance on 8080
if lsof -ti :8080 &>/dev/null; then
    warn "Port 8080 in use — killing existing process"
    lsof -ti :8080 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

CONTEXT_LENGTH="$CONTEXT_LENGTH" PARALLEL_SLOTS="$PARALLEL_SLOTS" \
    bash inference/entrypoint-metal.sh >"$LOG_DIR/llama-server.log" 2>&1 &
LLAMA_PID=$!
PIDS+=("$LLAMA_PID")
echo "  PID $LLAMA_PID → $LOG_DIR/llama-server.log"

wait_healthy "llama-server" "http://localhost:8080/health" 60 2

# ── 3. Geometric Lens ────────────────────────────────────────────────────────
step "Geometric Lens (port 8099)"

if lsof -ti :8099 &>/dev/null; then
    warn "Port 8099 in use — killing existing process"
    lsof -ti :8099 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# OMP_NUM_THREADS=1 + KMP_DUPLICATE_LIB_OK: the lens loads torch (C(x)) then
# xgboost (G(x)) in one process; on macOS their two libomp copies otherwise
# clash and segfault at startup. Single-threaded OpenMP avoids it (xgboost
# inference is cheap); C(x) is tiny so the thread cap costs nothing here.
LLAMA_URL=http://localhost:8080 \
LLAMA_EMBED_URL=http://localhost:8080 \
GEOMETRIC_LENS_ENABLED=true \
ATLAS_MODEL_NAME="$ATLAS_MODEL_NAME" \
OMP_NUM_THREADS=1 KMP_DUPLICATE_LIB_OK=TRUE \
PROJECT_DATA_DIR=/tmp/atlas-projects \
REDIS_URL=redis://localhost:6379 \
  bash -c 'cd geometric-lens && exec python -m uvicorn main:app --host 0.0.0.0 --port 8099' \
  >"$LOG_DIR/geometric-lens.log" 2>&1 &
LENS_PID=$!
PIDS+=("$LENS_PID")
echo "  PID $LENS_PID → $LOG_DIR/geometric-lens.log"

wait_healthy "geometric-lens" "http://localhost:8099/health" 30 2

# ── 4. Sandbox ───────────────────────────────────────────────────────────────
step "Sandbox (port 8020)"

if lsof -ti :8020 &>/dev/null; then
    warn "Port 8020 in use — killing existing process"
    lsof -ti :8020 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

bash -c 'cd sandbox && exec python executor_server.py' >"$LOG_DIR/sandbox.log" 2>&1 &
SANDBOX_PID=$!
PIDS+=("$SANDBOX_PID")
echo "  PID $SANDBOX_PID → $LOG_DIR/sandbox.log"

wait_healthy "sandbox" "http://localhost:8020/health" 30 2

# ── 5. proxy ──────────────────────────────────────────────────────────────────
step "proxy (port 8090)"

PROXY_BIN="${HOME}/.local/bin/atlas-proxy"
if [[ ! -x "$PROXY_BIN" ]]; then
    warn "proxy not found — building now"
    (cd proxy && go build -o "$PROXY_BIN" .)
fi

if lsof -ti :8090 &>/dev/null; then
    warn "Port 8090 in use — killing existing process"
    lsof -ti :8090 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# ATLAS_GRAMMAR_MODE=gbnf: the stock Metal llama.cpp build can't compile a
#   JSON schema into a sampler ("Failed to initialize samplers") — it accepts
#   plain json_object and GBNF grammars but not response_format schemas. gbnf
#   mode constrains the agent's tool calls with the full GBNF grammar instead,
#   giving schema-strict tool calls that compile on this build. (Use "loose"
#   for json_object-only, or "strict" if you build a llama.cpp that supports
#   json-schema response_format.)
# ATLAS_VERIFY_IN=host: the sandbox confines run_command to /workspace, which
#   isn't bind-mounted to your project on native macOS, so sandboxed commands
#   fail with "invalid cwd … not in the subpath of /workspace". Running on the
#   host lets the agent actually execute/verify in your working dir. This means
#   agent commands run on your machine — fine for local dev; set to "sandbox"
#   if you don't want that.
ATLAS_INFERENCE_URL=http://localhost:8080 \
ATLAS_LENS_URL=http://localhost:8099 \
ATLAS_SANDBOX_URL=http://localhost:8020 \
ATLAS_MODEL_NAME="$ATLAS_MODEL_NAME" \
ATLAS_GRAMMAR_MODE="${ATLAS_GRAMMAR_MODE:-gbnf}" \
ATLAS_VERIFY_IN="${ATLAS_VERIFY_IN:-host}" \
  "$PROXY_BIN" >"$LOG_DIR/atlas-proxy.log" 2>&1 &
PROXY_PID=$!
PIDS+=("$PROXY_PID")
echo "  PID $PROXY_PID → $LOG_DIR/atlas-proxy.log"
wait_healthy "atlas-proxy" "http://localhost:8090/health" 15 1

# ── Status summary ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Services running:${RESET}"
echo -e "  ${GREEN}●${RESET} llama-server    http://localhost:8080"
echo -e "  ${GREEN}●${RESET} geometric-lens  http://localhost:8099"
echo -e "  ${GREEN}●${RESET} sandbox         http://localhost:8020"
echo -e "  ${GREEN}●${RESET} redis           redis://localhost:6379"
echo -e "  ${GREEN}●${RESET} atlas-proxy     http://localhost:8090"
echo ""
echo -e "  Logs: ${LOG_DIR}/"
echo ""
echo -e "${BOLD}Launching ATLAS CLI…${RESET}"
echo -e "  Type ${CYAN}/help${RESET} for commands, ${CYAN}/quit${RESET} to exit"
echo ""

# ── Launch atlas CLI (foreground — blocks until user quits) ──────────────────
atlas

# cleanup() fires on exit
