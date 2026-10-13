from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence

from anchorrun.commands import (
    CONFIG_LABEL,
    IMAGE_LABEL,
    OWNER_LABEL,
    build_container_create,
    build_remote_exec,
    ssh_command,
)
from anchorrun.errors import (
    AnchorRunError,
    CommandError,
    CommandStartError,
    ConfigError,
)
from anchorrun.model import TargetConfig


def run_command(
    command: Sequence[str],
    *,
    capture: bool = False,
    stdin: bool = False,
    timeout: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            list(command),
            check=False,
            capture_output=capture,
            text=capture,
            stdin=None if stdin else subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise CommandStartError("remote operation", str(exc)) from exc
    if capture and check and result.returncode:
        detail = (result.stderr or "").strip()
        if detail:
            print(detail, file=sys.stderr)
        raise CommandError("remote operation", result.returncode)
    return result


def _capture(
    target: TargetConfig, command: Sequence[str], *, timeout: int | None = 20
) -> str:
    return run_command(
        ssh_command(target, command), capture=True, timeout=timeout
    ).stdout.strip()


def inspect_container(target: TargetConfig, *, timeout: int = 20) -> dict | None:
    runtime = target.container.runtime
    # Listing first distinguishes an absent container from a broken daemon or
    # denied Docker socket. Never interpret an arbitrary inspect error as absence.
    found = _capture(
        target,
        [
            runtime,
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--filter",
            f"name=^/{target.container_name}$",
            "--format",
            "{{.ID}}",
        ],
        timeout=timeout,
    )
    if not found:
        return None
    raw = _capture(
        target,
        [runtime, "container", "inspect", target.container_name],
        timeout=timeout,
    )
    try:
        records = json.loads(raw)
        info = records[0]
        if (
            not isinstance(info, dict)
            or not isinstance(info.get("Config"), dict)
            or not isinstance(info.get("State"), dict)
        ):
            raise TypeError("missing Config or State")
        if not isinstance(info.get("Id"), str) or not info["Id"]:
            raise ValueError("missing container ID")
        labels = info["Config"].get("Labels")
        if labels is not None and (
            not isinstance(labels, dict)
            or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in labels.items()
            )
        ):
            raise TypeError("invalid container labels")
        if type(info["State"].get("Running")) is not bool:
            raise TypeError("invalid running state")
        for key in ("Paused", "Restarting"):
            if key in info["State"] and type(info["State"][key]) is not bool:
                raise TypeError("invalid container state")
        info["Image"] = _normalize_image_id(info.get("Image"))
        return info
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ConfigError("remote", "invalid container inspection response") from exc


def validate_container(
    target: TargetConfig, info: dict, *, matching: bool = True
) -> None:
    labels = info["Config"].get("Labels") or {}
    if labels.get(OWNER_LABEL) != target.workspace_id:
        raise ConfigError(
            "container",
            f"{target.container_name} is not owned by this workspace; refusing to use or replace it",
        )
    if matching and labels.get(CONFIG_LABEL) != target.fingerprint:
        raise ConfigError(
            "container",
            "configuration changed; run prepare --recreate explicitly (container-only changes will be lost)",
        )
    if matching and labels.get(IMAGE_LABEL) != info.get("Image"):
        raise ConfigError(
            "container",
            "recorded image does not match container image; inspect before recreating",
        )


def _paths_command(target: TargetConfig, *, create: bool) -> list[str]:
    root = shlex.quote(target.remote_root)
    lines = ["set -eu"]
    if create:
        lines.append(f"mkdir -p -- {root}")
    lines.append(
        f"test -d {root} || {{ echo 'remote_root is not a directory' >&2; exit 1; }}"
    )
    for mount in target.container.mounts:
        lines.append(
            f"test -e {shlex.quote(mount.source)} || {{ echo 'configured mount source is missing' >&2; exit 1; }}"
        )
    return ["sh", "-c", "\n".join(lines)]


def _ready_container(target: TargetConfig, *, timeout: int = 20) -> dict:
    info = inspect_container(target, timeout=timeout)
    if info is None:
        raise ConfigError("container", "not prepared; run prepare")
    validate_container(target, info)
    if (
        not info["State"].get("Running")
        or info["State"].get("Paused")
        or info["State"].get("Restarting")
    ):
        raise ConfigError(
            "container",
            "not running; run prepare (paused/restarting containers need inspection)",
        )
    return info


def probe_target(target: TargetConfig, *, timeout: int = 20) -> dict:
    result = {
        "target": target.name,
        "ssh_host": target.ssh_host,
        "remote_root": target.remote_root,
        "container_name": target.container_name,
        "ready": False,
    }
    try:
        _capture(target, _paths_command(target, create=False), timeout=timeout)
        info = _ready_container(target, timeout=timeout)
        _capture(
            target,
            [
                target.container.runtime,
                "exec",
                "--workdir",
                target.container.workdir,
                info["Id"],
                target.container.shell,
                "-c",
                "test -r . && test -w .",
            ],
            timeout=timeout,
        )
        result.update(
            ready=True, container_id=info["Id"], image_id=info["Image"], message="ready"
        )
    except AnchorRunError as exc:
        result["message"] = str(exc)
    return result


def local_issues() -> list[str]:
    return [] if shutil.which("ssh") else ["required executable is unavailable: ssh"]


def _normalize_image_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:sha256:)?[0-9a-f]{64}", value
    ):
        raise ConfigError("image", "runtime did not return an immutable image ID")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _resolve_image(target: TargetConfig) -> str:
    command = [
        target.container.runtime,
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        target.container.image,
    ]
    result = run_command(
        ssh_command(target, command), capture=True, check=False, timeout=20
    )
    if result.returncode:
        detail = (result.stderr or "").strip()
        absent = any(
            message in detail.lower()
            for message in ("no such image", "image not known")
        )
        if result.returncode == 255 or not absent:
            if detail:
                print(detail, file=sys.stderr)
            raise CommandError("image inspection", result.returncode)
        _capture(
            target,
            [target.container.runtime, "pull", target.container.image],
            timeout=None,
        )
        return _normalize_image_id(_capture(target, command))
    return _normalize_image_id(result.stdout.strip())


def prepare_target(
    target: TargetConfig, *, recreate: bool = False, dry_run: bool = False
) -> dict | None:
    if dry_run:
        print(
            json.dumps(
                {
                    "target": target.name,
                    "remote_root": target.remote_root,
                    "container_name": target.container_name,
                    "image": target.container.image,
                    "action": "replace managed container"
                    if recreate
                    else "create or reuse managed container",
                    "changes": [
                        "ensure remote directory",
                        "resolve local image or pull if missing",
                        "create/start container if needed",
                    ],
                },
                indent=2,
            )
        )
        return None
    info = inspect_container(target)
    if info is not None:
        validate_container(target, info, matching=not recreate)
    # Check paths and resolve the replacement before removing an old container.
    _capture(target, _paths_command(target, create=True))
    if info is None or recreate:
        runtime = target.container.runtime
        image_id = _resolve_image(target)
        if info is not None:
            print(
                "Replacing managed container; its writable layer will be lost. Remote bind mounts are retained.",
                file=sys.stderr,
            )
            _capture(target, [runtime, "stop", info["Id"]], timeout=None)
            _capture(target, [runtime, "rm", info["Id"]])
        # Do not retry a name conflict by deleting anything. Concurrent prepares
        # can fail safely; rerunning prepare inspects the winner.
        _capture(target, build_container_create(target, image_id), timeout=None)
        info = inspect_container(target)
        if info is None:
            raise ConfigError("container", "container disappeared after creation")
        validate_container(target, info)
    if not info["State"].get("Running"):
        _capture(target, [target.container.runtime, "start", info["Id"]], timeout=None)
    info = _ready_container(target)
    _capture(
        target,
        [
            target.container.runtime,
            "exec",
            "--workdir",
            target.container.workdir,
            info["Id"],
            target.container.shell,
            "-c",
            "test -r . && test -w .",
        ],
    )
    return {
        "target": target.name,
        "container_name": target.container_name,
        "container_id": info["Id"],
        "image_id": info["Image"],
        "remote_root": target.remote_root,
        "status": "ready",
    }


def execute_remote(
    target: TargetConfig,
    command_args: Sequence[str],
    *,
    interactive: bool = False,
    stdin: bool = False,
    dry_run: bool = False,
) -> int:
    if not command_args:
        raise ConfigError("command", "expected a command after --")
    if dry_run:
        print(
            shlex.join(
                build_remote_exec(
                    target, command_args, interactive=interactive, stdin=stdin
                )
            )
        )
        return 0
    info = _ready_container(target)
    print(
        f"target: {target.name}; host: {target.ssh_host}; workdir: {target.container.workdir}; container: {target.container_name}",
        file=sys.stderr,
    )
    result = run_command(
        build_remote_exec(
            target,
            command_args,
            container_id=info["Id"],
            interactive=interactive,
            stdin=stdin,
        ),
        stdin=stdin or interactive,
    )
    # SSH convention: remote status unchanged; 255 is a transport failure.
    return result.returncode if result.returncode >= 0 else 128 - result.returncode
