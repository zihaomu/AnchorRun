from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from anchorrun.commands import (
    build_prepare_command,
    build_pull_command,
    build_remote_doctor_script,
    build_remote_exec,
    build_remote_mkdir,
    build_sync_command,
)
from anchorrun.errors import CommandError, ConfigError
from anchorrun.model import TargetConfig, WorkspaceConfig


@dataclass(frozen=True)
class RemoteProbe:
    target: str
    ssh_host: str
    reachable: bool
    runtime_available: bool
    image_present: bool
    remote_path_writable: bool
    user: str | None
    message: str

    @property
    def ready(self) -> bool:
        return (
            self.reachable
            and self.runtime_available
            and self.image_present
            and self.remote_path_writable
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "ssh_host": self.ssh_host,
            "ready": self.ready,
            "reachable": self.reachable,
            "runtime_available": self.runtime_available,
            "image_present": self.image_present,
            "remote_path_writable": self.remote_path_writable,
            "user": self.user,
            "message": self.message,
        }


def format_command(command: Sequence[str]) -> str:
    return shlex.join(command)


def run_command(
    command: Sequence[str],
    *,
    name: str,
    dry_run: bool = False,
) -> None:
    print(f"+ {format_command(command)}", file=sys.stderr)
    if dry_run:
        return
    completed = subprocess.run(list(command), check=False)
    if completed.returncode != 0:
        raise CommandError(name, completed.returncode)


def local_issues(config: WorkspaceConfig) -> list[str]:
    issues: list[str] = []
    if not config.local_root.is_dir():
        issues.append(f"local project directory does not exist: {config.local_root}")
    for executable in ("ssh", "rsync"):
        if shutil.which(executable) is None:
            issues.append(f"required executable is unavailable: {executable}")
    return issues


def prepare_target(target: TargetConfig, *, dry_run: bool = False) -> None:
    run_command(
        build_prepare_command(target),
        name="remote target preparation",
        dry_run=dry_run,
    )


def probe_target(target: TargetConfig, timeout_seconds: int = 20) -> RemoteProbe:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        f"ConnectTimeout={min(timeout_seconds, 10)}",
        target.ssh_host,
        build_remote_doctor_script(target),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return RemoteProbe(
            target=target.name,
            ssh_host=target.ssh_host,
            reachable=False,
            runtime_available=False,
            image_present=False,
            remote_path_writable=False,
            user=None,
            message=f"SSH probe timed out after {timeout_seconds}s",
        )

    if completed.returncode != 0:
        message = completed.stderr.strip() or f"ssh exited with {completed.returncode}"
        return RemoteProbe(
            target=target.name,
            ssh_host=target.ssh_host,
            reachable=False,
            runtime_available=False,
            image_present=False,
            remote_path_writable=False,
            user=None,
            message=message,
        )

    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    runtime = values.get("runtime") == "yes"
    image = values.get("image") == "yes"
    path = values.get("path") == "yes"
    problems: list[str] = []
    if not runtime:
        problems.append(f"{target.container.runtime} is unavailable")
    if not image:
        problems.append("configured image digest is not present")
    if not path:
        problems.append("remote root or its parent is not writable")
    return RemoteProbe(
        target=target.name,
        ssh_host=target.ssh_host,
        reachable=True,
        runtime_available=runtime,
        image_present=image,
        remote_path_writable=path,
        user=values.get("user") or None,
        message="; ".join(problems) if problems else "ready",
    )


def sync_workspace(
    config: WorkspaceConfig,
    target: TargetConfig,
    *,
    dry_run: bool = False,
    delete: bool = False,
) -> None:
    if dry_run:
        print(f"+ {format_command(build_remote_mkdir(target))}", file=sys.stderr)
    else:
        run_command(build_remote_mkdir(target), name="remote workspace creation")
    run_command(
        build_sync_command(config, target, dry_run=dry_run, delete=delete),
        name="workspace synchronization",
        dry_run=dry_run,
    )


def execute_remote(
    target: TargetConfig,
    command_args: Sequence[str],
    *,
    interactive: bool = False,
    dry_run: bool = False,
) -> None:
    if not command_args:
        raise ConfigError("command", "expected a command after --")
    run_command(
        build_remote_exec(target, command_args, interactive=interactive),
        name="remote container command",
        dry_run=dry_run,
    )


def pull_artifacts(
    config: WorkspaceConfig,
    target: TargetConfig,
    *,
    dry_run: bool = False,
) -> None:
    if not config.artifacts:
        raise ConfigError("artifacts", "no artifact mappings are configured")
    for artifact in config.artifacts:
        command, destination = build_pull_command(
            config,
            target,
            artifact,
            dry_run=dry_run,
        )
        if not dry_run:
            destination.mkdir(parents=True, exist_ok=True)
        run_command(
            command,
            name=f"artifact pull ({artifact.remote})",
            dry_run=dry_run,
        )
