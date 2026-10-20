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
