"""atlas native — the fully native macOS deployment (launchd + Seatbelt).

The macOS hybrid path runs llama-server natively and the other four
services in Docker Desktop. This path drops Docker entirely: every service
is a per-user launchd agent, and the sandbox — the container boundary in
every other deployment — runs under a macOS Seatbelt profile.

Each agent runs scripts/native/atlas-service.sh <service>, which plays the
part of one docker-compose.yml service entry (environment, depends_on,
working_dir) and listens on 127.0.0.1 at the host port compose would
publish, so `atlas`, the TUI and `atlas doctor` work unchanged.

Usage:
    atlas native install [service ...]    write + load the LaunchAgents
    atlas native uninstall [service ...]  unload + remove them
    atlas native start|stop|restart [service ...]
    atlas native status [--json]
    atlas native logs <service> [-n N] [-f]
    atlas native project <dir>            point the sandbox at a project
    atlas native print-plist <service>    show a generated LaunchAgent
    atlas native render-profile ...       write the sandbox Seatbelt profile
                                          (called by atlas-service.sh)
"""

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from atlas import compose as compose_config
from atlas.env import atlas_root as _atlas_root

# Start order: dependencies first (compose depends_on).
SERVICES = ["llama-server", "sandbox", "geometric-lens", "v3-service",
            "atlas-proxy"]

# Service -> key in atlas.compose's service URL table (health probes).
_URL_KEY = {
    "llama-server": "llama",
    "sandbox": "sandbox",
    "geometric-lens": "lens",
    "v3-service": "v3",
    "atlas-proxy": "proxy",
}

# launchd throttles CPU and I/O for agents without a ProcessType.
# Everything on the request path runs Interactive (no throttling); the
# sandbox runs Standard at a lower priority so a build or test run never
# competes with token generation.
_PROCESS_TYPE = {"sandbox": "Standard"}
_NICE = {"sandbox": 5}
# llama-server unmaps a multi-GB model on exit; give it time.
_EXIT_TIMEOUT = {"llama-server": 30}

DEFAULT_LABEL_PREFIX = "ai.atlas"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _home() -> str:
    return os.path.expanduser("~")


def _env_value(key: str, default: str = "") -> str:
    """Process environment, then the checkout's .env, then `default`."""
    value = os.environ.get(key)
    if value:
        return value
    return compose_config.read_env_file(_atlas_root()).get(key) or default


def label_prefix() -> str:
    return _env_value("ATLAS_LAUNCHD_PREFIX", DEFAULT_LABEL_PREFIX)


def label(service: str) -> str:
    return f"{label_prefix()}.{service}"


def launch_agents_dir() -> str:
    return os.path.join(_home(), "Library", "LaunchAgents")


def plist_path(service: str) -> str:
    return os.path.join(launch_agents_dir(), f"{label(service)}.plist")


def log_dir() -> str:
    return os.path.join(_home(), "Library", "Logs", "atlas")


def log_path(service: str) -> str:
    return os.path.join(log_dir(), f"{service}.log")


def native_home() -> str:
    return os.path.expanduser(
        _env_value("ATLAS_NATIVE_HOME", os.path.join(_home(), ".atlas",
                                                     "native")))


def domain_target() -> str:
    return f"gui/{os.getuid()}"


def service_target(service: str) -> str:
    return f"{domain_target()}/{label(service)}"


# ---------------------------------------------------------------------------
# LaunchAgent plists
# ---------------------------------------------------------------------------

def build_plist(service: str, atlas_root: str, home: str) -> Dict:
    """The LaunchAgent dictionary for one service."""
    if service not in SERVICES:
        raise ValueError(f"unknown service: {service}")
    log = os.path.join(home, "Library", "Logs", "atlas", f"{service}.log")
    plist = {
        "Label": label(service),
        "ProgramArguments": [
            "/bin/bash",
            os.path.join(atlas_root, "scripts", "native", "atlas-service.sh"),
            service,
        ],
        "WorkingDirectory": atlas_root,
        "EnvironmentVariables": {
            "ATLAS_ROOT": atlas_root,
            "HOME": home,
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:"
                    "/usr/sbin:/sbin",
        },
        "RunAtLoad": True,
        # Restart after a crash or a failed start, not after a clean stop.
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": _PROCESS_TYPE.get(service, "Interactive"),
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "SoftResourceLimits": {"NumberOfFiles": 65536},
    }
    if service in _NICE:
        plist["Nice"] = _NICE[service]
    if service in _EXIT_TIMEOUT:
        plist["ExitTimeOut"] = _EXIT_TIMEOUT[service]
    return plist


def render_plist(service: str, atlas_root: Optional[str] = None,
                 home: Optional[str] = None) -> bytes:
    return plistlib.dumps(build_plist(service, atlas_root or _atlas_root(),
                                      home or _home()))


# ---------------------------------------------------------------------------
# Seatbelt profile
# ---------------------------------------------------------------------------

# Programs that start work OUTSIDE the sandbox (launchd jobs, apps,
# AppleScript) or reach credentials/the clipboard.
_DENIED_EXECUTABLES = [
    "/bin/launchctl",
    "/usr/bin/open",
    "/usr/bin/osascript",
    "/usr/bin/security",
    "/usr/bin/sudo",
    "/usr/bin/su",
    "/usr/bin/login",
    "/usr/bin/pbcopy",
    "/usr/bin/pbpaste",
    "/usr/sbin/screencapture",
]

# Device nodes ordinary programs write to.
_DEVICE_WRITES = [
    '(literal "/dev/null")',
    '(literal "/dev/zero")',
    '(literal "/dev/tty")',
    '(literal "/dev/dtracehelper")',
    '(regex #"^/dev/fd/")',
    '(regex #"^/dev/ttys[0-9]+$")',
]


@dataclass
class SeatbeltConfig:
    project: str               # ATLAS_PROJECT_DIR — the container's /workspace
    sandbox_home: str          # private HOME (the container's tmpfs mounts)
    sandbox_tmp: str           # private TMPDIR / WORKSPACE_BASE parent
    venv: str                  # the sandbox service's Python venv
    secrets: str               # ATLAS_SECRETS_DIR
    token_file: str            # service token the server authenticates with
    atlas_root: str
    prefix: str                # ATLAS_MACOS_PREFIX (native binaries)
    real_home: str
    darwin_temp: str = ""      # getconf DARWIN_USER_TEMP_DIR
    darwin_cache: str = ""     # getconf DARWIN_USER_CACHE_DIR
    deny_ports: List[int] = field(default_factory=list)
    net_internal: bool = False
    extra_read: List[str] = field(default_factory=list)


def sbpl_string(path: str) -> str:
    """Quote a path as an SBPL string literal."""
    if any(c in path for c in "\n\r\0"):
        raise ValueError(f"unsupported character in path: {path!r}")
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _real(path: str) -> str:
    # Seatbelt matches resolved paths (/tmp is /private/tmp, /var is
    # /private/var), so every path in the profile is resolved first.
    return os.path.realpath(os.path.expanduser(path)) if path else ""


def _venv_base_prefix(venv: str) -> str:
    """The interpreter installation a venv was created from (pyvenv.cfg's
    `home`, minus its bin/), so its stdlib is readable in the sandbox."""
    try:
        with open(os.path.join(venv, "pyvenv.cfg"), encoding="utf-8") as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key.strip() == "home" and value.strip():
                    return os.path.dirname(value.strip())
    except OSError:
        pass
    return ""


def _sbpl_regex_escape(path: str) -> str:
    """Escape a literal path for use inside an SBPL #"..." regex."""
    sbpl_string(path)  # same character restrictions
    out = []
    for c in path:
        if c in ".^$*+?()[]{}|\\":
            out.append("\\" + c)
        elif c == '"':
            raise ValueError(f"unsupported character in path: {path!r}")
        else:
            out.append(c)
    return "".join(out)


def _subpaths(paths: Sequence[str]) -> str:
    return " ".join(f"(subpath {sbpl_string(p)})" for p in paths if p)


def render_seatbelt_profile(cfg: SeatbeltConfig) -> str:
    """Seatbelt (SBPL) profile for the sandbox service and everything it
    runs. Later rules override earlier ones, so each section narrows the
    one before it. What it reproduces from the container:

    * the project is the only writable host path (container: /workspace
      bind mount + read-only rootfs); toolchain caches go to a private
      HOME/TMPDIR (container: tmpfs mounts);
    * nothing else in the real home is readable — no ~/.ssh, keychains,
      browser data, cloud credentials (container: separate filesystem);
    * secrets/ and .env are unreadable even when the project is the ATLAS
      checkout, except the service token (container: mounted read-only);
    * ATLAS_SANDBOX_NET_INTERNAL=true cuts all IP egress (container:
      internal sandbox-net).

    Beyond the container: code here can't signal processes outside the
    sandbox, can't reach the other ATLAS services on localhost, can't
    start launchd jobs / apps / AppleScript, and can't plant git hooks
    that the host's git would later run.

    Not reproduced: cgroup memory/CPU/pids caps. Execution time is
    bounded by the executor's own timeouts.
    """
    home = _real(cfg.real_home)
    project = _real(cfg.project)
    root = _real(cfg.atlas_root)
    secrets = _real(cfg.secrets)
    sbx_home = _real(cfg.sandbox_home)
    sbx_tmp = _real(cfg.sandbox_tmp)
    venv = _real(cfg.venv)
    readable = [project, sbx_home, sbx_tmp, venv,
                os.path.join(root, "sandbox"),
                _real(_venv_base_prefix(cfg.venv))]
    readable += [_real(p) for p in cfg.extra_read]
    writable = [project, sbx_home, sbx_tmp]
    # The per-user temp/cache dirs (/var/folders/<x>/<y>/{T,C}) hold every
    # app's scratch files. Executed code gets TMPDIR in the private tmp;
    # only the caches xcrun/clang insist on writing there stay reachable.
    darwin_base = ""
    darwin_caches: List[str] = []
    if cfg.darwin_temp:
        darwin_base = os.path.dirname(_real(cfg.darwin_temp))
        darwin_caches.append(
            f'(regex #"^{_sbpl_regex_escape(_real(cfg.darwin_temp))}/xcrun_db")')
    if cfg.darwin_cache:
        cache = _real(cfg.darwin_cache)
        darwin_base = darwin_base or os.path.dirname(cache)
        for sub in ("clang", "com.apple.DeveloperTools", "xcrun_db"):
            darwin_caches.append(
                f"(subpath {sbpl_string(os.path.join(cache, sub))})")
    protected_writes = [
        os.path.join(root, d) for d in ("scripts", "atlas", "sandbox",
                                        "proxy", "inference", "tui")
    ] + [secrets, _real(cfg.prefix)]

    lines = [
        "(version 1)",
        ";; ATLAS sandbox profile — generated by `atlas native "
        "render-profile`",
        ";; on every sandbox start. Edits are overwritten.",
        "(allow default)",
        "",
        ";; Reads: nothing under the real home or on other volumes except",
        ";; what the sandbox needs. Metadata stays readable so path lookups",
        ";; through the home directory still resolve.",
        f"(deny file-read-data file-read-xattr (subpath {sbpl_string(home)})"
        ' (subpath "/Volumes")'
        + (f" (subpath {sbpl_string(darwin_base)})" if darwin_base else "")
        + ")",
        f"(allow file-read-data file-read-xattr {_subpaths(readable)}"
        + "".join(" " + c for c in darwin_caches) + ")",
        "",
        ";; Secrets: unreadable even inside the project, except the token",
        ";; the executor authenticates requests with.",
        f"(deny file-read* (subpath {sbpl_string(secrets)})"
        f" (literal {sbpl_string(os.path.join(root, '.env'))}))",
    ]
    if cfg.token_file:
        lines.append(
            f"(allow file-read* (literal {sbpl_string(_real(cfg.token_file))}))")
    lines += [
        "",
        ";; Writes: the project, the private home/tmp, the xcrun/clang",
        ";; caches and ordinary device nodes.",
        "(deny file-write*)",
        f"(allow file-write* {_subpaths(writable)}"
        + "".join(" " + c for c in darwin_caches),
        "  " + " ".join(_DEVICE_WRITES) + ")",
        ";; ...but never ATLAS's own code, binaries or secrets (launchd runs",
        ";; those outside the sandbox) or the project's git hooks/config",
        ";; (the host's git would execute them).",
        f"(deny file-write* {_subpaths(protected_writes)}",
        f"  (literal {sbpl_string(os.path.join(root, '.env'))})",
        f"  (subpath {sbpl_string(os.path.join(project, '.git', 'hooks'))})",
        f"  (literal {sbpl_string(os.path.join(project, '.git', 'config'))}))",
        "",
        ";; Processes: signals stay inside this sandbox; nothing that starts",
        ";; work outside it.",
        "(deny signal)",
        "(allow signal (target same-sandbox))",
        "(deny process-exec "
        + " ".join(f"(literal {sbpl_string(p)})" for p in _DENIED_EXECUTABLES)
        + ")",
        "(deny appleevent-send)",
        '(deny mach-lookup (global-name "com.apple.pasteboard.1"))',
        "",
        ";; Network.",
    ]
    if cfg.net_internal:
        lines += [
            ";; ATLAS_SANDBOX_NET_INTERNAL=true: no IP egress at all.",
            '(deny network-outbound (remote ip "*:*"))',
        ]
    elif cfg.deny_ports:
        lines.append(";; The other ATLAS services are off limits.")
        lines.append(
            "(deny network-outbound "
            + " ".join(f'(remote ip "localhost:{int(p)}")'
                       for p in cfg.deny_ports)
            + ")")
    return "\n".join(lines) + "\n"


def _getconf(name: str) -> str:
    try:
        p = subprocess.run(["getconf", name], capture_output=True, text=True,
                           timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _cmd_render_profile(args: argparse.Namespace) -> int:
    home = _home()
    extra = []
    for p in (os.path.join(home, ".rustup"), os.path.join(home, ".cargo",
                                                           "bin")):
        if os.path.isdir(p):
            extra.append(p)
    cfg = SeatbeltConfig(
        project=args.project, sandbox_home=args.sandbox_home,
        sandbox_tmp=args.sandbox_tmp, venv=args.venv, secrets=args.secrets,
        token_file=args.token_file if os.path.isfile(args.token_file) else "",
        atlas_root=args.atlas_root, prefix=args.prefix, real_home=home,
        darwin_temp=_getconf("DARWIN_USER_TEMP_DIR"),
        darwin_cache=_getconf("DARWIN_USER_CACHE_DIR"),
        deny_ports=args.deny_port or [],
        net_internal=_truthy(args.net_internal), extra_read=extra)
    text = render_seatbelt_profile(cfg)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, args.out)
    return 0


# ---------------------------------------------------------------------------
# launchctl
# ---------------------------------------------------------------------------

def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True,
                          text=True, timeout=60)


def _print_info(service: str) -> Dict[str, str]:
    """`launchctl print` fields for a loaded service ({} if not loaded)."""
    p = _launchctl("print", service_target(service))
    if p.returncode != 0:
        return {}
    info = {"loaded": "yes"}
    for line in p.stdout.splitlines():
        key, sep, value = line.strip().partition(" = ")
        if sep and key in ("pid", "state", "last exit code", "runs"):
            info[key] = value.strip()
    return info


def _health(service: str, timeout: float = 3.0) -> bool:
    url = compose_config.service_url(_URL_KEY[service]) + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _select(names: Sequence[str]) -> List[str]:
    if not names:
        return list(SERVICES)
    unknown = [n for n in names if n not in SERVICES]
    if unknown:
        raise SystemExit(f"atlas native: unknown service(s): "
                         f"{', '.join(unknown)} (known: {', '.join(SERVICES)})")
    return [s for s in SERVICES if s in names]


def _require_macos() -> Optional[int]:
    if sys.platform != "darwin":
        print("atlas native: the native deployment is macOS-only.",
              file=sys.stderr)
        return 1
    return None


def _write_plist(service: str) -> str:
    path = plist_path(service)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(log_dir(), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(render_plist(service))
    os.replace(tmp, path)
    return path


def _bootstrap(service: str) -> bool:
    # Clear a `stop` (persistent disable) first; bootstrap refuses a
    # disabled service.
    _launchctl("enable", service_target(service))
    p = _launchctl("bootstrap", domain_target(), plist_path(service))
    if p.returncode != 0 and not _print_info(service):
        print(f"  {service}: launchctl bootstrap failed: "
              f"{(p.stderr or p.stdout).strip()}", file=sys.stderr)
        return False
    return True


def _bootout(service: str) -> None:
    if _print_info(service):
        _launchctl("bootout", service_target(service))


def _cmd_install(args: argparse.Namespace) -> int:
    ok = True
    for service in _select(args.services):
        path = _write_plist(service)
        # Reload so a changed plist takes effect.
        _bootout(service)
        if _bootstrap(service):
            print(f"  {service}: loaded {path}")
        else:
            ok = False
    if ok:
        print(f"  logs: {log_dir()}/<service>.log — "
              f"`atlas native status` to watch them come up")
    return 0 if ok else 1


def _cmd_uninstall(args: argparse.Namespace) -> int:
    for service in reversed(_select(args.services)):
        _bootout(service)
        # Drop any disable override `stop` left in launchd's database.
        _launchctl("enable", service_target(service))
        path = plist_path(service)
        if os.path.exists(path):
            os.remove(path)
        print(f"  {service}: removed")
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    ok = True
    for service in _select(args.services):
        if not os.path.exists(plist_path(service)):
            print(f"  {service}: not installed — run `atlas native install`",
                  file=sys.stderr)
            ok = False
            continue
        if _print_info(service):
            _launchctl("kickstart", service_target(service))
        elif not _bootstrap(service):
            ok = False
            continue
        print(f"  {service}: started")
    return 0 if ok else 1


def _cmd_stop(args: argparse.Namespace) -> int:
    for service in reversed(_select(args.services)):
        _bootout(service)
        # Disabled services stay down across logins (launchd would
        # otherwise reload every plist in ~/Library/LaunchAgents).
        _launchctl("disable", service_target(service))
        print(f"  {service}: stopped")
    return 0


def _cmd_restart(args: argparse.Namespace) -> int:
    ok = True
    for service in _select(args.services):
        if _print_info(service):
            p = _launchctl("kickstart", "-k", service_target(service))
            if p.returncode != 0:
                print(f"  {service}: kickstart failed: "
                      f"{(p.stderr or p.stdout).strip()}", file=sys.stderr)
                ok = False
                continue
        elif not (os.path.exists(plist_path(service))
                  and _bootstrap(service)):
            print(f"  {service}: not installed — run `atlas native install`",
                  file=sys.stderr)
            ok = False
            continue
        print(f"  {service}: restarted")
    return 0 if ok else 1


def _cmd_status(args: argparse.Namespace) -> int:
    rows = []
    for service in SERVICES:
        info = _print_info(service)
        rows.append({
            "service": service,
            "label": label(service),
            "installed": os.path.exists(plist_path(service)),
            "loaded": bool(info),
            "pid": info.get("pid", ""),
            "last_exit": info.get("last exit code", ""),
            "healthy": _health(service) if info else False,
        })
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"  {'service':<15} {'loaded':<7} {'pid':<7} {'health':<8} "
              f"last exit")
        for r in rows:
            loaded = "yes" if r["loaded"] else (
                "no" if r["installed"] else "-")
            health = "ok" if r["healthy"] else ("down" if r["loaded"] else "-")
            print(f"  {r['service']:<15} {loaded:<7} {r['pid']:<7} "
                  f"{health:<8} {r['last_exit']}")
    return 0 if all(r["healthy"] for r in rows) else 1


def _cmd_logs(args: argparse.Namespace) -> int:
    path = log_path(args.service)
    if not os.path.exists(path):
        print(f"atlas native: no log yet at {path}", file=sys.stderr)
        return 1
    cmd = ["tail", "-n", str(args.lines)]
    if args.follow:
        cmd.append("-F")
    try:
        return subprocess.call(cmd + [path])
    except KeyboardInterrupt:
        return 0


def set_project(directory: str, wait: float = 30.0) -> int:
    """Point the sandbox at `directory` and restart it.

    The native proxy has no fixed workspace (it uses each request's
    working_dir), but the sandbox's workspace root must equal the project
    directory: V3 build verification snapshots that root and writes
    candidate files relative to it. This is the native counterpart of the
    compose path's `_align_workspace` container recreate."""
    from atlas.commands.fit import _write_env
    target = os.path.realpath(os.path.expanduser(directory))
    if not os.path.isdir(target):
        print(f"atlas native: not a directory: {target}", file=sys.stderr)
        return 1
    path = _write_env({"ATLAS_PROJECT_DIR": target})
    print(f"  ATLAS_PROJECT_DIR={target} (wrote {path})")
    rc = _cmd_restart(argparse.Namespace(services=["sandbox"]))
    if rc != 0:
        return rc
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if _health("sandbox", timeout=2.0):
            return 0
        time.sleep(0.5)
    print(f"  sandbox did not become healthy within {wait:.0f}s — "
          f"`atlas native logs sandbox`", file=sys.stderr)
    return 1


def _cmd_project(args: argparse.Namespace) -> int:
    return set_project(args.dir)


def _cmd_print_plist(args: argparse.Namespace) -> int:
    sys.stdout.write(render_plist(args.service).decode("utf-8"))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas native",
        description="Run the ATLAS stack natively on macOS (launchd agents, "
                    "Seatbelt-confined sandbox).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (("install", "write and load the LaunchAgents"),
                           ("uninstall", "unload and remove the LaunchAgents"),
                           ("start", "start services"),
                           ("stop", "stop services and keep them stopped "
                                    "across logins (LaunchAgents stay "
                                    "installed)"),
                           ("restart", "restart services")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("services", nargs="*", metavar="service",
                       help=f"default: all ({', '.join(SERVICES)})")
    p = sub.add_parser("status", help="launchd state + health per service")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("logs", help="show a service log")
    p.add_argument("service", choices=SERVICES)
    p.add_argument("-n", "--lines", type=int, default=100)
    p.add_argument("-f", "--follow", action="store_true")
    p = sub.add_parser("project", help="set ATLAS_PROJECT_DIR and restart "
                                       "the sandbox")
    p.add_argument("dir")
    p = sub.add_parser("print-plist", help="print a generated LaunchAgent")
    p.add_argument("service", choices=SERVICES)
    p = sub.add_parser("render-profile",
                       help="write the sandbox Seatbelt profile")
    p.add_argument("--out", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--sandbox-home", required=True)
    p.add_argument("--sandbox-tmp", required=True)
    p.add_argument("--venv", required=True)
    p.add_argument("--secrets", required=True)
    p.add_argument("--token-file", default="")
    p.add_argument("--atlas-root", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--deny-port", type=int, action="append")
    p.add_argument("--net-internal", default="")
    return parser


_COMMANDS = {
    "install": _cmd_install,
    "uninstall": _cmd_uninstall,
    "start": _cmd_start,
    "stop": _cmd_stop,
    "restart": _cmd_restart,
    "status": _cmd_status,
    "logs": _cmd_logs,
    "project": _cmd_project,
    "print-plist": _cmd_print_plist,
    "render-profile": _cmd_render_profile,
}

# Commands that only render text and are safe anywhere (tests, CI).
_PORTABLE = {"print-plist", "render-profile"}


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command not in _PORTABLE:
        rc = _require_macos()
        if rc is not None:
            return rc
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
