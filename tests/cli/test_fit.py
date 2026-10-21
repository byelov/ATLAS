"""Runtime sizing invariants not tied to a particular model family."""

from atlas.commands.fit import GIB, GGUFMeta, fit_runtime_knobs


def _model() -> GGUFMeta:
    return GGUFMeta(
        path="fixture.gguf", file_size=int(7 * GIB), architecture="fixture",
        n_layers=32, n_embd=4096, n_head=16, head_dim=256, v_len=256,
        k_len_swa=256, v_len_swa=256, kv_heads=[4] * 32,
        n_ctx_train=262144, sliding_window=0, local_mask=[False] * 32,
        swa_note="full attention",
    )


def test_fit_keeps_embedding_batch_equal_to_microbatch():
    result = fit_runtime_knobs(_model(), vram_gib=13, slots=1)
    assert result.fits is True
    assert result.ubatch == 1024
    assert result.batch == result.ubatch


def test_unfit_result_still_reports_runnable_batch_geometry():
    result = fit_runtime_knobs(_model(), vram_gib=10, slots=1)
    assert result.fits is False
    assert result.batch == result.ubatch == 512


def test_metal_budget_uses_working_set_limit_not_all_ram():
    from atlas.commands.fit import metal_gpu_budget_gib
    # 128 GB M1 Ultra: macOS default wires ~3/4 to the GPU.
    assert metal_gpu_budget_gib(128.0) == 96.0
    # Small Macs: ~2/3, and never more than RAM minus the host reserve.
    assert round(metal_gpu_budget_gib(32.0), 2) == 21.33
    assert metal_gpu_budget_gib(16.0) == 8.0
    # An explicit iogpu.wired_limit_mb wins, still clamped by the reserve.
    assert metal_gpu_budget_gib(128.0, wired_limit_mb=112640) == 110.0
    assert metal_gpu_budget_gib(128.0, wired_limit_mb=131072) == 120.0


def test_per_slot_cap_allows_longer_slots_when_memory_allows():
    default = fit_runtime_knobs(_model(), vram_gib=96, slots=6)
    assert default.per_slot == 32768
    longer = fit_runtime_knobs(_model(), vram_gib=96, slots=6,
                               per_slot_cap=65536)
    assert longer.fits is True
    assert longer.per_slot == 65536
    assert longer.parallel == 6
    assert longer.kv_type_k == longer.kv_type_v == "f16"


def _write_gguf(path, kv):
    """Minimal GGUF v3 header: no tensors, string / u32 metadata only."""
    import struct

    def s(text):
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw

    out = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv))
    for key, value in kv.items():
        if isinstance(value, str):
            out += s(key) + struct.pack("<I", 8) + s(value)
        else:
            out += s(key) + struct.pack("<II", 4, value)
    path.write_bytes(out)


def test_hybrid_model_bills_kv_only_for_attention_layers(tmp_path):
    # Qwen3.5-9B's geometry: Gated DeltaNet with full attention every 4th
    # layer. llama-server allocates KV for 8 of 32 layers (12288 MiB at
    # 6 × 65536 f16) plus 301.5 MiB of recurrent state for 6 slots; billing
    # KV for all 32 layers over-estimated the cache 4×.
    from atlas.commands.fit import read_gguf_meta
    gguf = tmp_path / "hybrid.gguf"
    _write_gguf(gguf, {
        "general.architecture": "qwen35",
        "qwen35.block_count": 32,
        "qwen35.context_length": 262144,
        "qwen35.embedding_length": 4096,
        "qwen35.attention.head_count": 16,
        "qwen35.attention.head_count_kv": 4,
        "qwen35.attention.key_length": 256,
        "qwen35.attention.value_length": 256,
        "qwen35.ssm.conv_kernel": 4,
        "qwen35.ssm.state_size": 128,
        "qwen35.ssm.group_count": 16,
        "qwen35.ssm.time_step_rank": 32,
        "qwen35.ssm.inner_size": 4096,
        "qwen35.full_attention_interval": 4,
    })
    meta = read_gguf_meta(str(gguf))
    assert meta.recurrent_mask.count(False) == 8
    assert meta.recurrent_mask[3] is False and meta.recurrent_mask[0] is True
    assert meta.recurrent_state_bytes * 6 == int(301.5 * 2 ** 20)

    meta.file_size = int(7 * GIB)
    result = fit_runtime_knobs(meta, vram_gib=96, slots=6,
                               per_slot_cap=65536)
    assert result.per_slot == 65536 and result.kv_type_k == "f16"
    assert result.kv_gib == round((12288 + 301.5) / 1024, 2)


def test_dense_model_has_no_recurrent_state():
    model = _model()
    assert model.recurrent_state_bytes == 0
    result = fit_runtime_knobs(model, vram_gib=96, slots=6,
                               per_slot_cap=65536)
    # 32 attention layers × 4 KV heads × 512 dims × 2 bytes × 393216 tokens
    assert result.kv_gib == 48.0
