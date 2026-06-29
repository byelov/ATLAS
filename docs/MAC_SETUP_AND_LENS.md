# ATLAS on macOS (Apple Silicon / Metal) — Repeatable Runbook

A start-to-finish guide to run ATLAS on an M-series Mac in a conda env, and to
build a **model-matched Geometric Lens** so the G(x) verification layer works
for *any* model you select — not just the default.

Everything here is reproducible on a fresh M1/M2/M3/M4. The only per-machine
variable is the model you choose (see [Selecting a model](#2-selecting-a-model)).

---

## 0. Prerequisites

```bash
brew install --cask miniforge      # conda (Apple Silicon native)
brew install go cmake redis git
xcode-select --install             # if git/clang are missing
```

The toolchain is: **conda env `atlas`** (Python 3.12) for the Python services and
CLI, **llama.cpp built with Metal** for inference, **Go** for the proxy, and
**Redis** for the lens pattern cache.

---

## 1. One-time setup

From the repo root:

```bash
bash scripts/setup-mac.sh
```

This is idempotent and does:

1. Check prerequisites (Homebrew, conda, Go, cmake, git).
2. Create conda env **`atlas`** (Python 3.12) — skipped if it already exists.
3. Install Python deps for all services + `pip install -e .` (the `atlas` CLI).
4. Install Redis.
5. Build `llama-server` with Metal and symlink it to `/usr/local/bin`.
6. Download the default model (`Qwen3.5-9B-Q6_K`) into the HF cache.
7. Download the base Geometric Lens C(x) weights.

> **Note:** setup ships the **C(x)** weights only. The **G(x)** classifier is
> model-specific and you build it yourself — see
> [Building a model-matched lens](#4-building-a-model-matched-geometric-lens-gx).

---

## 2. Selecting a model

The default is `Qwen3.5-9B-Q6_K`. To use a different one, set two things so the
whole stack agrees:

| What | Where | Why |
|------|-------|-----|
| `MODEL_PATH` (or HF id) | `inference/entrypoint-metal.sh` | which `.gguf` llama-server loads |
| `ATLAS_MODEL_NAME` | exported before `run-mac.sh`, or edit its default | couples the lens artifacts + tags proxy/CLI requests to the model identity |

The two **must refer to the same model** — the lens enforces this with a
`model_identity.json` check (a mismatched lens is refused rather than producing
garbage scores). `ATLAS_MODEL_NAME` is matched case-insensitively against the
model file's basename minus `.gguf` (e.g. `Qwen3.5-9B-Q6_K`).

```bash
# 1. Pull the GGUF from Hugging Face (cached under ~/.cache/huggingface)
conda activate atlas
python3 - <<'PY'
from huggingface_hub import hf_hub_download
p = hf_hub_download("unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf")  # repo, file
print("downloaded:", p)
PY

# 2. Point llama-server at it and tag the stack with the matching identity
export ATLAS_MODEL_NAME="Qwen3.5-9B-Q4_K_M"
MODEL_PATH=~/.cache/huggingface/hub/models--unsloth--Qwen3.5-9B-GGUF/snapshots/*/Qwen3.5-9B-Q4_K_M.gguf \
  bash scripts/run-mac.sh
```

(Models known to the registry can also be resolved by name — see
`atlas/cli/commands/model_registry.py` for supported entries and their HF repos.)

llama-server **must be started with `--embeddings`** (the macOS entrypoint already
is) — the lens reads the model's own hidden-state embeddings for C(x)/G(x).

---

## 3. Running the stack

```bash
bash scripts/run-mac.sh
```

Starts, in order, waiting for each to be healthy:

| Service | Port | Notes |
|---------|------|-------|
| Redis | 6379 | via `brew services` |
| llama-server (Metal) | 8080 | loads the model, `--embeddings` on |
| geometric-lens | 8099 | C(x)/G(x) scoring (FastAPI) |
| sandbox | 8020 | isolated code execution |
| proxy | 8090 | grammar-constrained agent loop (Go) |

Then it drops you into the interactive `atlas` REPL. `/help` for commands,
`/quit` to exit. On exit it tears down every service.

Logs for each service live in `/tmp/atlas-logs/`.

> **PATH safety:** `run-mac.sh` forces the `atlas` env to the front of `PATH`
> after `conda activate atlas`, so an auto-activated env (e.g. one a directory
> hook activates) cannot shadow it. If `which python` isn't inside the atlas env
> the script aborts early rather than running services against the wrong Python.

---

## 4. Building a model-matched Geometric Lens (G(x))

The lens artifacts are **coupled to one model**. With the wrong (or no) G(x)
artifact, `atlas lens check` reports `needs-build` and the lens runs with C(x)
only — G(x) verdicts come back `unavailable`. To enable G(x) for your selected
model, train it once.

### 4.1 Probe compatibility

With llama-server running (port 8080):

```bash
conda activate atlas
ATLAS_INFERENCE_URL=http://localhost:8080 atlas lens check
```

- `verdict: ready` → G(x) is already calibrated for this model. Done.
- `verdict: needs-build` → continue below. The probe also prints the model's
  **embedding dim** (e.g. 4096) — the lens artifacts must match it.

### 4.2 Get labeled training samples

`atlas lens build` needs examples of this model's own code labeled pass/fail.
It does **not** ship a dataset. Three sources:

1. **`--from-results <dir>`** — a benchmark results directory of per-task JSONs
   (each with `code` + `passed`) produced by `atlas bench`. Point at the
   `per_task/` subfolder.
2. **`--samples <file>`** — a labeled file: `[{"text": "<code>", "label": 0|1}, ...]`.
3. **collected agent samples** — passes you rated 👍/👎 during real use
   (`atlas lens retrain`).

> **Gotcha:** a result set is only usable if its **failures still contain code**.
> Some runs save no `code` on failed tasks → 0 usable FAIL samples, and
> contrastive training needs both classes. Check first:
>
> ```bash
> python3 - <<'PY'
> import json, glob, os
> d = "docs/reports/ablation/condition_c_phase1_2/v3_lcb/per_task"   # your dir
> p = f = 0
> for fp in glob.glob(os.path.join(d, "*.json")):
>     v = json.load(open(fp))
>     if not (v.get("code") or "").strip(): continue
>     (p := p+1) if v.get("passed") else (f := f+1)
> print(f"usable  pass={p}  fail={f}")
> PY
> ```
>
> You want a healthy count in **both** columns.

### 4.3 Build

The G(x) trainer needs **scikit-learn** and **xgboost** on the host (and,
optionally, **safetensors** for a pickle-free C(x) twin). These are in
`geometric-lens/requirements.txt`, so a fresh `setup-mac.sh` installs them; if
you set the env up before they were added, install them explicitly:

```bash
conda activate atlas
pip install scikit-learn xgboost safetensors
```

llama-server must be running. Run from the repo root, in the `atlas` env:

```bash
conda activate atlas
export PATH="$(conda info --base)/envs/atlas/bin:$PATH"   # ensure atlas python
export LLAMA_URL=http://localhost:8080
export LLAMA_EMBED_URL=http://localhost:8080
export ATLAS_INFERENCE_URL=http://localhost:8080
export ATLAS_MODEL_NAME="Qwen3.5-9B-Q6_K"                 # your selected model

# REQUIRED on macOS: the build loads torch (C(x)) then xgboost (G(x)) in one
# process; their two libomp copies otherwise clash and segfault at stage [5/5].
export OMP_NUM_THREADS=1 KMP_DUPLICATE_LIB_OK=TRUE

atlas lens build \
  --from-results docs/reports/ablation/condition_c_phase1_2/v3_lcb/per_task \
  --force
```

What happens (5 stages): probe → load samples → **extract one embedding per
sample from llama-server** → train C(x) (contrastive) → train G(x) (XGBoost on
PCA-reduced embeddings) + calibration.

**Performance knobs** (all optional; sensible defaults baked in):

| Env var | Default | Effect |
|---|---|---|
| `ATLAS_LENS_EMBED_WORKERS` | 4 | concurrent embedding requests — the dominant cost. Match llama-server's slot count. Identical texts are embedded once. |
| `ATLAS_LENS_BATCH_SIZE` | 1024 | C(x) mini-batch (pairs). Bigger = larger GEMMs that use more cores + fewer iterations (≈6× faster than the old 32). |
| `ATLAS_LENS_THREADS` | all cores | torch intra-op threads for C(x) (set explicitly because `OMP_NUM_THREADS=1` above would otherwise pin it to 1). |
| `ATLAS_LENS_DEVICE` | cpu | `mps` trains C(x) on Metal (faster) but has shown intermittent crashes on torch 2.11; CPU is the safe default. |

Embeddings are **cached** to `<samples>.embcache.jsonl` (or `embeddings_cache.jsonl`
next to a results dir), keyed by text hash. A re-run with the same data skips
extraction entirely — a full rebuild then takes ~1–2 min instead of ~10.

It writes a complete, model-stamped bundle to
`geometric-lens/geometric_lens/models/`:

```
cost_field.pt  cost_field.safetensors   # C(x)
gx_xgboost.json  gx_weights.json         # G(x) (XGBoost + PCA projection)
cx_normalization.json  gx_thresholds.json    # per-model calibration
model_identity.json                      # {"model": ..., "embedding_dim": N}
```

### 4.4 Verify

```bash
ATLAS_INFERENCE_URL=http://localhost:8080 atlas lens check
# expect: verdict: ready

# end-to-end: restart the lens service (run-mac.sh does this) and score code
curl -s http://localhost:8099/internal/lens/gx-score \
  -H 'Content-Type: application/json' \
  -d '{"text":"SOLUTION: def add(a,b):\n    return a+b"}' | python3 -m json.tool
# expect: "gx_available": true  and a real "verdict" (not "unavailable")
```

The lens service reads `ATLAS_MODEL_NAME` at startup and refuses to enable G(x)
if it doesn't match `model_identity.json` — so always launch it with the same
`ATLAS_MODEL_NAME` you built with (`run-mac.sh` passes it through automatically).

---

## 4.5 Moving a trained lens between machines

The lens bundle is coupled to the **model**, not the machine — so you can copy a
trained lens from one Mac to another (or anywhere) and skip retraining, **as long
as both run the same model**.

- **Copy** the whole `geometric-lens/geometric_lens/models/` bundle to the same
  path on the other machine:
  `cost_field.pt`, `metric_tensor.pt`, `gx_xgboost.json`, `gx_weights.json`,
  `cx_normalization.json`, `gx_thresholds.json`, `model_identity.json`.

  ```bash
  # on the source machine
  tar czf lens-$ATLAS_MODEL_NAME.tgz -C geometric-lens/geometric_lens/models .
  # on the target machine (same model loaded)
  tar xzf lens-<model>.tgz -C geometric-lens/geometric_lens/models
  ATLAS_INFERENCE_URL=http://localhost:8080 atlas lens check   # verdict: ready
  ```

- **Or publish/fetch** via the model registry: `atlas lens publish` uploads the
  bundle to Hugging Face and opens a registry PR; other machines then fetch it.

- **Why it's portable:** the artifacts are derived from the GGUF model's own
  embeddings (computed by llama.cpp, deterministic for a given model), plus plain
  CPU tensors / JSON. Hardware is irrelevant — M1↔M2↔M3↔M4 all interchange.

- **The only requirement:** the target must load the **same model** with a
  matching `ATLAS_MODEL_NAME`. A different model fails the `model_identity.json`
  check (intentionally — a cross-model lens would score garbage).

---

## 5. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `which python` points at the wrong env after `conda activate atlas` | Another env is auto-activated and sits ahead on `PATH`. Force it: `export PATH="$(conda info --base)/envs/atlas/bin:$PATH"`. `run-mac.sh` already does this. |
| `ModuleNotFoundError: xgboost` in the lens log | Lens deps not fully installed in `atlas`: `pip install -r geometric-lens/requirements.txt`. |
| `atlas lens build` step [5/5] fails: `Could not import the G(x) trainer: No module named 'sklearn'` | The G(x) trainer needs scikit-learn (+xgboost): `pip install scikit-learn xgboost`. C(x) already trained and **embeddings are cached** (`<samples>.embcache.jsonl`), so the retry skips extraction and only re-trains. |
| **Segmentation fault (exit 139)** at build stage [5/5], or the lens service dies at startup right after "No G(x) model found" | macOS duplicate-OpenMP crash: torch and xgboost each load their own `libomp` in one process. Set `OMP_NUM_THREADS=1 KMP_DUPLICATE_LIB_OK=TRUE` before running (the build command and `run-mac.sh` both do this). `torch.set_num_threads()` keeps C(x) multi-core regardless. |
| Lens log: `ATLAS_MODEL_NAME is unset` / self-test 503 | Launch the lens with `ATLAS_MODEL_NAME=...`. `run-mac.sh` passes it; if running by hand, export it. |
| Lens log: `model_identity.json not found` or `artifacts are for 'X', selected model is 'Y'` | No model-matched G(x) bundle. Build one (section 4). |
| `gx_available: false`, `verdict: unavailable` | Same as above — G(x) not built/loaded for this model. C(x) still works. |
| Proxy can't reach the sandbox | The proxy defaults `ATLAS_SANDBOX_URL` to the k3s NodePort `30820`; on macOS the sandbox is `8020`. `run-mac.sh` exports the correct URL. |
| `atlas lens build`: "No usable samples" | Point `--from-results` at the **`per_task/`** subfolder, and confirm failures contain code (see 4.2 gotcha). |
| `atlas lens build`: "Need both pass and fail samples" | Your result set has only one class with code. Use a different run, or merge runs into one `--samples` file. |
| Build pauses for ~1–2 min per sample; llama log shows `input (N tokens) is too large to process` | Embeddings must fit in **one physical batch** (`--ubatch-size`, default 4096). Samples longer than that error and the extractor stalls before skipping them. Either pre-filter long samples (drop code whose token count exceeds the ubatch size — roughly >14k chars), or raise `--ubatch-size`/`--batch-size` in `inference/entrypoint-metal.sh` to cover the longest sample (costs more memory). Pre-filtering is faster and the dropped giant solutions add little signal. |
| Agent loop: every LLM call 400s with `Failed to initialize samplers: std::exception` | The stock Metal llama.cpp build can't compile a JSON **schema** into a sampler (it accepts plain `json_object` + GBNF grammars, not `response_format` schemas). Run the proxy with `ATLAS_GRAMMAR_MODE=gbnf` (run-mac.sh default) — it constrains tool calls with the full GBNF grammar, which compiles here and keeps tool calls schema-strict. `loose` (json_object only) also works but lets the model occasionally emit malformed tool calls. |
| Agent `run_command` fails: `invalid cwd '…' is not in the subpath of '/workspace'` | The sandbox jails commands to `/workspace`, which isn't bind-mounted to your project on native macOS. Run on the host instead: `ATLAS_VERIFY_IN=host` (run-mac.sh default) or per-project `.atlas/config.toml` → `[execution]\ntarget = "host"`. Commands then run in your real working dir (on your machine). |
| Port already in use | `run-mac.sh` kills occupants of 8080/8099/8020/8090 on startup and on exit. |

---

## 5a. The agent loop (`/v1/agent`)

The proxy's agent endpoint runs the full **reason → write → execute → verify →
repair** loop (this is what the TUI drives). On macOS two settings are required,
both defaulted by `run-mac.sh`:

- **`ATLAS_GRAMMAR_MODE=loose`** — the Metal llama.cpp build rejects json-schema
  samplers (see troubleshooting). Loose mode keeps the loop running; the proper
  fix is a llama.cpp that compiles json-schema, or routing the unrestricted turn
  through GBNF (which this build *does* accept).
- **`ATLAS_VERIFY_IN=host`** — lets `run_command` execute in your working dir
  instead of the unusable `/workspace` sandbox jail. Note this runs agent
  commands **on your machine**; set `ATLAS_VERIFY_IN=sandbox` to opt out.

Quick smoke test (proxy must be up):

```bash
curl -sN http://localhost:8090/v1/agent -H 'Content-Type: application/json' \
  -d '{"message":"Create hello.py that prints 1+1 and run it to verify.",
       "working_dir":"/tmp/atlas-play","mode":"yolo","session_id":"smoke"}'
# streams SSE events: tool_call write_file / run_command, lens scores, then [DONE]
```

---

## 6. Stopping & logs

`run-mac.sh` cleans up on Ctrl-C / exit. To stop services started another way:

```bash
for p in 8080 8099 8020 8090; do lsof -ti :$p | xargs kill -9 2>/dev/null; done
```

Per-service logs: `/tmp/atlas-logs/{llama-server,geometric-lens,sandbox,atlas-proxy}.log`.

---

## Quick reference

```bash
# one-time
bash scripts/setup-mac.sh

# run (default model)
bash scripts/run-mac.sh

# build a model-matched lens (llama-server must be up)
conda activate atlas
export ATLAS_MODEL_NAME="<your-model>" LLAMA_URL=http://localhost:8080
atlas lens build --from-results <results>/per_task --force
atlas lens check        # verdict: ready
```
