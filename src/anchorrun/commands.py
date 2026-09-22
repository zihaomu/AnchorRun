from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from anchorrun.errors import ConfigError
from anchorrun.model import ArtifactConfig, TargetConfig, WorkspaceConfig


def build_remote_mkdir(target: TargetConfig) -> list[str]:
    script = f"mkdir -p -- {shlex.quote(target.remote_root)}"
    return ["ssh", target.ssh_host, script]


def build_prepare_command(target: TargetConfig) -> list[str]:
    runtime = shlex.quote(target.container.runtime)
    image = shlex.quote(target.container.image)
    root = shlex.quote(target.remote_root)
    script = "\n".join(
        [
            "set -eu",
            f"command -v {runtime} >/dev/null 2>&1",
            f"mkdir -p -- {root}",
            f"if ! {runtime} image inspect {image} >/dev/null 2>&1; then {runtime} pull {image}; fi",
        ]
    )
    return ["ssh", target.ssh_host, script]


def build_sync_command(
    config: WorkspaceConfig,
    target: TargetConfig,
    *,
    dry_run: bool = False,
    delete: bool = False,
) -> list[str]:
    if delete and not config.sync.allow_delete:
        raise ConfigError(
            "sync.allow_delete",
            "remote deletion is disabled; enable it in config and pass --delete",
        )
    command = ["rsync", "-rlt", "--safe-links", "--itemize-changes"]
    if dry_run:
        command.append("--dry-run")
    if delete:
        command.append("--delete")
    for pattern in config.sync.excludes:
        command.extend(["--exclude", pattern])
    command.extend(
        [
            "--",
            f"{config.local_root}/",
            f"{target.ssh_host}:{target.remote_root}/",
        ]
    )
    return command


def build_container_argv(
    target: TargetConfig,
    command_args: Sequence[str],
    *,
    interactive: bool = False,
) -> list[str]:
    container = target.container
    command = [container.runtime, "run", "--rm"]
    if interactive:
        command.extend(["--interactive", "--tty"])
    command.extend(
        [
            "--volume",
            f"{target.remote_root}:{container.workdir}",
            "--workdir",
            container.workdir,
        ]
    )
    for device in container.devices:
        command.extend(["--device", device])
    for option in container.security_options:
        command.extend(["--security-opt", option])
    for mount in container.mounts:
        specification = f"{mount.source}:{mount.target}"
        if mount.read_only:
            specification += ":ro"
        command.extend(["--volume", specification])
    for name in container.environment_from_host:
        command.extend(["--env", name])
    command.append(container.image)
    command.extend(command_args)
    return command


def build_remote_exec(
    target: TargetConfig,
    command_args: Sequence[str],
    *,
    interactive: bool = False,
) -> list[str]:
    container_command = build_container_argv(
        target,
        command_args,
        interactive=interactive,
    )
    ssh_command = ["ssh"]
    if interactive:
        ssh_command.append("-t")
    ssh_command.extend([target.ssh_host, shlex.join(container_command)])
    return ssh_command


def build_pull_command(
    config: WorkspaceConfig,
    target: TargetConfig,
    artifact: ArtifactConfig,
    *,
    dry_run: bool = False,
) -> tuple[list[str], Path]:
    destination = config.local_root / artifact.local
    command = ["rsync", "-rlt", "--safe-links", "--itemize-changes"]
    if dry_run:
        command.append("--dry-run")
    command.extend(
        [
            "--",
            f"{target.ssh_host}:{target.remote_root}/{artifact.remote}/",
            f"{destination}/",
        ]
    )
    return command, destination


def build_remote_doctor_script(target: TargetConfig) -> str:
    runtime = shlex.quote(target.container.runtime)
    image = shlex.quote(target.container.image)
    root = shlex.quote(target.remote_root)
    parent = shlex.quote(str(PurePosixPath(target.remote_root).parent))
    return "\n".join(
        [
            "set -u",
            'printf "user=%s\\n" "$(id -un)"',
            f"if command -v {runtime} >/dev/null 2>&1; then echo runtime=yes; else echo runtime=no; fi",
            f"if {runtime} image inspect {image} >/dev/null 2>&1; then echo image=yes; else echo image=no; fi",
            f"root={root}",
            f"probe={parent}",
            'while [ ! -e "$probe" ] && [ "$probe" != / ]; do probe=$(dirname -- "$probe"); done',
            'if [ -d "$root" ]; then probe="$root"; fi',
            'if [ -d "$probe" ] && [ -w "$probe" ]; then echo path=yes; else echo path=no; fi',
        ]
    )
