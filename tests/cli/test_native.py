"""The fully native macOS deployment (atlas native): LaunchAgent plists, the
sandbox Seatbelt profile, the per-service wrapper, and the CLI paths that
branch on ATLAS_DEPLOY=native."""

import argparse
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys

import pytest

from atlas import compose as compose_config
from atlas.commands import native

ROOT = pathlib.Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "native" / "atlas-service.sh"

macos_only = pytest.mark.skipif(
    sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"),
    reason="needs macOS sandbox-exec")


# ---------------------------------------------------------------------------
# Deploy-mode resolution
# ---------------------------------------------------------------------------

def test_resolve_deploy_defaults_to_docker(tmp_path):
    assert compose_config.resolve_deploy(str(tmp_path), environ={}) == "docker"


def test_resolve_deploy_reads_env_file_and_shell_wins(tmp_path):
    (tmp_path / ".env").write_text("ATLAS_DEPLOY=native\n")
    assert compose_config.resolve_deploy(str(tmp_path), environ={}) == "native"
    assert compose_config.resolve_deploy(
        str(tmp_path), environ={"ATLAS_DEPLOY": "docker"}) == "docker"


# ---------------------------------------------------------------------------
# LaunchAgent plists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("service", native.SERVICES)
def test_plist_runs_the_wrapper_for_each_service(service, monkeypatch):
    monkeypatch.delenv("ATLAS_LAUNCHD_PREFIX", raising=False)
    monkeypatch.setattr(native, "_atlas_root", lambda: "/opt/atlas")
    plist = native.build_plist(service, "/opt/atlas", "/Users/me")
    assert plist["Label"] == f"ai.atlas.{service}"
    # The wrapper is the program itself, so Login Items names the agent
    # "atlas-service.sh" rather than "bash".
    assert plist["ProgramArguments"] == [
        "/opt/atlas/scripts/native/atlas-service.sh", service]
    assert plist["EnvironmentVariables"]["ATLAS_ROOT"] == "/opt/atlas"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["StandardOutPath"] == (
        f"/Users/me/Library/Logs/atlas/{service}.log")
    # Round-trips as a valid plist.
    assert plistlib.loads(plistlib.dumps(plist)) == plist


def test_request_path_is_interactive_and_sandbox_is_deprioritized(monkeypatch):
    monkeypatch.setattr(native, "_atlas_root", lambda: "/opt/atlas")
    for service in ("llama-server", "geometric-lens", "v3-service",
                    "atlas-proxy"):
        plist = native.build_plist(service, "/opt/atlas", "/Users/me")
        assert plist["ProcessType"] == "Interactive", service
        assert "Nice" not in plist
    sandbox = native.build_plist("sandbox", "/opt/atlas", "/Users/me")
    assert sandbox["ProcessType"] == "Standard"
    assert sandbox["Nice"] > 0


def test_label_prefix_is_configurable(monkeypatch):
    monkeypatch.setenv("ATLAS_LAUNCHD_PREFIX", "com.example.atlas")
    assert native.label("atlas-proxy") == "com.example.atlas.atlas-proxy"


@macos_only
def test_rendered_plist_passes_plutil(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "_atlas_root", lambda: str(ROOT))
    path = tmp_path / "agent.plist"
    path.write_bytes(native.render_plist("atlas-proxy", str(ROOT), "/Users/me"))
    result = subprocess.run(["plutil", "-lint", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def _fake_launchd(monkeypatch, tmp_path, loaded=False):
    """Point install/status at a temp checkout + home with launchctl faked."""
    root = tmp_path / "atlas"
    (root / "scripts" / "native").mkdir(parents=True)
    wrapper = root / "scripts" / "native" / "atlas-service.sh"
    wrapper.write_text("#!/usr/bin/env bash\n")
    home = tmp_path / "home"
    monkeypatch.delenv("ATLAS_LAUNCHD_PREFIX", raising=False)
    monkeypatch.setattr(native, "_atlas_root", lambda: str(root))
    monkeypatch.setattr(native, "_home", lambda: str(home))
    calls = []
    monkeypatch.setattr(native, "_launchctl", lambda *a: calls.append(a) or
                        subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(native, "_print_info",
                        lambda s: {"pid": "1"} if loaded else {})
    monkeypatch.setattr(native, "_health", lambda s, timeout=3.0: loaded)
    return wrapper, calls


def test_install_restores_wrapper_exec_bit_and_explains_login_items(
        tmp_path, monkeypatch, capsys):
    wrapper, calls = _fake_launchd(monkeypatch, tmp_path)
    wrapper.chmod(0o644)  # e.g. a checkout from an archive
    assert native._cmd_install(argparse.Namespace(services=[])) == 0
    assert os.access(wrapper, os.X_OK)
    plist = plistlib.loads(pathlib.Path(native.plist_path("sandbox")).read_bytes())
    assert plist["ProgramArguments"] == [str(wrapper), "sandbox"]
    assert [c[0] for c in calls if c[0] == "bootstrap"] == ["bootstrap"] * len(
        native.SERVICES)
    assert "atlas-service.sh" in capsys.readouterr().out


def test_status_explains_installed_but_unloaded_agents(tmp_path, monkeypatch,
                                                       capsys):
    _fake_launchd(monkeypatch, tmp_path, loaded=False)
    assert native._cmd_install(argparse.Namespace(services=[])) == 0
    capsys.readouterr()
    assert native._cmd_status(argparse.Namespace(json=False)) == 1
    out = capsys.readouterr().out
    assert "atlas native start" in out
    assert "Login Items" in out


def test_unknown_service_rejected():
    with pytest.raises(ValueError):
        native.build_plist("redis", "/opt/atlas", "/Users/me")


# ---------------------------------------------------------------------------
# Seatbelt profile (text)
# ---------------------------------------------------------------------------

def _cfg(tmp_path, **overrides):
    home = tmp_path / "home"
    root = tmp_path / "atlas"
    for d in (home, root / "secrets", root / "sandbox", tmp_path / "project",
              tmp_path / "sbx" / "home", tmp_path / "sbx" / "tmp",
              tmp_path / "prefix" / "venvs" / "sandbox"):
        d.mkdir(parents=True, exist_ok=True)
    (root / "secrets" / "service-token").write_text("atlas-st-test\n")
    (root / "secrets" / "api-keys.json").write_text("{}\n")
    values = dict(
        project=str(tmp_path / "project"),
        sandbox_home=str(tmp_path / "sbx" / "home"),
        sandbox_tmp=str(tmp_path / "sbx" / "tmp"),
        venv=str(tmp_path / "prefix" / "venvs" / "sandbox"),
        secrets=str(root / "secrets"),
        token_file=str(root / "secrets" / "service-token"),
        atlas_root=str(root), prefix=str(tmp_path / "prefix"),
        real_home=str(home), deny_ports=[8080, 8090])
    values.update(overrides)
    return native.SeatbeltConfig(**values)


def test_profile_rule_order_narrows_each_section(tmp_path):
    text = native.render_seatbelt_profile(_cfg(tmp_path))
    real = os.path.realpath
    # Later rules win, so each re-allow must follow the deny it narrows.
    assert text.index("(deny file-read-data") < text.index(
        "(allow file-read-data")
    assert text.index("(allow file-read-data") < text.index(
        f"(deny {native._SECRET_READ_OPS} (subpath " + native.sbpl_string(
            real(str(tmp_path / "atlas" / "secrets"))))
    assert text.index("(deny file-write*)") < text.index("(allow file-write*")
    assert text.index("(allow file-write*") < text.index(
        native.sbpl_string(real(str(tmp_path / "project" / ".git" / "hooks"))))
    assert "(allow signal (target same-sandbox))" in text
    assert '(literal "/bin/launchctl")' in text
    assert '(remote ip "localhost:8080")' in text
    assert '(remote ip "localhost:8090")' in text
    # Default: egress stays open, like the container.
    assert '(remote ip "*:*")' not in text


def test_profile_net_internal_cuts_all_egress(tmp_path):
    text = native.render_seatbelt_profile(_cfg(tmp_path, net_internal=True))
    assert '(deny network-outbound (remote ip "*:*"))' in text


def test_profile_paths_are_resolved_and_quoted(tmp_path):
    odd = tmp_path / 'pro"ject'
    odd.mkdir()
    text = native.render_seatbelt_profile(_cfg(tmp_path, project=str(odd)))
    assert native.sbpl_string(os.path.realpath(str(odd))) in text
    assert '\\"' in native.sbpl_string('a"b')
    with pytest.raises(ValueError):
        native.sbpl_string("bad\npath")


# ---------------------------------------------------------------------------
# Seatbelt profile (enforced by sandbox-exec)
# ---------------------------------------------------------------------------

@macos_only
def test_profile_enforces_the_sandbox_boundary(tmp_path):
    cfg = _cfg(tmp_path)
    profile = tmp_path / "p.sb"
    profile.write_text(native.render_seatbelt_profile(cfg))
    project = os.path.realpath(cfg.project)
    home = os.path.realpath(cfg.real_home)
    pathlib.Path(home, "secret.txt").write_text("hunter2\n")

    def run(cmd):
        return subprocess.run(
            ["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=20).returncode

    assert run(f"echo ok > '{project}/out.txt'") == 0
    assert run(f"touch '{home}/escape'") != 0
    assert not os.path.exists(os.path.join(home, "escape"))
    assert run(f"cat '{home}/secret.txt' >/dev/null") != 0
    assert run(f"cat '{cfg.token_file}' >/dev/null") == 0
    assert run(f"cat '{cfg.secrets}/api-keys.json' >/dev/null") != 0
    assert run(f"mkdir -p '{project}/.git/hooks' && "
               f"echo x > '{project}/.git/hooks/pre-commit'") != 0
    assert run("/bin/launchctl list >/dev/null") != 0


@macos_only
@pytest.mark.parametrize("project_is_checkout", [False, True])
def test_profile_secrets_hold_when_the_checkout_is_under_home(
        tmp_path, project_is_checkout):
    """The usual layout: the checkout (and its secrets/) inside the home
    directory. Seatbelt lets a file-read-data rule beat a file-read* rule
    regardless of order, so the token re-allow must name file-read-data to
    beat the home deny (else the executor starts without auth), and the
    secrets deny must too, to beat the project allow when the project is
    the checkout."""
    cfg = _cfg(tmp_path, real_home=str(tmp_path))
    if project_is_checkout:
        cfg = _cfg(tmp_path, real_home=str(tmp_path), project=cfg.atlas_root)
    profile = tmp_path / "p.sb"
    profile.write_text(native.render_seatbelt_profile(cfg))

    def cat(path):
        return subprocess.run(
            ["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/cat", path],
            capture_output=True, text=True, timeout=20).returncode

    assert cat(cfg.token_file) == 0
    assert cat(os.path.join(cfg.secrets, "api-keys.json")) != 0


# ---------------------------------------------------------------------------
# Wrapper (scripts/native/atlas-service.sh) — dry run
# ---------------------------------------------------------------------------

def _wrapper_env(tmp_path):
    prefix = tmp_path / "prefix"
    native_home = tmp_path / "native"
    for venv in ("lens", "v3", "sandbox"):
        bindir = prefix / "venvs" / venv / "bin"
        bindir.mkdir(parents=True)
        (bindir / "python").symlink_to(sys.executable)
    tools = native_home / "sandbox" / "home" / ".venv" / "bin"
    tools.mkdir(parents=True)
    (tools / "python").symlink_to(sys.executable)
    (prefix / "bin").mkdir()
    proxy = prefix / "bin" / "atlas-proxy"
    proxy.write_text("#!/bin/sh\n")
    proxy.chmod(0o755)
    project = tmp_path / "project"
    project.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "ATLAS_ROOT": str(ROOT),
        "ATLAS_MACOS_PREFIX": str(prefix),
        "ATLAS_NATIVE_HOME": str(native_home),
        "ATLAS_PROJECT_DIR": str(project),
        "ATLAS_SECRETS_DIR": str(tmp_path / "secrets"),
        "ATLAS_MODEL_NAME": "fixture-model",
        "ATLAS_NATIVE_DRY_RUN": "1",
    }
    return env, project


def _dry_run(service, env):
    result = subprocess.run(["/bin/bash", str(WRAPPER), service], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    out = {"env": {}}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == "env":
            k, _, v = value.partition("=")
            out["env"][k] = v
        else:
            out[key] = value
    return out


def test_wrapper_proxy_binds_loopback_and_uses_request_dirs(tmp_path):
    env, _ = _wrapper_env(tmp_path)
    out = _dry_run("atlas-proxy", env)
    assert out["env"]["ATLAS_PROXY_HOST"] == "127.0.0.1"
    assert out["env"]["ATLAS_SANDBOX_URL"] == "http://127.0.0.1:30820"
    assert out["env"]["ATLAS_V3_URL"] == "http://127.0.0.1:8070"
    # No /workspace to translate to: the proxy serves each request's dir.
    assert "ATLAS_WORKSPACE_DIR" not in out["env"]
    assert out["deps"].split() == [
        "http://127.0.0.1:8080", "http://127.0.0.1:8099",
        "http://127.0.0.1:8070", "http://127.0.0.1:30820"]


def test_wrapper_sandbox_runs_under_seatbelt_on_the_host_port(tmp_path):
    env, project = _wrapper_env(tmp_path)
    out = _dry_run("sandbox", env)
    assert out["cmd"].startswith("/usr/bin/sandbox-exec -f ")
    assert out["env"]["ATLAS_SANDBOX_HOST"] == "127.0.0.1"
    assert out["env"]["ATLAS_SANDBOX_PORT"] == "30820"
    assert out["env"]["ATLAS_SANDBOX_WORKSPACE_ROOT"] == os.path.realpath(
        str(project))
    # The private HOME, not the real one, and the tools venv first on PATH.
    assert out["env"]["HOME"].startswith(env["ATLAS_NATIVE_HOME"])
    assert out["env"]["PATH"].split(":")[0].endswith("/home/.venv/bin")
    profile = pathlib.Path(env["ATLAS_NATIVE_HOME"], "sandbox",
                           "atlas-sandbox.sb")
    assert profile.read_text().startswith("(version 1)")


def test_wrapper_services_bind_loopback(tmp_path):
    env, _ = _wrapper_env(tmp_path)
    assert _dry_run("v3-service", env)["env"]["ATLAS_V3_HOST"] == "127.0.0.1"
    lens = _dry_run("geometric-lens", env)
    assert "--host 127.0.0.1 --port 8099" in lens["cmd"]
    assert lens["env"]["LLAMA_URL"] == "http://127.0.0.1:8080"
    # torch + xgboost (calibrated G(x)) share the process on macOS.
    assert lens["env"]["KMP_DUPLICATE_LIB_OK"] == "TRUE"
    assert lens["env"]["OMP_NUM_THREADS"] == "1"
    # No bind mount natively: compose's default lens dir, passed by env.
    assert lens["env"]["ATLAS_LENS_MODELS_DIR"] == str(
        ROOT / "geometric-lens" / "geometric_lens" / "models")
    llama = _dry_run("llama-server", env)
    assert llama["env"]["ATLAS_LLAMA_HOST"] == "127.0.0.1"
    assert llama["cmd"].endswith("scripts/atlas-llama-macos.sh")


def test_wrapper_passes_a_per_model_lens_dir(tmp_path):
    env, _ = _wrapper_env(tmp_path)
    env["ATLAS_LENS_MODELS"] = "./models/lens/fixture-model"
    lens = _dry_run("geometric-lens", env)
    assert lens["env"]["ATLAS_LENS_MODELS_DIR"] == str(
        ROOT / "models" / "lens" / "fixture-model")


def test_wrapper_honors_port_overrides(tmp_path):
    env, _ = _wrapper_env(tmp_path)
    env["ATLAS_SANDBOX_PORT"] = "31111"
    env["ATLAS_PROXY_PORT"] = "9999"
    out = _dry_run("atlas-proxy", env)
    assert out["env"]["ATLAS_PROXY_PORT"] == "9999"
    assert out["env"]["ATLAS_SANDBOX_URL"] == "http://127.0.0.1:31111"


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_wrapper_rejects_unknown_service():
    result = subprocess.run(["/bin/bash", str(WRAPPER), "redis"],
                            capture_output=True, text=True)
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_render_profile_command_writes_profile(tmp_path):
    cfg = _cfg(tmp_path)
    out = tmp_path / "out.sb"
    rc = native.main([
        "render-profile", "--out", str(out), "--project", cfg.project,
        "--sandbox-home", cfg.sandbox_home, "--sandbox-tmp", cfg.sandbox_tmp,
        "--venv", cfg.venv, "--secrets", cfg.secrets,
        "--token-file", cfg.token_file, "--atlas-root", cfg.atlas_root,
        "--prefix", cfg.prefix, "--deny-port", "8090",
        "--net-internal", "true"])
    assert rc == 0
    text = out.read_text()
    assert '(remote ip "*:*")' in text


def test_native_commands_refuse_off_macos(monkeypatch, capsys):
    monkeypatch.setattr(native.sys, "platform", "linux")
    assert native.main(["status"]) == 1
    assert "macOS-only" in capsys.readouterr().err


def test_runtime_aligns_native_sandbox_to_cwd(tmp_path, monkeypatch):
    from atlas import runtime
    root = tmp_path / "atlas"
    root.mkdir()
    (root / ".env").write_text(
        f"ATLAS_DEPLOY=native\nATLAS_PROJECT_DIR={tmp_path / 'old'}\n")
    project = tmp_path / "new"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.delenv("ATLAS_PROJECT_DIR", raising=False)
    monkeypatch.delenv("ATLAS_DEPLOY", raising=False)
    monkeypatch.delenv("ATLAS_AUTO_WORKSPACE", raising=False)
    calls = []
    monkeypatch.setattr(native, "set_project",
                        lambda d, wait=30.0: calls.append(d) or 0)
    runtime._align_workspace(str(root))
    assert calls == [os.path.realpath(str(project))]

    # Already aligned: no restart.
    (root / ".env").write_text(
        f"ATLAS_DEPLOY=native\nATLAS_PROJECT_DIR={project}\n")
    calls.clear()
    runtime._align_workspace(str(root))
    assert calls == []


def test_runtime_starts_launchd_proxy_instead_of_a_local_one(monkeypatch):
    from atlas import runtime
    monkeypatch.setattr(runtime, "_find_atlas_dir", lambda: "/opt/atlas")
    monkeypatch.setattr(runtime, "_check_url", lambda url, timeout=3: False)
    monkeypatch.setattr(runtime, "_native_deploy", lambda d: True)
    started = []
    monkeypatch.setattr(native, "main", lambda argv: started.append(argv) or 0)
    monkeypatch.setattr(runtime, "_wait_for_proxy", lambda timeout=60: True)
    monkeypatch.setattr(runtime, "_align_workspace", lambda d: None)
    monkeypatch.setattr(runtime, "_launch_local_proxy",
                        lambda b: pytest.fail("launched a competing proxy"))
    assert runtime.ensure_proxy() is True
    assert started == [["start"]]


def test_doctor_native_flow_skips_docker(monkeypatch, tmp_path):
    from atlas.commands import doctor
    (tmp_path / ".env").write_text("ATLAS_DEPLOY=native\n")
    monkeypatch.setattr(doctor, "_find_atlas_root", lambda: str(tmp_path))
    monkeypatch.delenv("ATLAS_DEPLOY", raising=False)
    monkeypatch.setattr(doctor, "check_docker",
                        lambda: pytest.fail("docker probed on a native install"))
    ok = doctor.CheckResult("x", "pass", "ok")
    for name in ("check_arch", "_check_metal_native", "check_model_file",
                 "check_lens_weights", "check_asa_steering",
                 "check_sqlite_state", "check_tier_match",
                 "check_tier_constraints"):
        monkeypatch.setattr(doctor, name, lambda *a, **k: ok)
    for name in ("check_health_endpoints", "check_internal_auth",
                 "check_status_dimensions"):
        monkeypatch.setattr(doctor, name, lambda *a, **k: [ok])
    monkeypatch.setattr(doctor, "check_native_runtime",
                        lambda root: [doctor.CheckResult(
                            "native/runtime", "pass", "ok")])
    monkeypatch.setattr(doctor, "check_native_services",
                        lambda: [doctor.CheckResult(
                            "native/atlas-proxy", "pass", "ok")])
    assert doctor.main(["--quick", "--json"]) == 0


@macos_only
def test_doctor_seatbelt_check_accepts_generated_profile(tmp_path, monkeypatch):
    from atlas.commands import doctor
    root = tmp_path / "atlas"
    (root / "secrets").mkdir(parents=True)
    monkeypatch.setenv("ATLAS_NATIVE_HOME", str(tmp_path / "native"))
    monkeypatch.setenv("ATLAS_MACOS_PREFIX", str(tmp_path / "prefix"))
    monkeypatch.setattr(native, "_atlas_root", lambda: str(root))
    results = {r.name: r for r in doctor.check_native_runtime(str(root))}
    assert results["native/runtime"].status == "fail"   # nothing installed
    assert results["native/seatbelt"].status == "pass", results[
        "native/seatbelt"].detail


def test_wrapper_is_bash32_safe():
    """launchd runs the wrapper with macOS's /bin/bash 3.2: arrays that may
    be empty must not be expanded bare under `set -u`."""
    text = WRAPPER.read_text()
    for name in ("token_env", "extra_env"):
        assert f'"${{{name}[@]}}"' not in text.replace(
            f'${{{name}[@]+"${{{name}[@]}}"}}', "")


@pytest.mark.skipif(shutil.which("shellcheck") is None,
                    reason="shellcheck not installed")
def test_wrapper_shellcheck():
    result = subprocess.run(["shellcheck", "--severity=error", str(WRAPPER)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_profile_hides_shared_per_user_temp_except_toolchain_caches(tmp_path):
    temp = tmp_path / "folders" / "xy" / "T"
    cache = tmp_path / "folders" / "xy" / "C"
    temp.mkdir(parents=True)
    cache.mkdir()
    text = native.render_seatbelt_profile(
        _cfg(tmp_path, darwin_temp=str(temp), darwin_cache=str(cache)))
    base = os.path.realpath(str(tmp_path / "folders" / "xy"))
    deny_line = next(l for l in text.splitlines()
                     if l.startswith("(deny file-read-data"))
    assert native.sbpl_string(base) in deny_line
    assert "/xcrun_db\")" in text
    assert native.sbpl_string(os.path.join(os.path.realpath(str(cache)),
                                           "clang")) in text
    # The temp dir itself is no longer a writable subpath.
    assert f"(subpath {native.sbpl_string(os.path.realpath(str(temp)))})" \
        not in text
