#!/usr/bin/env bash
# ATLAS native macOS service wrapper — the program every launchd agent runs.
#
#   scripts/native/atlas-service.sh <service>
#
# <service> is one of: llama-server, sandbox, geometric-lens, v3-service,
# atlas-proxy. `atlas native install` writes one LaunchAgent per service
# (~/Library/LaunchAgents/<prefix>.<service>.plist) that runs this script.
#
# The wrapper is the native stand-in for one docker-compose service entry:
# it loads .env (process environment wins, matching Compose), sets the same
# variables docker-compose.yml passes that container, waits for the
# services compose would list under depends_on, then execs the service on
# 127.0.0.1 at the SAME host port compose publishes — so the CLI, TUI and
# `atlas doctor` reach a native stack exactly like a docker one.
#
# The sandbox is execed under /usr/bin/sandbox-exec with a Seatbelt profile
# rendered by `atlas native render-profile` (see atlas/commands/native.py).
#
# ATLAS_NATIVE_DRY_RUN=1 prints the resolved environment and command
# instead of exec'ing (used by the tests).

set -euo pipefail

SERVICE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATLAS_ROOT="${ATLAS_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
export ATLAS_ROOT

log() { printf '[atlas-service %s] %s\n' "$SERVICE" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

case "$SERVICE" in
  llama-server|sandbox|geometric-lens|v3-service|atlas-proxy) ;;
  *) echo "usage: $0 {llama-server|sandbox|geometric-lens|v3-service|atlas-proxy}" >&2
     exit 2;;
esac

# ---------------------------------------------------------------------------
# .env as defaults (same parser as scripts/atlas-llama-macos.sh: never
# executed as shell code; an already-set process variable wins).
# ---------------------------------------------------------------------------
if [[ -f "$ATLAS_ROOT/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if printenv "$key" >/dev/null 2>&1; then
      continue
    fi
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ ( "$value" == \"*\" && "$value" == *\" ) ||
          ( "$value" == \'*\' && "$value" == *\' ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  done < "$ATLAS_ROOT/.env"
fi

# Resolve a path the way compose resolves bind-mount sources: relative to
# the checkout, with a leading ~/ expanded.
abs_path() {
  local p="$1"
  local tilde
  tilde="$(printf '\176/')"
  if [[ "$p" == "$tilde"* ]]; then
    p="$HOME/${p:2}"
  fi
  if [[ "$p" != /* ]]; then
    p="$ATLAS_ROOT/${p#./}"
  fi
  # Strip a trailing "/." or "/" so "." resolves to the checkout itself.
  p="${p%/.}"
  [[ "$p" != "/" ]] && p="${p%/}"
  printf '%s\n' "$p"
}

PREFIX="$(abs_path "${ATLAS_MACOS_PREFIX:-$HOME/.atlas/macos}")"
NATIVE_HOME="$(abs_path "${ATLAS_NATIVE_HOME:-$HOME/.atlas/native}")"
BIND_HOST="127.0.0.1"

LLAMA_PORT="${ATLAS_LLAMA_PORT:-8080}"
LENS_PORT="${ATLAS_LENS_PORT:-8099}"
V3_PORT="${ATLAS_V3_PORT:-8070}"
SANDBOX_PORT="${ATLAS_SANDBOX_PORT:-30820}"
PROXY_PORT="${ATLAS_PROXY_PORT:-8090}"

LLAMA_URL="http://$BIND_HOST:$LLAMA_PORT"
LENS_URL="http://$BIND_HOST:$LENS_PORT"
V3_URL="http://$BIND_HOST:$V3_PORT"
SANDBOX_URL="http://$BIND_HOST:$SANDBOX_PORT"

# The sandbox's workspace root. Resolved through symlinks: the executor
# compares resolved cwds against it, and Seatbelt matches real paths
# (/tmp is /private/tmp). `atlas` re-points it at the directory it is
# launched from (atlas/runtime.py, the native _align_workspace).
PROJECT_DIR="$(abs_path "${ATLAS_PROJECT_DIR:-.}")"
if [[ -d "$PROJECT_DIR" ]]; then
  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
fi
MODELS_DIR="$(abs_path "${ATLAS_MODELS_DIR:-./models}")"
SECRETS_DIR="$(abs_path "${ATLAS_SECRETS_DIR:-./secrets}")"
TOKEN_FILE="$SECRETS_DIR/service-token"
MODEL_NAME="${ATLAS_MODEL_NAME:?ATLAS_MODEL_NAME not set — run atlas init}"

VENVS="$PREFIX/venvs"
STATE="$NATIVE_HOME/state"

# Services in the container get the token file only when atlas init wrote
# one; mirror that so an install without auth still starts.
# (Arrays that may be empty are expanded as ${a[@]+"${a[@]}"}: macOS ships
# bash 3.2, which treats "${a[@]}" of an empty array as unbound under -u.)
token_env=()
if [[ -s "$TOKEN_FILE" ]]; then
  token_env=(ATLAS_SERVICE_TOKEN_FILE="$TOKEN_FILE")
fi

# Passthrough: copy NAME into the service env only when set (compose's
# `${NAME:-}` leaves it empty, which every consumer treats as unset).
passthrough() {
  local name
  for name in "$@"; do
    if [[ -n "${!name:-}" ]]; then
      svc_env+=("$name=${!name}")
    fi
  done
}

# depends_on: condition: service_healthy. Blocks until each URL's /health
# answers, then returns; a dependency that never comes up makes this exit
# non-zero so launchd restarts the job after its ThrottleInterval.
wait_healthy() {
  local url deadline
  deadline=$(( $(date +%s) + ${ATLAS_NATIVE_DEP_TIMEOUT:-600} ))
  for url in "$@"; do
    until curl -sf -m 3 -o /dev/null "$url/health"; do
      if (( $(date +%s) >= deadline )); then
        die "dependency $url not healthy after ${ATLAS_NATIVE_DEP_TIMEOUT:-600}s"
      fi
      sleep 2
    done
  done
}

venv_python() {
  local py="$VENVS/$1/bin/python"
  [[ -x "$py" ]] || die "missing venv $VENVS/$1 — run ./scripts/atlas-setup-macos.sh --native"
  printf '%s\n' "$py"
}

# The service's environment is built from scratch (env -i) so nothing from
# the launchd session leaks in; this list is the whole of it.
svc_env=(
  HOME="$HOME"
  PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  LANG="${LANG:-en_US.UTF-8}"
  ATLAS_LOG_FORMAT="${ATLAS_LOG_FORMAT:-}"
)
deps=()
workdir="$ATLAS_ROOT"
cmd=()

case "$SERVICE" in
  # -------------------------------------------------------------------------
  llama-server)
    # scripts/atlas-llama-macos.sh already mirrors inference/entrypoint-v3.1.sh
    # (sizing from .env, ASA control vector, --api-key-file, loopback bind).
    svc_env+=(ATLAS_ROOT="$ATLAS_ROOT" ATLAS_LLAMA_HOST="$BIND_HOST")
    passthrough ATLAS_MACOS_PREFIX ATLAS_MODELS_DIR ATLAS_MODEL_FILE \
      ATLAS_MODEL_NAME ATLAS_CTX_SIZE ATLAS_PARALLEL_SLOTS ATLAS_KV_TYPE_K \
      ATLAS_KV_TYPE_V ATLAS_BATCH ATLAS_UBATCH ATLAS_LLAMA_PORT \
      ATLAS_CONTROL_VECTOR ATLAS_CONTROL_VECTOR_SCALE \
      ATLAS_CONTROL_VECTOR_LAYER_RANGE ATLAS_CONTROL_VECTOR_ALLOW_UNVERIFIED \
      ATLAS_EMBED_POOLING ATLAS_SERVICE_TOKEN_FILE TMPDIR
    cmd=(/bin/bash "$ATLAS_ROOT/scripts/atlas-llama-macos.sh")
    ;;

  # -------------------------------------------------------------------------
  geometric-lens)
    # Compose bind-mounts ATLAS_LENS_MODELS over the lens's artifact dir;
    # natively the lens reads the same directory from ATLAS_LENS_MODELS_DIR.
    lens_models="$(abs_path "${ATLAS_LENS_MODELS:-./geometric-lens/geometric_lens/models}")"
    mkdir -p "$STATE/lens"
    svc_env+=(
      ATLAS_LENS_MODELS_DIR="$lens_models"
      LLAMA_URL="$LLAMA_URL"
      LLAMA_EMBED_URL="$LLAMA_URL"
      ATLAS_MODEL_NAME="$MODEL_NAME"
      GEOMETRIC_LENS_ENABLED=true
      SQLITE_DB_PATH="$STATE/lens/geometric_state.db"
      PYTHONDONTWRITEBYTECODE=1
      # torch and xgboost each bundle an OpenMP runtime on macOS (the Linux
      # images share libgomp). Once a calibrated G(x) is loaded both live
      # in this process and libomp aborts at startup ("OMP: Error #15").
      # The lens scores one vector at a time, so run single-threaded,
      # which keeps the two runtimes from ever running worker threads.
      KMP_DUPLICATE_LIB_OK=TRUE
      OMP_NUM_THREADS=1
      ${token_env[@]+"${token_env[@]}"}
    )
    deps=("$LLAMA_URL")
    workdir="$ATLAS_ROOT/geometric-lens"
    cmd=("$(venv_python lens)" -m uvicorn main:app
         --host "$BIND_HOST" --port "$LENS_PORT")
    ;;

  # -------------------------------------------------------------------------
  v3-service)
    mkdir -p "$STATE/v3-telemetry"
    svc_env+=(
      ATLAS_INFERENCE_URL="$LLAMA_URL"
      ATLAS_LENS_URL="$LENS_URL"
      ATLAS_SANDBOX_URL="$SANDBOX_URL"
      ATLAS_MODEL_NAME="$MODEL_NAME"
      ATLAS_CALL_GRAPH="${ATLAS_CALL_GRAPH:-0}"
      ATLAS_V3_TELEMETRY_DIR="${ATLAS_V3_TELEMETRY_DIR:-$STATE/v3-telemetry}"
      ATLAS_V3_HOST="$BIND_HOST"
      ATLAS_V3_PORT="$V3_PORT"
      PYTHONDONTWRITEBYTECODE=1
      ${token_env[@]+"${token_env[@]}"}
    )
    passthrough ATLAS_PLAN_THINKING ATLAS_V3_TIMEOUT
    deps=("$LLAMA_URL" "$LENS_URL")
    workdir="$ATLAS_ROOT/v3-service"
    cmd=("$(venv_python v3)" main.py)
    ;;

  # -------------------------------------------------------------------------
  sandbox)
    # The container's tmpfs mounts become a private HOME + TMPDIR under
    # $NATIVE_HOME/sandbox. Toolchains write their caches there, never
    # into the real home (which the Seatbelt profile makes unreadable).
    sbx="$NATIVE_HOME/sandbox"
    sbx_home="$sbx/home"
    sbx_tmp="$sbx/tmp"
    mkdir -p "$sbx_home/.cache" "$sbx_home/go" "$sbx_home/.cargo" "$sbx_tmp/sandbox"
    [[ -d "$PROJECT_DIR" ]] || die "ATLAS_PROJECT_DIR does not exist: $PROJECT_DIR"
    profile="$sbx/atlas-sandbox.sb"
    # Two Python 3.13 venvs (3.13 like the container: py_compile must accept
    # PEP 701). The executor's own venv is read-only inside the sandbox; the
    # tools venv in the private HOME is what `python`/`pip` resolve to for
    # executed code, so `pip install` works without touching the executor.
    py="$(venv_python sandbox)"
    tools_venv="$sbx_home/.venv"
    [[ -x "$tools_venv/bin/python" ]] || \
      die "missing $tools_venv — run ./scripts/atlas-setup-macos.sh --native"

    # Homebrew's openjdk is keg-only, so `javac` on PATH is Apple's stub,
    # which only finds JDKs registered under /Library/Java or ~/Library/Java.
    java_home="${ATLAS_SANDBOX_JAVA_HOME:-}"
    if [[ -z "$java_home" ]]; then
      for jdk in /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
                 /usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home; do
        if [[ -x "$jdk/bin/javac" ]]; then java_home="$jdk"; break; fi
      done
    fi

    sbx_path="$tools_venv/bin:$sbx_home/.local/bin:${java_home:+$java_home/bin:}/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    extra_env=()
    if [[ -n "$java_home" ]]; then
      extra_env+=(JAVA_HOME="$java_home")
    fi
    # rustup keeps its toolchains in the real home; expose them read-only.
    if [[ -d "$HOME/.rustup" && -d "$HOME/.cargo/bin" ]]; then
      sbx_path="$sbx_path:$HOME/.cargo/bin"
      extra_env+=(RUSTUP_HOME="$HOME/.rustup")
    fi

    PYTHONPATH="$ATLAS_ROOT" "$py" -m atlas.commands.native render-profile \
      --out "$profile" \
      --project "$PROJECT_DIR" \
      --sandbox-home "$sbx_home" \
      --sandbox-tmp "$sbx_tmp" \
      --venv "$VENVS/sandbox" \
      --secrets "$SECRETS_DIR" \
      --token-file "$TOKEN_FILE" \
      --atlas-root "$ATLAS_ROOT" \
      --prefix "$PREFIX" \
      --deny-port "$LLAMA_PORT" --deny-port "$LENS_PORT" \
      --deny-port "$V3_PORT" --deny-port "$PROXY_PORT" \
      ${ATLAS_SANDBOX_NET_INTERNAL:+--net-internal "$ATLAS_SANDBOX_NET_INTERNAL"}

    # The executor treats an unreadable token file as "auth disabled". The
    # token exists, so if the profile hides it, refuse to start open.
    if [[ ${#token_env[@]} -gt 0 && "${ATLAS_NATIVE_DRY_RUN:-0}" != "1" ]] &&
       ! /usr/bin/sandbox-exec -f "$profile" /bin/cat "$TOKEN_FILE" >/dev/null 2>&1; then
      die "the Seatbelt profile hides $TOKEN_FILE; the executor would run without auth"
    fi

    svc_env=(
      HOME="$sbx_home"
      TMPDIR="$sbx_tmp/"
      PATH="$sbx_path"
      LANG="${LANG:-en_US.UTF-8}"
      ATLAS_LOG_FORMAT="${ATLAS_LOG_FORMAT:-}"
      CARGO_HOME="$sbx_home/.cargo"
      GOPATH="$sbx_home/go"
      GOCACHE="$sbx_home/.cache/go-build"
      npm_config_cache="$sbx_home/.npm"
      PIP_CACHE_DIR="$sbx_home/.cache/pip"
      WORKSPACE_BASE="$sbx_tmp/sandbox"
      ATLAS_SANDBOX_WORKSPACE_ROOT="$PROJECT_DIR"
      ATLAS_SANDBOX_HOST="$BIND_HOST"
      ATLAS_SANDBOX_PORT="$SANDBOX_PORT"
      MAX_EXECUTION_TIME="${ATLAS_SANDBOX_MAX_EXECUTION_TIME:-300}"
      ATLAS_SHELL_SNAPSHOT_MAX_FILES="${ATLAS_SHELL_SNAPSHOT_MAX_FILES:-20000}"
      ATLAS_SHELL_SNAPSHOT_MAX_BYTES="${ATLAS_SHELL_SNAPSHOT_MAX_BYTES:-268435456}"
      ATLAS_SHELL_SNAPSHOT_MAX_FILE_BYTES="${ATLAS_SHELL_SNAPSHOT_MAX_FILE_BYTES:-16777216}"
      VIRTUAL_ENV="$tools_venv"
      PYTHONDONTWRITEBYTECODE=1
      ${extra_env[@]+"${extra_env[@]}"}
      ${token_env[@]+"${token_env[@]}"}
    )
    workdir="$ATLAS_ROOT/sandbox"
    cmd=(/usr/bin/sandbox-exec -f "$profile" "$py" executor_server.py)
    ;;

  # -------------------------------------------------------------------------
  atlas-proxy)
    lens_data="$(abs_path "${ATLAS_LENS_HOST_DIR:-./lens_training}")"
    mkdir -p "$lens_data"
    proxy_bin="$PREFIX/bin/atlas-proxy"
    [[ -x "$proxy_bin" ]] || die "missing $proxy_bin — run ./scripts/atlas-setup-macos.sh --native"
    svc_env+=(
      ATLAS_GRAMMAR_MODE="${ATLAS_GRAMMAR_MODE:-strict}"
      ATLAS_PROXY_HOST="$BIND_HOST"
      ATLAS_PROXY_PORT="$PROXY_PORT"
      ATLAS_INFERENCE_URL="$LLAMA_URL"
      ATLAS_LLAMA_URL="$LLAMA_URL"
      ATLAS_LENS_URL="$LENS_URL"
      ATLAS_SANDBOX_URL="$SANDBOX_URL"
      ATLAS_V3_URL="$V3_URL"
      ATLAS_MODEL_NAME="$MODEL_NAME"
      ATLAS_MODELS_DIR="$MODELS_DIR"
      ATLAS_CONTROL_VECTOR="$MODELS_DIR/ast_edit_steering.gguf"
      ATLAS_LENS_DATA_DIR="$lens_data"
      ATLAS_CTX_SIZE="${ATLAS_CTX_SIZE:-131072}"
      ATLAS_PARALLEL_SLOTS="${ATLAS_PARALLEL_SLOTS:-${PARALLEL_SLOTS:-4}}"
      ATLAS_DEDUP_READS="${ATLAS_DEDUP_READS:-1}"
      ATLAS_CALL_GRAPH="${ATLAS_CALL_GRAPH:-0}"
      ATLAS_VERIFY_IN="${ATLAS_VERIFY_IN:-sandbox}"
      ${token_env[@]+"${token_env[@]}"}
    )
    passthrough ATLAS_TRUST_MODE ATLAS_ALLOW_CREDENTIAL_READS \
      ATLAS_PERMISSION_TIMEOUT_SEC ATLAS_REASONING_BUDGET ATLAS_DRY_MULTIPLIER \
      ATLAS_DRY_BASE ATLAS_DRY_ALLOWED_LENGTH ATLAS_DRY_PENALTY_LAST_N \
      ATLAS_REPEAT_PENALTY ATLAS_REPEAT_LAST_N ATLAS_MAX_TURNS ATLAS_V3_TIMEOUT \
      ATLAS_MAX_TOKENS ATLAS_MAX_COMPLETION_TOKENS ATLAS_AGENT_HISTORY_BUDGET \
      ATLAS_LENS_RETRAIN_MIN ATLAS_KEEP_LLAMA_WARM ATLAS_FRESH_SLOT_PER_SESSION
    # ATLAS_WORKSPACE_DIR stays unset: there is no /workspace to translate
    # to, so the proxy reads and writes the directory each request names
    # (the TUI's cwd), contained by os.OpenRoot.
    deps=("$LLAMA_URL" "$LENS_URL" "$V3_URL" "$SANDBOX_URL")
    workdir="$ATLAS_ROOT"
    cmd=("$proxy_bin")
    ;;
esac

if [[ "${ATLAS_NATIVE_DRY_RUN:-0}" == "1" ]]; then
  printf 'workdir=%s\n' "$workdir"
  printf 'deps=%s\n' "${deps[*]:-}"
  printf 'env=%s\n' "${svc_env[@]}"
  printf 'cmd=%s\n' "${cmd[*]}"
  exit 0
fi

if (( ${#deps[@]} )); then
  log "waiting for: ${deps[*]}"
  wait_healthy "${deps[@]}"
fi

cd "$workdir"
log "starting: ${cmd[*]}"
exec /usr/bin/env -i "${svc_env[@]}" "${cmd[@]}"
