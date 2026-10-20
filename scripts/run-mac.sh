#!/usr/bin/env bash
# run-mac.sh
# Start all ATLAS services on macOS (Metal) and launch the CLI.
# Run from the project root: bash scripts/run-mac.sh
#
# Services started (each in its own background process, log to /tmp/atlas-logs/):
#   llama-server  :8080  (Metal GPU)
#   geometric-lens :8099 (Python / FastAPI)
#   sandbox        :8020 (Python / FastAPI)
#   v3-service     :8070 (Python — V3 pipeline: PlanSearch, candidates, Lens selection)
#   atlas-proxy    :8090 (Go — needed for Aider integration)
#   redis          :6379 (via brew services)
#
# Every service binds to 127.0.0.1 — nothing here has auth.
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

# ── Configuration ─────────────────────────────────────────────────────────────
# M1 Ultra 128 GB defaults: 131072 total context across 4 slots = 32 K per
# slot, matching max_input_tokens in .aider.model.metadata.json. f16 KV.
CONTEXT_LENGTH="${CONTEXT_LENGTH:-131072}"
PARALLEL_SLOTS="${PARALLEL_SLOTS:-4}"
KV_CACHE_TYPE_K="${KV_CACHE_TYPE_K:-f16}"
KV_CACHE_TYPE_V="${KV_CACHE_TYPE_V:-f16}"
BIND_HOST="127.0.0.1"

# ── Cleanup on exit ───────────────────────────────────────────────────────────
# Only the processes this script started are stopped — never whatever else
# happens to be listening on the same ports.
PIDS=()
cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping ATLAS services…${RESET}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    for _ in 1 2 3 4 5; do
        alive=0
        for pid in "${PIDS[@]}"; do
            kill -0 "$pid" 2>/dev/null && alive=1
        done
        [[ $alive -eq 0 ]] && break
        sleep 1
    done
    for pid in "${PIDS[@]}"; do
        kill -9 "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo -e "${GREEN}All services stopped.${RESET}"
}
trap cleanup EXIT INT TERM

# ── Port helper ───────────────────────────────────────────────────────────────
# free_port PORT PATTERN — if PORT is held by a leftover ATLAS process whose
# command line matches PATTERN, stop it; if it is held by anything else,
# refuse to start rather than kill an unrelated program.
free_port() {
    local port="$1" pattern="$2" pids pid cmd
    pids=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null) || true
    [[ -z "$pids" ]] && return 0
    for pid in $pids; do
        cmd=$(ps -o command= -p "$pid" 2>/dev/null) || continue
        if [[ "$cmd" =~ $pattern ]]; then
            warn "Port $port held by a previous ATLAS process (PID $pid) — stopping it"
            kill "$pid" 2>/dev/null || true
        else
            error "Port $port is in use by another program (PID $pid: ${cmd:0:80}). Stop it or free the port."
        fi
    done
    for _ in 1 2 3 4 5; do
        lsof -nP -iTCP:"$port" -sTCP:LISTEN -t &>/dev/null || return 0
        sleep 1
    done
    error "Port $port is still in use after stopping the previous ATLAS process"
}

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

free_port 8080 'llama-server'

CONTEXT_LENGTH="$CONTEXT_LENGTH" PARALLEL_SLOTS="$PARALLEL_SLOTS" \
KV_CACHE_TYPE_K="$KV_CACHE_TYPE_K" KV_CACHE_TYPE_V="$KV_CACHE_TYPE_V" \
ATLAS_LLAMA_HOST="$BIND_HOST" ATLAS_LLAMA_PORT=8080 \
    bash inference/entrypoint-metal.sh >"$LOG_DIR/llama-server.log" 2>&1 &
LLAMA_PID=$!
PIDS+=("$LLAMA_PID")
echo "  PID $LLAMA_PID → $LOG_DIR/llama-server.log"

wait_healthy "llama-server" "http://localhost:8080/health" 60 2

# ── 3. Geometric Lens ────────────────────────────────────────────────────────
step "Geometric Lens (port 8099)"

free_port 8099 'uvicorn main:app'

LLAMA_URL=http://localhost:8080 \
LLAMA_EMBED_URL=http://localhost:8080 \
GEOMETRIC_LENS_ENABLED=true \
PROJECT_DATA_DIR=/tmp/atlas-projects \
REDIS_URL=redis://localhost:6379 \
  bash -c "cd geometric-lens && exec python -m uvicorn main:app --host $BIND_HOST --port 8099" \
  >"$LOG_DIR/geometric-lens.log" 2>&1 &
LENS_PID=$!
PIDS+=("$LENS_PID")
echo "  PID $LENS_PID → $LOG_DIR/geometric-lens.log"

wait_healthy "geometric-lens" "http://localhost:8099/health" 30 2

# ── 4. Sandbox ───────────────────────────────────────────────────────────────
step "Sandbox (port 8020)"

free_port 8020 'executor_server\.py'

SANDBOX_HOST="$BIND_HOST" SANDBOX_PORT=8020 \
  bash -c 'cd sandbox && exec python executor_server.py' >"$LOG_DIR/sandbox.log" 2>&1 &
SANDBOX_PID=$!
PIDS+=("$SANDBOX_PID")
echo "  PID $SANDBOX_PID → $LOG_DIR/sandbox.log"

wait_healthy "sandbox" "http://localhost:8020/health" 30 2

# ── 5. V3 pipeline service ───────────────────────────────────────────────────
# Without it the proxy's /health probe fails and every T2+ task silently
# skips the V3 pipeline.
step "V3 service (port 8070)"

free_port 8070 'main\.py'

ATLAS_INFERENCE_URL=http://localhost:8080 \
ATLAS_LENS_URL=http://localhost:8099 \
ATLAS_SANDBOX_URL=http://localhost:8020 \
ATLAS_MODEL_NAME=Qwen3.5-9B-Q6_K \
ATLAS_V3_HOST="$BIND_HOST" \
ATLAS_V3_PORT=8070 \
  bash -c 'cd v3-service && exec python main.py' >"$LOG_DIR/v3-service.log" 2>&1 &
V3_PID=$!
PIDS+=("$V3_PID")
echo "  PID $V3_PID → $LOG_DIR/v3-service.log"

wait_healthy "v3-service" "http://localhost:8070/health" 30 2

# ── 6. atlas-proxy ───────────────────────────────────────────────────────────
step "atlas-proxy (port 8090)"

PROXY_BIN="${HOME}/.local/bin/atlas-proxy"
if [[ ! -x "$PROXY_BIN" ]]; then
    warn "atlas-proxy not found — building now"
    (cd atlas-proxy && go build -o "$PROXY_BIN" .)
fi

free_port 8090 'atlas-proxy'

ATLAS_INFERENCE_URL=http://localhost:8080 \
ATLAS_LENS_URL=http://localhost:8099 \
ATLAS_SANDBOX_URL=http://localhost:8020 \
ATLAS_V3_URL=http://localhost:8070 \
ATLAS_PROXY_PORT=8090 \
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
echo -e "  ${GREEN}●${RESET} v3-service      http://localhost:8070"
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
