# ATLAS Setup — macOS (Apple Silicon, Hybrid Metal + Docker)

This is the install guide for **Apple Silicon Macs** (M1, M2, M3, M4). Intel Macs should use the [Vulkan path](SETUP.md#vulkan--the-universal-fallback-pc-114) instead — Metal is Apple-Silicon-only.

ATLAS on Mac uses a **hybrid architecture** (#32):

- **llama-server** runs **natively** on macOS with **Metal** GPU acceleration (5-10x faster than running it inside Docker via MoltenVK)
- **Everything else** (proxy, v3-service, geometric-lens, sandbox) runs in **Docker** via `docker-compose.macos.yml`

The hybrid keeps the rest of ATLAS unchanged from the Linux + CUDA/ROCm path while letting Mac users get native Metal inference speed.

## Prerequisites

| Component | Why | How to install |
|---|---|---|
| macOS 13.0+ (Ventura or newer) | Metal API requirements | System Settings → Software Update |
| Apple Silicon (M1/M2/M3/M4) | Metal GPU backend | `uname -m` should print `arm64` |
| 16 GB unified memory | medium tier minimum (9B-Q6 + KV cache) | 32 GB+ recommended for full context |
| Xcode Command Line Tools | cmake, git, metal-cpp headers | `xcode-select --install` |
| Homebrew | brew package manager | https://brew.sh |
| pipx | install atlas CLI in an isolated venv (Homebrew Python enforces PEP 668, plain `pip install` is blocked) | `brew install pipx` (the setup script handles this automatically) |
| Go 1.24+ | build the atlas-tui binary (Bubbletea TUI client invoked by `atlas`) | `brew install go` (the setup script handles this automatically) |
| Docker Desktop | runs the 4 non-inference services | https://docker.com/products/docker-desktop |

Notes:

- **You do NOT need full Xcode** — just the Command Line Tools (~2 GB vs ~12 GB).
- **Docker Desktop is still required** — only `llama-server` runs natively, everything else stays in containers.
- **8 GB Macs:** technically supported on the `small` tier (7B-Q4 model) but performance will be tight. 16 GB is the realistic floor.

## Install — TL;DR

```bash
git clone https://github.com/itigges22/ATLAS.git
cd ATLAS

# One-time setup (5-10 minutes): brew deps + builds llama.cpp with Metal
./scripts/atlas-setup-macos.sh

# Wizard: detects Apple Silicon, writes .env for the hybrid Metal path
atlas init

# Bring up the stack — TWO terminals:
# Terminal 1 (foreground):
./scripts/atlas-llama-macos.sh

# Terminal 2:
docker compose -f docker-compose.yml -f docker-compose.macos.yml up -d

# Verify everything is healthy
atlas doctor

# Start coding (from your project directory)
cd /path/to/your/project
atlas
```

## Install — step by step

### Step 1: Run the setup script

```bash
./scripts/atlas-setup-macos.sh
```

What this does (idempotent, re-runs are cheap):

1. Verifies macOS + Apple Silicon (errors out on Intel + offers Vulkan as alternative)
2. Checks Xcode Command Line Tools are installed
3. Verifies Homebrew is installed
4. Installs missing brew packages: `cmake`, `git`, `python@3.12`, `pipx`, `go`
5. Reads `LLAMA_CPP_REV` from `inference/Dockerfile.v31` (the pinned SHA used by the Docker images — keeps the native build in lockstep with the linux + cuda/rocm builds)
6. Fetches llama.cpp at that exact SHA, applies the PC-202 hidden-states patch + spec-decode embeddings fix
7. Builds `llama-server` with `-DGGML_METAL=ON -DGGML_METAL_USE_BF16=ON` (Apple GPU compute backend, bf16 support for M3/M4)
8. Installs the binary to `~/.atlas/macos/bin/llama-server-metal` (plus `llama-cli-metal` and `llama-cvector-generator-metal` for ASA workflows)
9. Installs the `atlas` Python CLI via `pipx install --editable` (isolated venv, dodges Homebrew Python's PEP 668 enforcement)
10. Builds the `atlas-tui` Go binary and installs it to `~/.local/bin/atlas-tui` (the Bubbletea TUI client that `atlas` shells out to for the interactive session)

Optional flags:

```bash
./scripts/atlas-setup-macos.sh --rebuild        # force rebuild even if SHA matches
./scripts/atlas-setup-macos.sh --prefix /opt/atlas  # install to a different prefix
```

The build step is the slow one (~5-10 min depending on Mac generation). The setup script skips it on re-runs when the existing binary's stored SHA matches `LLAMA_CPP_REV`.

### Step 2: Run the wizard

```bash
atlas init
```

The wizard detects Apple Silicon and writes a `.env` for the hybrid Metal path. You'll see something like:

```
[2/5] Selecting model…
  Apple Silicon detected — recommending the hybrid Metal path (V3.1.2 / #32).
  llama-server will run NATIVELY on macOS with Metal (5-10x faster than the
  Docker-via-MoltenVK fallback). Everything else (proxy, v3, lens, sandbox)
  stays in Docker. No core component changes.

  Prereq: run ./scripts/atlas-setup-macos.sh first if you haven't already.
  It installs brew deps + builds llama.cpp with Metal. See docs/SETUP_MACOS.md
  for the full walkthrough.

  Alternatives:
    --backend vulkan   slow Docker-only path (uses MoltenVK, no native build needed)

  Proceed with hybrid Metal path? [Y/n]
```

If you want the slow docker-only fallback instead (e.g. you're scripting a CI run on a Mac and don't want to install brew), re-run with `atlas init --backend vulkan`.

### Step 3: Start the native llama-server

In a **new terminal** (the launcher runs in the foreground):

```bash
./scripts/atlas-llama-macos.sh
```

This reads `.env` and starts `llama-server-metal` with the same flags as the Docker entrypoint. You'll see a banner like:

```
ATLAS llama-server (native macOS Metal) — #32 hybrid path
  Model:                /Users/you/ATLAS/models/<selected-model>.gguf
  Context length:       32768
  Parallel slots:       1
  KV cache K / V:       q8_0 / q4_0
  Port:                 8080
  ASA steering:         disabled
  Binary:               /Users/you/.atlas/macos/bin/llama-server-metal
```

Stop with Ctrl-C. On stop the docker stack's proxy will start serving 502s until you re-launch.

### Step 4: Bring up the docker stack

```bash
docker compose -f docker-compose.yml -f docker-compose.macos.yml up -d
```

The macOS overlay swaps the `llama-server` service for a tiny `alpine/socat` container that forwards Docker-internal `llama-server:8080` → `host.docker.internal:${ATLAS_LLAMA_PORT:-8080}` (where the native server you started in Step 3 is listening). The other 4 services (proxy, v3, lens, sandbox) come up unchanged from the base compose file.

If port 8080 is already occupied, set `ATLAS_LLAMA_PORT` in `.env` or launch with `./scripts/atlas-llama-macos.sh --port 8081`, then bring the compose stack up with the same `ATLAS_LLAMA_PORT` value. The container-side URL remains `http://llama-server:8080`; only the native host-side port changes.

First-time pull is small (~30 MB for socat + ~200 MB for redis if not cached; the v3 / lens / proxy / sandbox images come from GHCR, ~600 MB total).

### Step 5: Verify

```bash
atlas doctor
```

You should see (among other checks):

```
  [OK]  arch          x86_64                       # ← reads as x86_64 in Docker but you're on arm64 host
  [OK]  metal-native  native llama-server up at /Users/you/.atlas/macos/bin/llama-server-metal, listening on :8080
```

The `metal-native` check only fires when `ATLAS_BACKEND=metal` is set (which `atlas init` does on your Mac). It catches:

- Setup script was never run → binary missing
- Setup ran but binary won't execute (corrupt build) → re-run with `--rebuild`
- Native llama-server isn't running → warn (start it in step 3)

### Step 6: Use ATLAS

```bash
cd /path/to/your/project
atlas
```

Same UX as Linux + CUDA. The TUI connects to the proxy on localhost:8090; the proxy talks to the docker stack (lens, v3, sandbox) which talks to the native llama-server via socat.

## How it actually works under the hood

```
Your Mac
 |
 |- Native process: ./scripts/atlas-llama-macos.sh
 |   |- llama-server-metal listening on :${ATLAS_LLAMA_PORT:-8080} (Apple GPU via Metal)
 |
 |- Docker Desktop
     |- docker-compose stack (4 services):
     |   |- atlas-proxy        (Go binary, port 8090)
     |   |- v3-service         (Python, port 8070)
     |   |- geometric-lens     (Python, port 8099)
     |   |- sandbox            (Python, port 30820)
     |   |- redis              (existing service)
     |   |- llama-server slot  ← socat: forwards container :8080 to host.docker.internal:${ATLAS_LLAMA_PORT:-8080}
     |
     |- (Each service connects to http://llama-server:8080 from the base
     |   compose file — that name now resolves to the socat container which
     |   forwards every connection to the native server on the host.)
```

Why this design:

- **No core component changes.** The 4 docker services (proxy, v3, lens, sandbox) are unchanged from the Linux + CUDA path. The base `docker-compose.yml` is unchanged. Only the new `docker-compose.macos.yml` overlay differs.
- **Fast Metal inference.** llama.cpp built with `-DGGML_METAL=ON` uses Apple's GPU directly. MoltenVK + Docker Desktop adds 5-10x overhead which kills inference perf.
- **Standard atlas UX.** Same `atlas init` / `atlas doctor` / `atlas` commands as Linux.
- **Reversible.** Stop the native llama-server, rerun `atlas init --backend vulkan`, and you fall back to the docker-only path that uses MoltenVK. Useful for scripting.

## Troubleshooting

### `atlas doctor` says `metal-native: fail — native llama-server not found`

You haven't run the setup script, or you ran it with a custom `--prefix` and the doctor check is looking at the default. The check expects the binary at `~/.atlas/macos/bin/llama-server-metal`. Either:

- Run `./scripts/atlas-setup-macos.sh` (no flags)
- Or symlink: `ln -s /your/custom/prefix/bin/llama-server-metal ~/.atlas/macos/bin/`

### `atlas doctor` says `metal-native: warn — nothing listening on the configured llama port`

The binary is installed but you haven't started it. Open a new terminal and run `./scripts/atlas-llama-macos.sh`. The launcher stays in the foreground; leave it running.

### Native llama-server starts but Docker services can't reach it

Docker Desktop on Mac auto-resolves `host.docker.internal` to the host's loopback. If for some reason it doesn't (very old Docker Desktop, custom DNS setup):

```bash
# Inside any container, this should print an IP that points back to your Mac:
docker compose -f docker-compose.yml -f docker-compose.macos.yml exec atlas-proxy \
  nslookup host.docker.internal
```

If that fails, update Docker Desktop to 4.x or newer.

### llama-server fails to load model: `unable to allocate Metal buffer`

Unified memory is shared with the OS. Realistic GPU budget on Apple Silicon is ~70% of total RAM under load. If you're trying to load a model larger than that:

- 16 GB Mac: stick to 7B-Q4 (~4 GB) or 9B-Q4_K_M (~5.5 GB)
- 32 GB Mac: 9B-Q6 (~7.5 GB) or 14B-Q5 (~10 GB) fits comfortably
- 64 GB+ Mac: 32B-Q5 (~22 GB) or larger

Run `atlas tier` to see the recommendation for your hardware.

### `atlas --help` says `atlas-tui binary not found and Go is not available to build it`

You ran an older setup script that didn't install Go + build the TUI. Two recovery paths:

1. **Re-run the latest setup script** (it installs `go` via brew + runs the build in step 8):
   ```bash
   git pull origin dev
   ./scripts/atlas-setup-macos.sh
   ```

2. **Manual fix without re-running setup** (skip the cmake rebuild):
   ```bash
   brew install go
   cd <ATLAS-repo>/tui && go build -o ~/.local/bin/atlas-tui .
   ```

Either way, `atlas --help` should then show the CLI usage without errors.

### Setup script fails at step 7 with `error: externally-managed-environment`

This is Homebrew Python's PEP 668 enforcement — `pip install` and `pip install --user` are blocked on macOS because they could break the brew install. The setup script already handles this by using `pipx` (installed in step 3), so this error means you're on an older version of the setup script. Two recovery paths:

1. **Re-run the latest setup script** (it now installs `pipx` automatically and uses it for the atlas install):
   ```bash
   git pull origin dev
   ./scripts/atlas-setup-macos.sh
   ```

2. **Manual fix without re-running setup** (skip the cmake rebuild):
   ```bash
   brew install pipx
   pipx ensurepath
   cd ~/ATLAS
   pipx install --force --editable .
   source ~/.zprofile     # reload PATH
   ```

Either path puts the `atlas` binary in `~/.local/bin/` with its dependencies isolated in a pipx-managed venv. `git pull` upgrades atlas in place because we used `--editable`.

### Setup script fails at `PC-202 patch does not apply`

Upstream llama.cpp has drifted past the pinned SHA. See [docs/TROUBLESHOOTING.md § llama.cpp patch drift](TROUBLESHOOTING.md#llamacpp-patch-drift-when-the-publish-workflow-fails-at-patch-does-not-apply) for the bump runbook.

### I want to skip the native build entirely (use only Docker)

The Vulkan-via-MoltenVK path still works:

```bash
atlas init --backend vulkan
docker compose -f docker-compose.yml -f docker-compose.vulkan.yml up -d
```

Inference will be 5-10x slower but you don't need brew, cmake, or the setup script.

## What this changes vs the standard install

This is intentionally a small change to keep things easy to maintain:

| File | Change |
|---|---|
| `scripts/atlas-setup-macos.sh` | NEW |
| `scripts/atlas-llama-macos.sh` | NEW |
| `docker-compose.macos.yml` | NEW |
| `docs/SETUP_MACOS.md` | NEW (this file) |
| `atlas/cli/commands/init.py` | new branch for darwin + apple silicon |
| `atlas/cli/commands/doctor.py` | new `_check_metal_native()` |
| `atlas/cli/commands/tier.py` | `apple` vendor flipped from unsupported → supported |
| `docker-compose.yml` | **UNCHANGED** |
| All other service code | **UNCHANGED** |

Linux + CUDA / ROCm installs see zero behavior change.

## Roadmap

- [ ] Hardware validation on M3 Pro 18 GB
- [ ] Hardware validation on M3 Max 36+ GB
- [ ] Hardware validation on M4 series
- [ ] Pre-built `llama-server-metal` binaries on GHCR releases (skip the build step)
- [ ] Pure-native path (drop Docker entirely on Mac, use launchd) — separate ticket if there's demand

Report issues on [#32](https://github.com/itigges22/ATLAS/issues/32) with your Mac model + memory size + `atlas doctor` output.
