"""Tests for atlas.cli.commands.doctor (focused on #32 macOS hybrid).

The existing doctor checks (gpu, compose, container health, etc) don't
have unit tests yet — they're integration-shaped and mostly tested by
real CI runs. These tests cover the new check_metal_native() added in
#32 because:
  1. It's pure-logic + filesystem (no Docker, no slow network)
  2. The failure modes are exactly the ones a Mac user will hit
     (binary missing, not executable, not listening) and we want
     fast feedback when they regress
  3. The Linux + skip path matters too — the check must be a no-op
     for non-Mac users
"""

import sys

from atlas.cli.commands import doctor


def test_check_model_file_requires_explicit_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "MODEL_FILE", "")
    result = doctor.check_model_file(str(tmp_path))
    assert result.status == "fail"
    assert "ATLAS_MODEL_FILE is not configured" in result.message
    assert "atlas init" in result.detail


def test_check_metal_native_skips_on_non_darwin(monkeypatch):
    """On Linux + Windows the metal hybrid path doesn't apply at all.
    The check must return `skip` so it shows up as a no-op in doctor
    output, not as a phantom warn for users who'll never use it."""
    monkeypatch.setattr(sys, "platform", "linux")
    result = doctor._check_metal_native()
    assert result.name == "metal-native"
    assert result.status == "skip"
    assert "macOS" in result.message


def test_check_metal_native_fail_when_binary_missing(monkeypatch, tmp_path):
    """The most common Mac failure mode: setup script was never run,
    so the binary doesn't exist at $HOME/.atlas/macos/bin/. Must point
    the user at the setup script in the detail field."""
    monkeypatch.setattr(sys, "platform", "darwin")
    # Repoint $HOME to an empty tmpdir so the expected binary path
    # definitely doesn't exist. This is more robust than mocking
    # os.path.isfile because the production code also calls os.access.
    monkeypatch.setenv("HOME", str(tmp_path))
    result = doctor._check_metal_native()
    assert result.status == "fail"
    assert "atlas-setup-macos.sh" in result.message
    # The detail should include the expected path so the user knows
    # WHERE the check looked.
    assert "/.atlas/macos/bin/llama-server-metal" in result.detail


def test_check_metal_native_fail_when_binary_not_executable(monkeypatch, tmp_path):
    """Less common but possible: the binary exists but lacks +x (e.g.
    the user copied it from a USB drive with vfat, or rsync'd it
    without --perms). The check should flag this distinctly from
    'binary missing' so the recovery action is clear (re-run setup)."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    # Create the binary path but without +x.
    bin_dir = tmp_path / ".atlas" / "macos" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "llama-server-metal"
    binary.write_text("#!/bin/sh\necho ok\n")
    binary.chmod(0o644)  # no execute bit

    result = doctor._check_metal_native()
    assert result.status == "fail"
    assert "not executable" in result.message
    assert "--rebuild" in result.message


def test_check_metal_native_warn_when_port_not_listening(monkeypatch, tmp_path):
    """Setup ran cleanly but the user hasn't started the native
    llama-server yet. Warn (not fail) — the binary is fine, they just
    need to run the launcher. Distinct from 'binary missing' because
    the recovery is different (run the launcher, not the setup script)."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    bin_dir = tmp_path / ".atlas" / "macos" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "llama-server-metal"
    # Tiny shell script that exits 0 for --help so the executability
    # probe in check_metal_native passes. Real binary would be the
    # llama-server output but for testing we just need exit 0.
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    # Binary --help works; _port_listening returns False (port not up).
    monkeypatch.setattr(doctor, "_run",
                        lambda argv, *args, **kwargs: (0, "", ""))
    monkeypatch.setattr(doctor, "_port_listening",
                        lambda host, port, timeout=2.0: False)

    result = doctor._check_metal_native()
    assert result.status == "warn"
    assert "nothing listening on :8080" in result.message
    assert "atlas-llama-macos.sh" in result.message


def test_check_metal_native_pass_when_everything_healthy(monkeypatch, tmp_path):
    """Happy path: binary exists, is executable, runs --help cleanly,
    and the port is listening. This is the steady-state Mac user
    experience after setup + launcher are both done."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    bin_dir = tmp_path / ".atlas" / "macos" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "llama-server-metal"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    # --help returns 0; _port_listening returns True (port is up).
    monkeypatch.setattr(doctor, "_run",
                        lambda argv, *args, **kwargs: (0, "", ""))
    monkeypatch.setattr(doctor, "_port_listening",
                        lambda host, port, timeout=2.0: True)

    result = doctor._check_metal_native()
    assert result.status == "pass"
    assert "listening on :8080" in result.message


def test_check_metal_native_pass_when_llama_help_exits_nonzero(monkeypatch, tmp_path):
    """Regression for the lead's M3 install: llama-server's --help
    treats the flag as a parse failure and exits 1. The check must NOT
    fail just because exit code is nonzero — it must look at whether
    the binary produced ANY output. A truly corrupt binary (dyld
    failure) produces no output AND exits nonzero; a healthy binary
    that just doesn't return 0 on --help prints its usage."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    bin_dir = tmp_path / ".atlas" / "macos" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "llama-server-metal"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    # --help exits 1 but DID print usage (typical llama-server behavior).
    monkeypatch.setattr(doctor, "_run",
                        lambda argv, *args, **kwargs:
                            (1, "usage: llama-server [opts]\n", ""))
    monkeypatch.setattr(doctor, "_port_listening",
                        lambda host, port, timeout=2.0: True)

    result = doctor._check_metal_native()
    # Must PASS — output proves the loader works, exit code is just a
    # convention quirk.
    assert result.status == "pass"
    assert "listening on :8080" in result.message


def test_resolve_backend_prefers_shell_env(monkeypatch, tmp_path):
    """Shell env wins over .env (matches the rest of doctor's env reads)."""
    monkeypatch.setenv("ATLAS_BACKEND", "cuda")
    (tmp_path / ".env").write_text("ATLAS_BACKEND=vulkan\n")
    assert doctor._resolve_backend(str(tmp_path)) == "cuda"


def test_resolve_backend_falls_back_to_env_file(monkeypatch, tmp_path):
    """When ATLAS_BACKEND isn't in the shell, read from .env. Critical
    for macOS hybrid: atlas init writes ATLAS_BACKEND=metal into .env
    but users rarely source it before running doctor."""
    monkeypatch.delenv("ATLAS_BACKEND", raising=False)
    (tmp_path / ".env").write_text("ATLAS_BACKEND=metal\nOTHER=foo\n")
    assert doctor._resolve_backend(str(tmp_path)) == "metal"


def test_resolve_backend_handles_quotes_and_comments(monkeypatch, tmp_path):
    """Real .env files have shell-style quotes + comment lines.
    The reader must strip both."""
    monkeypatch.delenv("ATLAS_BACKEND", raising=False)
    (tmp_path / ".env").write_text(
        "# generated by atlas init\n"
        "\n"
        'ATLAS_BACKEND="metal"\n'
    )
    assert doctor._resolve_backend(str(tmp_path)) == "metal"


def test_resolve_backend_returns_none_when_neither_set(monkeypatch, tmp_path):
    """No shell env + no .env (or .env with no ATLAS_BACKEND) -> None."""
    monkeypatch.delenv("ATLAS_BACKEND", raising=False)
    # No .env at all
    assert doctor._resolve_backend(str(tmp_path)) is None
    # .env exists but no ATLAS_BACKEND line
    (tmp_path / ".env").write_text("ATLAS_MODEL_NAME=foo\n")
    assert doctor._resolve_backend(str(tmp_path)) is None


def test_check_arch_pass_on_apple_silicon(monkeypatch):
    """Apple Silicon (darwin + aarch64) should PASS, not warn. The arm64
    Linux warning about 'no rocm, use vulkan/sbsa/l4t' doesn't apply to
    Mac users who go through the Metal hybrid path (#32)."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(doctor.tier, "arch_detect", lambda: "aarch64")
    result = doctor.check_arch()
    assert result.status == "pass"
    assert "Apple Silicon" in result.message
    assert "Metal" in result.message


def test_check_arch_warn_on_aarch64_linux(monkeypatch):
    """aarch64 on Linux still warns — the arm64 server matrix
    (sbsa/l4t/vulkan, no rocm) is real there. This is the
    counterpoint to test_check_arch_pass_on_apple_silicon."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(doctor.tier, "arch_detect", lambda: "aarch64")
    result = doctor.check_arch()
    assert result.status == "warn"
    assert "no rocm" in result.message


def test_check_overcommit_skips_on_darwin(monkeypatch):
    """vm.overcommit_memory is a Linux sysctl. macOS doesn't have
    /proc/sys, so this check must SKIP cleanly with an OS-aware
    message instead of the old 'could not read' confusion."""
    monkeypatch.setattr(sys, "platform", "darwin")
    result = doctor.check_overcommit()
    assert result.status == "skip"
    assert "darwin" in result.message
    assert "could not read" not in result.message


def test_check_gpu_apple_silicon_returns_pass(monkeypatch):
    """Apple GPU vendor should PASS the gpu dispatcher check (Metal
    hybrid path is supported via #32). The old 'Metal -> V3.1.2 native
    install' warning was stale and confusing once the path shipped."""
    apple_gpu = doctor.tier.GPUInfo(
        vendor="apple", name="Apple M3 Max", vram_gb=36.0,
        compute_target=None, index=0)
    monkeypatch.setattr(doctor.tier, "detect_gpu", lambda: [apple_gpu])
    monkeypatch.setattr(doctor.tier, "primary_gpu",
                        lambda gpus, **kw: apple_gpu)
    monkeypatch.setattr(doctor.tier, "arch_detect", lambda: "aarch64")
    result = doctor.check_gpu()
    assert result.status == "pass"
    assert "Metal hybrid" in result.message
    assert "not yet supported" not in result.message


def test_check_metal_native_fail_when_binary_crashes(monkeypatch, tmp_path):
    """Edge: corrupt build — binary exists, is executable, but exits
    nonzero on --help (e.g. dynamic linker failure, missing dylib).
    Less common than the 'missing' case but happens after interrupted
    cmake builds. Detail should preserve stderr for debugging."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    bin_dir = tmp_path / ".atlas" / "macos" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "llama-server-metal"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    # --help exits nonzero — simulates a corrupt binary.
    monkeypatch.setattr(doctor, "_run",
                        lambda argv, *args, **kwargs: (127, "", "dyld: Library not loaded"))

    result = doctor._check_metal_native()
    assert result.status == "fail"
    assert "won't run" in result.message
    assert "--rebuild" in result.message
    # The dynamic linker error should land in the detail so the user
    # can paste it into an issue without needing to re-run by hand.
    assert "dyld" in result.detail
