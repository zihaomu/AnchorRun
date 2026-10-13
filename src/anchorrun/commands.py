from __future__ import annotations

import shlex
from collections.abc import Sequence

from anchorrun.model import TargetConfig

OWNER_LABEL = "io.anchorrun.workspace"
CONFIG_LABEL = "io.anchorrun.config"
IMAGE_LABEL = "io.anchorrun.image"


def ssh_command(
    target: TargetConfig, command: Sequence[str], *, interactive: bool = False
) -> list[str]:
    return [
        "ssh",
        "-t" if interactive else "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        target.ssh_host,
        shlex.join(command),
    ]


def build_container_create(target: TargetConfig, image_id: str) -> list[str]:
    container = target.container
    command = [
        container.runtime,
        "create",
        "--name",
        target.container_name,
        "--label",
        f"{OWNER_LABEL}={target.workspace_id}",
        "--label",
        f"{CONFIG_LABEL}={target.fingerprint}",
        "--label",
        f"{IMAGE_LABEL}={image_id}",
        "--mount",
        f"type=bind,src={target.remote_root},dst={container.workdir}",
        "--workdir",
        container.workdir,
        # A managed development container needs a persistent shell process,
        # even when the image normally launches an application.
        "--entrypoint",
        container.entrypoint or container.shell,
    ]
    if container.user is not None:
        command.extend(["--user", container.user])
    for device in container.devices:
        command.extend(["--device", device])
    for option in container.security_options:
        command.extend(["--security-opt", option])
    for mount in container.mounts:
        spec = f"type=bind,src={mount.source},dst={mount.target}"
        if mount.read_only:
            spec += ",readonly"
        command.extend(["--mount", spec])
    for name in container.environment_from_host:
        command.extend(["--env", name])
    command.extend(
        [
            image_id,
            "-c",
            "trap 'exit 0' TERM INT; while :; do sleep 3600 & wait $!; done",
        ]
    )
    return command


def build_remote_exec(
    target: TargetConfig,
    command_args: Sequence[str],
    *,
    container_id: str | None = None,
    interactive: bool = False,
    stdin: bool = False,
) -> list[str]:
    command = [target.container.runtime, "exec"]
    if interactive or stdin:
        command.append("-i")
    if interactive:
        command.append("-t")
    command.extend(
        ["--workdir", target.container.workdir, container_id or target.container_name]
    )
    command.extend(command_args)
    return ssh_command(target, command, interactive=interactive)
