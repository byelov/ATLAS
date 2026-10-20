# ATLAS Setup — macOS, fully native (launchd + Seatbelt, no Docker)

This guide is for **Apple Silicon Macs** that should run ATLAS with **no Docker
at all**. It was built for an M1 Ultra Mac Studio (64-core GPU, 128 GB). Any
Apple Silicon Mac with 32 GB or more works.

The [hybrid path](SETUP_MACOS.md) runs llama-server natively and the other four
services in Docker Desktop. This path runs **every** service natively:

| | Hybrid ([SETUP_MACOS.md](SETUP_MACOS.md)) | Native (this guide) |
|---|---|---|
| llama-server | native, Metal | native, Metal |
| proxy / v3 / lens / sandbox | Docker Desktop containers | per-user **launchd agents** |
| Sandbox boundary | container (read-only rootfs, cgroups) | **Seatbelt** profile (`sandbox-exec`) |
| Docker Desktop | required | not used |
| Start at login / restart on crash | `restart: unless-stopped` | launchd `RunAtLoad` + `KeepAlive` |
| Logs | `docker compose logs` | `~/Library/Logs/atlas/<service>.log` |

Each service listens on `127.0.0.1` at the **same port compose would publish**
(llama 8080, lens 8099, v3 8070, sandbox 30820, proxy 8090), so `atlas`, the TUI
and `atlas doctor` work the same way on both paths.

## Prerequisites

| Component | How to install |
|---|---|
| macOS 14+ on Apple Silicon | `uname -m` prints `arm64` |
| Xcode Command Line Tools | `xcode-select --install` |
| Homebrew | https://brew.sh |
| Everything else (cmake, go, python@3.12, python@3.13, bash, libomp, pipx) | installed by the setup script |

Toolchains used to verify generated code are optional. The setup script lists the
ones it can't find: `node`, `go`, `rustc` (rustup), `javac` (openjdk), `ruby`,
`php`.

## Install — TL;DR

```bash
git clone <this fork> ATLAS && cd ATLAS

./scripts/atlas-setup-macos.sh --native     # llama.cpp (Metal), proxy, service venvs
atlas init --deploy native                  # writes .env with ATLAS_DEPLOY=native
atlas tier fit --write --slots 6 --per-slot-cap 65536   # M1 Ultra sizing (see below)
atlas native install                        # write + load the LaunchAgents
atlas doctor                                # verify
cd /path/to/your/project && atlas           # start coding
```

## Step by step

### 1. `./scripts/atlas-setup-macos.sh --native`

This runs the hybrid setup steps first, then two more:

1. Steps 1–8, same as [SETUP_MACOS.md](SETUP_MACOS.md):
   - Builds llama.cpp at the revision pinned in `inference/Dockerfile.v31`, with
     the hidden-states and spec-decode patches, into
     `~/.atlas/macos/bin/llama-server-metal`.
   - Installs the `atlas` CLI with pipx.
   - Builds `atlas-tui`.
2. **Step 9** builds the proxy into `~/.atlas/macos/bin/atlas-proxy`.
3. **Step 10** creates one venv per service under `~/.atlas/macos/venvs/`, from
   the same pinned requirements the images use:
   - `lens/`: Python 3.12, torch from the CPU index, then `geometric-lens/requirements.txt`.
   - `v3/`: Python 3.12, `v3-service/requirements.txt`.
   - `sandbox/`: Python 3.13 (like the container, because `py_compile` must accept
     PEP 701), `sandbox/requirements-runtime.txt`. This venv runs the executor
     itself and is read-only inside the sandbox.
   - `~/.atlas/native/sandbox/home/.venv`: Python 3.13,
     `sandbox/requirements-verify.txt`. This is the **tools venv**. The `python`
     and `pip` commands that executed code calls resolve here, so `pip install`
     works without touching the executor.

Each venv records a hash of its requirements, so re-running the script only
rebuilds what changed.

### 2. `atlas init --deploy native`

The usual wizard, plus `ATLAS_DEPLOY=native` in `.env`. On a Mac the KV cache
always gets **matching K and V types**. Metal's flash-attention kernel rejects
mixed types (`ggml-metal-device.m`), and that silently moves attention onto the
CPU.

### 3. `atlas tier fit --write` — sizing for an M1 Ultra

`tier fit` reads the GGUF header and picks the largest context that fits. On Apple
Silicon its budget is the **Metal working-set limit**, not total unified memory:
- macOS lets the GPU wire about 2/3 of RAM up to 36 GiB, and about 3/4 above that.
- `sysctl iogpu.wired_limit_mb` overrides the default.
- 8 GiB is kept back for macOS and the native services.

On a 128 GB M1 Ultra the budget is 96 GiB.

Qwen3.5-9B-Q6_K is the only model with supported Lens and ASA artifacts. It is
about 7 GB, which leaves almost all of that 96 GiB for the KV cache. Spend it
like this:

```bash
atlas tier fit --write --slots 6 --per-slot-cap 65536
```

- **f16 KV cache** (`tier fit` prefers f16 whenever it fits). It is the fastest
  type on Metal and loses nothing to quantization.
- **6 slots** instead of 4, so the agent loop, V3 candidates, lens embeddings
  and a second session can each have their own slot.
- **64K per slot** instead of the default 32K cap. The model's training context
  still bounds it.

Apply a new sizing with `atlas native restart llama-server`. The TUI launcher
passes `ATLAS_CTX_SIZE` and `ATLAS_PARALLEL_SLOTS` from `.env` to the TUI, so
its per-turn budget follows the larger slots.

Optional: to give the GPU more of the 128 GB, run
`sudo sysctl iogpu.wired_limit_mb=110000`. The setting resets at reboot. Re-run
`tier fit` afterwards.

### 4. `atlas native install`

Writes one LaunchAgent per service to
`~/Library/LaunchAgents/ai.atlas.<service>.plist` and loads it:

| Agent | Runs | Waits for (compose `depends_on`) | launchd ProcessType |
|---|---|---|---|
| `ai.atlas.llama-server` | `scripts/atlas-llama-macos.sh` | — | Interactive |
| `ai.atlas.sandbox` | `sandbox-exec -f <profile> python executor_server.py` | — | Standard, nice 5 |
| `ai.atlas.geometric-lens` | `uvicorn main:app` | llama-server | Interactive |
| `ai.atlas.v3-service` | `python main.py` | llama-server, lens | Interactive |
| `ai.atlas.atlas-proxy` | `atlas-proxy` | all four | Interactive |

Every agent runs `scripts/native/atlas-service.sh <service>`. The wrapper is the
native counterpart of one compose service entry:
- It loads `.env`. The process environment wins, as with compose.
- It builds the same environment compose passes that container, from scratch
  with `env -i`.
- It waits for the services that container's `depends_on` names.
- It then execs the service.

**ProcessType matters for speed.** launchd throttles the CPU and I/O of agents
that don't set it. Everything on the request path is `Interactive`. The sandbox
runs `Standard` at nice 5, so a build or test run never competes with token
generation.

Agents start at login and restart after a crash (`KeepAlive`, 10 s throttle).
`atlas native stop` unloads and disables them, so they stay down across logins
until `atlas native start`.

### 5. `atlas doctor`

On a native install, doctor skips the Docker checks and runs these instead:
- `native/runtime`: the proxy binary and all venvs are present.
- `native/seatbelt`: `sandbox-exec` loads the generated profile.
- One `native/<service>` check per agent: installed, loaded, healthy.

The health, internal-auth, status-dimension, model, lens, ASA, tier and
end-to-end smoke checks run as usual.

### 6. `atlas`

Run it from your project directory. Workspace alignment works differently on the
native path:
- The native proxy has no `/workspace`. It reads and writes the directory each
  request names, which is the TUI's working directory.
- Only the sandbox has a fixed root, and V3 build verification needs that root to
  equal the project. When you start `atlas` somewhere new, it writes
  `ATLAS_PROJECT_DIR=$(pwd)` and restarts the sandbox (about 2 s).
- `atlas native project <dir>` does the same by hand.
- `ATLAS_AUTO_WORKSPACE=0` turns automatic alignment off.

## The sandbox under Seatbelt

The sandbox runs model-written commands (`run_command`, V3 build verification,
syntax checks). In every other deployment its boundary is a container. Here it
is a Seatbelt profile that `atlas native render-profile` regenerates on every
sandbox start, at `~/.atlas/native/sandbox/atlas-sandbox.sb`.

| Concern | Container | Native Seatbelt profile |
|---|---|---|
| Writable host paths | `/workspace` only | the project only. Toolchain caches go to a private HOME/TMPDIR under `~/.atlas/native/sandbox/` |
| Your home directory | not mounted | contents unreadable: `~/.ssh`, keychains, browser data, cloud credentials, dotfiles. Metadata stays visible |
| `secrets/`, `.env` | token mounted read-only | unreadable, even when the project is the ATLAS checkout. The executor's token stays readable (same as the container) |
| ATLAS code, binaries, LaunchAgents | not mounted | not writable (launchd runs them outside the sandbox) |
| Project git hooks / `.git/config` | writable | **not writable** (the host's git would run them) |
| Other ATLAS services | reachable on `sandbox-net` | **blocked**: proxy, llama, lens and v3 ports on localhost |
| Signals | container PID namespace | only processes inside the sandbox |
| launchctl, open, osascript, AppleEvents, clipboard, keychain CLI | n/a | **denied** |
| Internet egress | on (`ATLAS_SANDBOX_NET_INTERNAL=true` cuts it) | same switch: on by default, `true` denies all IP egress |
| Memory / CPU / PID caps | cgroups | **none**. Each command is bounded by the executor's timeouts (`ATLAS_SANDBOX_MAX_EXECUTION_TIME`) and runs at nice 5 |

Seatbelt confines a process; it is not a VM. Code determined to escape could
still talk to system services the profile allows. Every command still goes
through the proxy's permission prompts and command policy first, just as it does
on the Docker path.

## Day-to-day

```bash
atlas native status                 # launchd state + /health per service
atlas native logs atlas-proxy -f    # tail one service
atlas native restart llama-server   # after `atlas tier fit --write`
atlas native stop                   # stop everything; stays stopped across logins
atlas native start
atlas native uninstall              # unload + remove the LaunchAgents
```

**Upgrading:** `git pull`, then `./scripts/atlas-setup-macos.sh --native`, then
`atlas native install`. The install step rewrites and reloads the agents.

**State:** lens SQLite in `~/.atlas/native/state/lens/`, V3 telemetry in
`~/.atlas/native/state/v3-telemetry/`, lens training samples in
`./lens_training` (same as compose).

## Not available without Docker

These commands drive containers and don't have native versions yet:
- `atlas asa build`, which trains inside the lens container.
- `atlas upgrade` and `atlas rollback`, which work with images. Upgrade with
  `git pull` plus setup instead.
- `atlas compose`.

`atlas diagnostics collect` works and bundles the launchd logs.

## Troubleshooting

**A service shows `down` in `atlas native status`.** Run
`atlas native logs <service>`. A service whose dependency isn't healthy within
`ATLAS_NATIVE_DEP_TIMEOUT` (default 600 s) exits, and launchd retries it. The
usual cause is llama-server: a missing model file or a context that doesn't fit.
Re-run `atlas tier fit --write`.

**`missing venv … run ./scripts/atlas-setup-macos.sh --native`.** The setup
script wasn't run with `--native`, or `ATLAS_MACOS_PREFIX` points elsewhere.

**A command fails with `Operation not permitted` in the sandbox.** The Seatbelt
profile denied it. Writes outside the project, reads in your home directory, and
`launchctl`/`open` are blocked on purpose. Read the active profile at
`~/.atlas/native/sandbox/atlas-sandbox.sb`.

**`node` aborts with `Symbol not found … simdutf`.** This is a Homebrew
dependency mismatch, not ATLAS: `brew reinstall node` (or `brew upgrade`).

**Port already in use.** Every agent binds 127.0.0.1 on the port from `.env`.
Change `ATLAS_*_PORT` there and run `atlas native install` again.
