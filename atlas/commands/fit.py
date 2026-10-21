"""atlas tier fit — model-aware llama-server runtime sizing (PC-208).

Derives the memory-bound runtime knobs (context length, KV cache types,
micro-batch) for the *configured model* on *this host's GPU*, instead of the
hardware-tier constants that assume a particular model's geometry.

The solver reads the model's GGUF header (layer count, embedding width,
KV-head geometry, sliding-window metadata) plus the GPU's VRAM, and picks the
largest context + micro-batch whose full budget — weights, KV cache, compute
buffers, reserve — fits on the GPU. The inference entrypoint runs llama-server
with `--fit off`, so a configuration that does not fit refuses to start rather
than spilling layers to the CPU; this solver exists to produce configurations
that fit with margin, for any GGUF (registered or drop-in).

Budget model (conservative — overestimates exotic architectures so the result
errs toward smaller-but-safe):
  weights  = GGUF file size × 1.02 (fully offloaded via -ngl 99)
  kv       = global-attention layers × ctx_total × (k+v) dims × bytes/elem
           + sliding-window layers × (slots × window + ubatch) × (k+v) dims
             × bytes/elem   (llama.cpp pads the SWA cache by one batch)
  compute  = ubatch × n_embd × ~280 B   (calibrated on a 12B/3840-dim model)
  reserve  = 1.9 GiB (CUDA context, graphs, embedding buffers, fragmentation;
             calibrated against measured llama-server footprints)

Apple Silicon: the "VRAM" figure is the Metal working-set limit, not total
unified memory. macOS lets the GPU wire ~2/3 of RAM up to 36 GiB and ~3/4
above (`sysctl iogpu.wired_limit_mb` overrides it), and the host keeps a
reserve for macOS plus the natively-run ATLAS services.

Usage:
    atlas tier fit                       # size the model configured in .env
    atlas tier fit /path/to/model.gguf   # size a specific GGUF
    atlas tier fit --write               # also update .env with the result
    atlas tier fit --slots 6 --per-slot-cap 65536   # more / longer slots
"""

import argparse
import json
import os
import struct
import subprocess
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from atlas.gguf import read_gguf_kv
# Canonical resolver; imported under the module-local name so tests can
# pin the root with monkeypatch.setattr(fit, "_atlas_root", ...).
from atlas.env import atlas_root as _atlas_root

GIB = 1024 ** 3

# Bytes per KV-cache element by llama.cpp cache type.
KV_BYTES = {"f16": 2.0, "q8_0": 1.0625, "q4_0": 0.5625}

# Compute-buffer estimate: bytes per (ubatch token × embedding element),
# calibrated against a measured 4157 MiB buffer at ubatch=4096, n_embd=3840.
COMPUTE_BYTES_PER_TOK_EMBD = 280
COMPUTE_FLOOR_GIB = 0.4

RESERVE_GIB = 1.9          # CUDA context + graphs + embeddings + fragmentation
                           # (measured ~1.86 GiB beyond weights+KV+compute on
                           # the calibration host)
WEIGHTS_OVERHEAD = 1.02    # mmap rounding / tensor alignment
PER_SLOT_MIN = 8192        # below this a slot can't hold prompt + generation
PER_SLOT_CAP = 32768       # diminishing returns past this for ATLAS workloads
CTX_ROUND = 1024           # llama-server context granularity per slot

# Apple Silicon unified memory (see module docstring).
METAL_WIRED_FRACTION_SMALL = 2 / 3   # RAM <= METAL_WIRED_SMALL_MAX_GIB
METAL_WIRED_FRACTION_LARGE = 0.75
METAL_WIRED_SMALL_MAX_GIB = 36
METAL_HOST_RESERVE_GIB = 8.0         # macOS + lens/v3/sandbox/proxy processes

# When a model declares a sliding window but not the local/global layer
# pattern, assume one global layer in every PATTERN_DEFAULT (the common
# arrangement in sliding-window model families).
SWA_PATTERN_DEFAULT = 6


# ---------------------------------------------------------------------------
# GGUF header reading
# ---------------------------------------------------------------------------

@dataclass
class GGUFMeta:
    path: str
    file_size: int
    architecture: str
    n_layers: int
    n_embd: int
    n_head: int
    head_dim: int                     # K head dimension, global layers
    v_len: int                        # V head dimension, global layers
    k_len_swa: int                    # K head dimension, sliding-window layers
    v_len_swa: int                    # V head dimension, sliding-window layers
    kv_heads: List[int]               # per-layer KV head count
    n_ctx_train: int
    sliding_window: int               # 0 = full attention everywhere
    local_mask: List[bool]            # per-layer: True = sliding-window layer
    swa_note: str                     # how the mask was derived
    # Hybrid recurrent models: per-layer True = recurrent layer (no KV cache),
    # plus the fixed f32 state each slot keeps for those layers.
    recurrent_mask: List[bool] = field(default_factory=list)
    recurrent_state_bytes: int = 0    # per slot, all recurrent layers


def read_gguf_meta(path: str) -> GGUFMeta:
    """Read the architecture/geometry keys the fit solver needs."""
    wanted = {}
    with open(path, "rb") as f:
        for key, val in read_gguf_kv(f):
            wanted[key] = val
            # The tokenizer block comes after the architecture keys; once we
            # have the essentials there is no need to walk the rest.
            if key.startswith("tokenizer.") and "block_count" in str(wanted):
                break

    arch = wanted.get("general.architecture", "")

    def a(key, default=None):
        return wanted.get(f"{arch}.{key}", default)

    n_layers = int(a("block_count", 0))
    n_embd = int(a("embedding_length", 0))
    n_head_raw = a("attention.head_count", 0) or 0
    if isinstance(n_head_raw, list):
        n_head = max(int(x) for x in n_head_raw) if n_head_raw else 0
    else:
        n_head = int(n_head_raw)
    head_dim = int(a("attention.key_length", 0) or 0)
    if not head_dim and n_head:
        head_dim = n_embd // n_head
    v_len = int(a("attention.value_length", 0) or 0) or head_dim
    # Sliding-window layers can use narrower K/V heads (e.g. gemma4:
    # key_length 512 on global layers, key_length_swa 256 on locals).
    k_len_swa = int(a("attention.key_length_swa", 0) or 0) or head_dim
    v_len_swa = int(a("attention.value_length_swa", 0) or 0) or v_len

    kv_raw = a("attention.head_count_kv", n_head)
    if isinstance(kv_raw, list):
        kv_heads = [int(x) for x in kv_raw] or [n_head] * n_layers
    else:
        kv_heads = [int(kv_raw)] * n_layers

    if not n_layers or not n_embd or not head_dim or not kv_heads:
        raise ValueError(
            f"GGUF header incomplete (arch={arch!r}, layers={n_layers}, "
            f"embd={n_embd}, head_dim={head_dim})")

    sliding = int(a("attention.sliding_window", 0) or 0)
    pattern = a("attention.sliding_window_pattern", 0)
    if not sliding:
        local_mask = [False] * n_layers
        swa_note = "full attention"
    elif isinstance(pattern, list) and pattern:
        # Per-layer flags straight from the GGUF: truthy = sliding layer.
        local_mask = [bool(x) for x in pattern]
        local_mask += [False] * (n_layers - len(local_mask))
        swa_note = (f"window {sliding}, per-layer mask "
                    f"({sum(local_mask)}/{n_layers} sliding)")
    else:
        p = int(pattern or 0) or SWA_PATTERN_DEFAULT
        local_mask = [(i + 1) % p != 0 for i in range(n_layers)]
        swa_note = (f"window {sliding}, assumed 1 global per {p} layers"
                    + ("" if pattern else " (pattern not in GGUF)"))

    # Hybrid recurrent models (Qwen3.5 / Qwen3-Next: Gated DeltaNet with a
    # full-attention layer every `full_attention_interval` layers). Only the
    # attention layers have a KV cache; each recurrent layer keeps a fixed
    # per-slot state instead — llama.cpp's n_embd_r + n_embd_s floats.
    interval = int(a("full_attention_interval", 0) or 0)
    recurrent_mask = ([(i + 1) % interval != 0 for i in range(n_layers)]
                      if interval > 1 else [False] * n_layers)
    d_conv = int(a("ssm.conv_kernel", 0) or 0)
    d_inner = int(a("ssm.inner_size", 0) or 0)
    d_state = int(a("ssm.state_size", 0) or 0)
    n_group = int(a("ssm.group_count", 0) or 0)
    state_floats = (max(d_conv - 1, 0) * (d_inner + 2 * n_group * d_state)
                    + d_state * d_inner)
    recurrent_state_bytes = sum(recurrent_mask) * state_floats * 4

    return GGUFMeta(
        path=path,
        file_size=os.path.getsize(path),
        architecture=arch,
        n_layers=n_layers,
        n_embd=n_embd,
        n_head=n_head,
        head_dim=head_dim,
        v_len=v_len,
        k_len_swa=k_len_swa,
        v_len_swa=v_len_swa,
        kv_heads=kv_heads,
        n_ctx_train=int(a("context_length", 0) or 0),
        sliding_window=sliding,
        local_mask=local_mask,
        swa_note=swa_note,
        recurrent_mask=recurrent_mask,
        recurrent_state_bytes=recurrent_state_bytes,
    )


# ---------------------------------------------------------------------------
# Fit solver
# ---------------------------------------------------------------------------

@dataclass
class FitResult:
    fits: bool
    ctx_total: int
    per_slot: int
    parallel: int
    kv_type_k: str
    kv_type_v: str
    ubatch: int
    batch: int
    vram_gib: float
    weights_gib: float
    kv_gib: float
    compute_gib: float
    reserve_gib: float
    note: str

    def env_vars(self) -> Dict[str, str]:
        return {
            "ATLAS_CTX_SIZE": str(self.ctx_total),
            "ATLAS_PARALLEL_SLOTS": str(self.parallel),
            "ATLAS_KV_TYPE_K": self.kv_type_k,
            "ATLAS_KV_TYPE_V": self.kv_type_v,
            "ATLAS_UBATCH": str(self.ubatch),
            "ATLAS_BATCH": str(self.batch),
        }


def _layer_dims(meta: GGUFMeta):
    """Per-layer (k+v) element width, split into global-attention layers and
    sliding-window layers via the per-layer mask. The two groups can use
    different head dimensions (key_length vs key_length_swa). Recurrent
    layers of a hybrid model have no KV cache."""
    global_dims = local_dims = 0
    recurrent = meta.recurrent_mask or [False] * len(meta.kv_heads)
    for kvh, is_local, is_recurrent in zip(meta.kv_heads, meta.local_mask,
                                           recurrent):
        if is_recurrent:
            continue
        if is_local:
            local_dims += kvh * (meta.k_len_swa + meta.v_len_swa)
        else:
            global_dims += kvh * (meta.head_dim + meta.v_len)
    return global_dims, local_dims


def metal_gpu_budget_gib(ram_gib: float,
                         wired_limit_mb: Optional[int] = None) -> float:
    """GPU-usable unified memory on Apple Silicon.

    `wired_limit_mb` is `sysctl iogpu.wired_limit_mb` (0/None = macOS
    default). The result never exceeds RAM minus the host reserve."""
    if wired_limit_mb:
        limit = wired_limit_mb / 1024
    elif ram_gib <= METAL_WIRED_SMALL_MAX_GIB:
        limit = ram_gib * METAL_WIRED_FRACTION_SMALL
    else:
        limit = ram_gib * METAL_WIRED_FRACTION_LARGE
    return max(0.0, min(limit, ram_gib - METAL_HOST_RESERVE_GIB))


def _read_wired_limit_mb() -> Optional[int]:
    try:
        p = subprocess.run(["sysctl", "-n", "iogpu.wired_limit_mb"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return int(p.stdout.strip())
    except ValueError:
        return None


def fit_runtime_knobs(meta: GGUFMeta, vram_gib: float,
                      slots: int = 4,
                      per_slot_cap: int = PER_SLOT_CAP) -> FitResult:
    """Largest context + micro-batch whose full budget fits in `vram_gib`."""
    weights = meta.file_size * WEIGHTS_OVERHEAD / GIB
    global_dims, local_dims = _layer_dims(meta)
    state_cost = slots * meta.recurrent_state_bytes / GIB

    best = None
    for ubatch in (2048, 1024, 512):
        compute = max(COMPUTE_FLOOR_GIB,
                      ubatch * meta.n_embd * COMPUTE_BYTES_PER_TOK_EMBD / GIB)
        for kv_type in ("f16", "q8_0"):
            bpe = KV_BYTES[kv_type]
            budget = vram_gib - weights - compute - RESERVE_GIB - state_cost
            # llama.cpp sizes the sliding-window cache at one batch beyond
            # slots × window, so bill the same.
            local_tokens = slots * meta.sliding_window + ubatch
            local_cost = (local_tokens * local_dims * bpe / GIB
                          if local_dims else 0.0)
            budget -= local_cost
            if budget <= 0:
                # Weights + compute + sliding-window KV alone overflow VRAM
                # at this rung — no context budget left to allocate.
                continue
            if global_dims <= 0:
                # Pure sliding-window model: KV doesn't grow with context,
                # so context is bounded only by the per-slot cap.
                ctx_total = per_slot_cap * slots
            else:
                ctx_total = int(budget * GIB / (global_dims * bpe))
            per_slot = ctx_total // slots
            if meta.n_ctx_train:
                per_slot = min(per_slot, meta.n_ctx_train)
            per_slot = min(per_slot, per_slot_cap)
            per_slot = (per_slot // CTX_ROUND) * CTX_ROUND
            if per_slot < PER_SLOT_MIN:
                continue
            ctx_total = per_slot * slots
            kv_gib = (ctx_total * global_dims * bpe / GIB + local_cost
                      + state_cost)
            note = meta.swa_note if "assumed" in meta.swa_note else ""
            result = FitResult(
                fits=True, ctx_total=ctx_total, per_slot=per_slot,
                parallel=slots, kv_type_k=kv_type, kv_type_v=kv_type,
                # llama.cpp self-embeddings require n_batch <= n_ubatch.
                # ATLAS always enables embeddings, so advertise the value the
                # runtime can actually use instead of relying on its clamp.
                ubatch=ubatch, batch=ubatch,
                vram_gib=round(vram_gib, 2), weights_gib=round(weights, 2),
                kv_gib=round(kv_gib, 2), compute_gib=round(compute, 2),
                reserve_gib=RESERVE_GIB, note=note)
            if best is None or (result.per_slot, -result.ubatch) > (
                    best.per_slot, -best.ubatch):
                best = result
        if best is not None and best.ubatch == ubatch:
            # A larger ubatch (faster prompt processing) already yields an
            # acceptable context; smaller ubatch can only trade speed for
            # context we cap anyway.
            if best.per_slot >= per_slot_cap:
                break

    if best is not None:
        return best

    # Nothing acceptable — report the most frugal configuration's accounting
    # (ubatch 512, q8_0 KV, minimum context) so the operator sees exactly
    # what doesn't fit, plus the largest quant of THIS geometry that would.
    compute = max(COMPUTE_FLOOR_GIB,
                  512 * meta.n_embd * COMPUTE_BYTES_PER_TOK_EMBD / GIB)
    bpe = KV_BYTES["q8_0"]

    def _min_kv(n_slots):
        return (PER_SLOT_MIN * n_slots * global_dims * bpe / GIB +
                ((n_slots * meta.sliding_window + 512) * local_dims * bpe / GIB
                 if local_dims else 0.0)
                + n_slots * meta.recurrent_state_bytes / GIB)

    def _max_file(n_slots):
        return (vram_gib - RESERVE_GIB - compute
                - _min_kv(n_slots)) / WEIGHTS_OVERHEAD

    min_kv = _min_kv(slots)
    fits_here, fits_one = _max_file(slots), _max_file(1)
    if fits_here > 0:
        guidance = (f"At {slots} slots, a quant of this model up to "
                    f"~{fits_here:.1f} GiB (file size) would fit; with "
                    f"--slots 1, up to ~{fits_one:.1f} GiB.")
    elif fits_one > 0:
        guidance = (f"Even the minimum context does not fit at {slots} "
                    f"slots; with --slots 1, a quant up to "
                    f"~{fits_one:.1f} GiB (file size) would fit.")
    else:
        guidance = ("This GPU cannot run this model's geometry at any "
                    "quant — even the minimum KV cache and compute "
                    "buffers exceed VRAM.")
    return FitResult(
        fits=False, ctx_total=0, per_slot=0, parallel=slots,
        kv_type_k="q8_0", kv_type_v="q8_0", ubatch=512, batch=512,
        vram_gib=round(vram_gib, 2),
        weights_gib=round(meta.file_size * WEIGHTS_OVERHEAD / GIB, 2),
        kv_gib=round(min_kv, 2), compute_gib=round(compute, 2),
        reserve_gib=RESERVE_GIB,
        note=(f"model does not fit: weights + minimum KV "
              f"({PER_SLOT_MIN}/slot × {slots}) + compute exceed VRAM. "
              f"{guidance}"))


# ---------------------------------------------------------------------------
# CLI surface (invoked by `atlas tier fit`)
# ---------------------------------------------------------------------------

def _default_model_path() -> Optional[str]:
    from atlas import env as cli_env
    root = _atlas_root()
    base = (cli_env.MODEL_DIR if os.path.isabs(cli_env.MODEL_DIR)
            else os.path.join(root, cli_env.MODEL_DIR))
    path = os.path.normpath(os.path.join(base, cli_env.MODEL_FILE))
    return path if os.path.isfile(path) else None


def _write_env(values: Dict[str, str]) -> str:
    """Set/replace the given keys in the repo's .env, preserving everything
    else. Returns the .env path."""
    path = os.path.join(_atlas_root(), ".env")
    lines: List[str] = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        prefix = ""
        if stripped.startswith("export "):
            prefix = "export "
            stripped = stripped[len(prefix):].lstrip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else None
        if key in values and not stripped.startswith("#"):
            # Rewrite every occurrence — .env consumers resolve duplicate
            # keys last-wins, so a stale trailing duplicate must not survive.
            out.append(f"{prefix}{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    missing = {k: v for k, v in values.items() if k not in seen}
    if missing:
        out.append("")
        out.append("# Runtime sizing for the configured model (atlas tier fit)")
        for k, v in missing.items():
            out.append(f"{k}={v}")
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    return path


def _cwd_deployment_root() -> Optional[str]:
    """The nearest directory at-or-above cwd holding a docker-compose.yml —
    a deployment the operator may believe `--write` targets. Distinct from
    `_atlas_root()` on purpose: comparing the two is what lets `--write`
    warn that it is about to edit a different checkout's .env."""
    cur = os.getcwd()
    for _ in range(8):
        if os.path.exists(os.path.join(cur, "docker-compose.yml")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def emit_fit(args: argparse.Namespace, color: bool) -> int:
    from atlas.commands.tier import detect_gpu, primary_gpu, _safe_print

    explicit = getattr(args, "model", None)
    if explicit and not os.path.isfile(explicit):
        _safe_print(f"  Model file not found: {explicit}")
        return 1
    model = explicit or _default_model_path()
    if not model:
        _safe_print("  No model configured. Pass a GGUF path or set "
                    "ATLAS_MODEL_FILE in .env.")
        return 1

    try:
        meta = read_gguf_meta(model)
    except (OSError, ValueError, struct.error, KeyError) as e:
        _safe_print(f"  Could not read GGUF header: {e}")
        return 1

    gpus = detect_gpu()
    gpu = primary_gpu(gpus) if gpus else None
    if gpu is None or not getattr(gpu, "vram_gb", 0):
        _safe_print("  No GPU with reported VRAM detected — fit requires one.")
        return 1
    vram_gib = float(gpu.vram_gb)
    gpu_label = f"{gpu.name} ({vram_gib:.1f} GiB)"
    if getattr(gpu, "vendor", "") == "apple":
        ram_gib = vram_gib
        vram_gib = metal_gpu_budget_gib(ram_gib, _read_wired_limit_mb())
        gpu_label = (f"{gpu.name} ({vram_gib:.1f} GiB Metal budget of "
                     f"{ram_gib:.1f} GiB unified)")

    slots = getattr(args, "slots", None)
    slots = 4 if slots is None else int(slots)
    if slots < 1:
        _safe_print("  --slots must be at least 1.")
        return 2
    per_slot_cap = getattr(args, "per_slot_cap", None)
    per_slot_cap = PER_SLOT_CAP if per_slot_cap is None else int(per_slot_cap)
    if per_slot_cap < PER_SLOT_MIN:
        _safe_print(f"  --per-slot-cap must be at least {PER_SLOT_MIN}.")
        return 2
    result = fit_runtime_knobs(meta, vram_gib, slots=slots,
                               per_slot_cap=per_slot_cap)

    if getattr(args, "json", False):
        payload = {"model": model, "meta": asdict(meta),
                   "fit": asdict(result),
                   "env": result.env_vars() if result.fits else {}}
        if getattr(args, "write", False) and result.fits:
            payload["wrote"] = _write_env(result.env_vars())
        print(json.dumps(payload, indent=2))
        return 0 if result.fits else 1

    _safe_print(f"atlas tier fit — {os.path.basename(model)}")
    _safe_print(f"  arch {meta.architecture} | {meta.n_layers} layers | "
                f"{meta.n_embd}-dim | head_dim {meta.head_dim} | {meta.swa_note}")
    _safe_print(f"  GPU: {gpu_label}")
    _safe_print(f"  budget: weights {result.weights_gib} + KV {result.kv_gib} "
                f"+ compute {result.compute_gib} + reserve {result.reserve_gib} "
                f"GiB of {result.vram_gib} GiB")
    if not result.fits:
        _safe_print(f"  DOES NOT FIT: {result.note}")
        return 1
    _safe_print(f"  fit: ctx {result.ctx_total} ({result.per_slot}/slot × "
                f"{result.parallel}), KV {result.kv_type_k}, "
                f"ubatch {result.ubatch}")
    if result.note:
        _safe_print(f"  note: {result.note}")
    for k, v in result.env_vars().items():
        _safe_print(f"    {k}={v}")
    if getattr(args, "write", False):
        path = _write_env(result.env_vars())
        _safe_print(f"  wrote {path}")
        cwd_root = _cwd_deployment_root()
        if cwd_root and (os.path.realpath(cwd_root)
                         != os.path.realpath(os.path.dirname(path))):
            _safe_print(f"  note: that is the ATLAS install's .env — NOT "
                        f"{cwd_root}/.env. docker compose reads the .env "
                        f"next to the docker-compose.yml it runs from.")
        from atlas import compose as compose_config
        if compose_config.resolve_deploy(_atlas_root()) == "native":
            _safe_print("  apply: atlas native restart llama-server")
        else:
            _safe_print("  apply: docker compose up -d llama-server "
                        "--no-deps --force-recreate")
    else:
        _safe_print("  (re-run with --write to update .env)")
    return 0
