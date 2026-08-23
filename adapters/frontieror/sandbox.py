"""Bubblewrap command construction for model-controlled subprocesses."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


class SandboxUnavailable(RuntimeError):
    pass


def command(workspace: Path, argv: list[str]) -> list[str]:
    """Return an argv that exposes only the task workspace and runtime files."""
    if sys.platform != "linux":
        return argv
    if shutil.which("bwrap") is None:
        raise SandboxUnavailable("bwrap is required for FrontierOR execution")

    workspace = workspace.resolve()
    env_dir = Path(sys.prefix).resolve()
    gurobi_home = Path(os.environ.get("GUROBI_HOME", "/home/bhz/gurobi1302")).resolve()
    license_file = Path(
        os.environ.get("GRB_LICENSE_FILE", "/home/bhz/gurobi.lic")
    ).resolve()
    sandbox_etc = workspace.parent / f".sandbox-etc-{workspace.name}"
    passwd = sandbox_etc / "passwd"
    group = sandbox_etc / "group"
    passwd.parent.mkdir(parents=True, exist_ok=True)
    passwd.write_text(
        f"bhz:x:{os.getuid()}:{os.getgid()}:sandbox:/work:/bin/sh\n", encoding="utf-8"
    )
    group.write_text(f"bhz:x:{os.getgid()}:\n", encoding="utf-8")

    box = [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/sbin", "/sbin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", str(passwd), "/etc/passwd",
        "--ro-bind", str(group), "/etc/group",
        "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
        "--ro-bind", "/etc/ssl", "/etc/ssl",
        "--ro-bind-try", "/etc/ca-certificates", "/etc/ca-certificates",
        "--ro-bind", str(env_dir), str(env_dir),
        "--bind", str(workspace), "/work",
        "--tmpfs", "/tmp",
        "--proc", "/proc",
        "--dev", "/dev",
        # Keep the host network namespace so node-locked Gurobi licenses can
        # resolve the host ID. Other sandbox isolation remains enabled.
        "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--die-with-parent", "--new-session", "--chdir", "/work",
    ]
    if gurobi_home.exists() and not str(gurobi_home).startswith(str(env_dir)):
        box.extend(["--ro-bind", str(gurobi_home), str(gurobi_home)])
    if license_file.is_file():
        box.extend(["--ro-bind", str(license_file), str(license_file)])
    return [*box, "--", *argv]
