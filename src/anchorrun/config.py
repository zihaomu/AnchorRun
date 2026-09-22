from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from anchorrun.errors import ConfigError
from anchorrun.model import (
    ArtifactConfig,
    ContainerConfig,
    MountConfig,
    SyncConfig,
    TargetConfig,
    WorkspaceConfig,
)

CONFIG_FILENAME = ".anchorrun.yaml"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SSH_ALIAS_RE = _NAME_RE
_IMAGE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-fA-F]{64}$"
)
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REMOTE_ABSOLUTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
_REMOTE_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_RUNTIMES = {"docker", "podman"}


class _StrictSafeLoader(yaml.SafeLoader):
    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from exc
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(path, "expected a mapping")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ConfigError(path, "expected a list")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    non_string_keys = sorted(
        (repr(key) for key in data if not isinstance(key, str)),
    )
    if non_string_keys:
        raise ConfigError(
            path,
            f"field names must be strings: {', '.join(non_string_keys)}",
        )
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(path, f"unknown field(s): {', '.join(unknown)}")


def _required_string(data: Mapping[str, Any], key: str, path: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}.{key}", "expected a non-empty string")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ConfigError(f"{path}.{key}", "contains a control character")
    return value


def _string_list(value: Any, path: str) -> tuple[str, ...]:
    result: list[str] = []
    for index, item in enumerate(_sequence(value, path)):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{path}[{index}]", "expected a non-empty string")
        if "\x00" in item or "\n" in item or "\r" in item:
            raise ConfigError(f"{path}[{index}]", "contains a control character")
        result.append(item)
    if len(result) != len(set(result)):
        raise ConfigError(path, "must not contain duplicates")
    return tuple(result)


def _local_path(root: Path, value: str, path: str) -> Path:
    supplied = Path(value)
    if supplied.is_absolute():
        raise ConfigError(path, "must be relative to the configuration directory")
    resolved = (root / supplied).resolve()
    if not resolved.is_relative_to(root):
        raise ConfigError(path, "must resolve inside the configuration directory")
    return resolved


def _remote_root(value: str, path: str) -> str:
    parsed = PurePosixPath(value)
    normalized = parsed.as_posix()
    if (
        not parsed.is_absolute()
        or value == "/"
        or "//" in value
        or ".." in parsed.parts
        or not _REMOTE_ABSOLUTE_PATH_RE.fullmatch(value)
        or normalized != value.rstrip("/")
    ):
        raise ConfigError(
            path,
            "expected a normalized non-root absolute POSIX path using only "
            "letters, digits, '.', '_', '-', and '/'",
        )
    return normalized


def _relative_remote(value: str, path: str) -> str:
    parsed = PurePosixPath(value)
    normalized = parsed.as_posix()
    if (
        parsed.is_absolute()
        or not parsed.parts
        or "//" in value
        or ".." in parsed.parts
        or any(part in {"", "."} for part in parsed.parts)
        or not _REMOTE_RELATIVE_PATH_RE.fullmatch(value)
        or normalized != value
    ):
        raise ConfigError(
            path,
            "expected a normalized relative path using only letters, digits, "
            "'.', '_', '-', and '/'",
        )
    return normalized


def _parse_mount(value: Any, path: str) -> MountConfig:
    data = _mapping(value, path)
    _reject_unknown(data, {"source", "target", "read_only"}, path)
    source = _remote_root(_required_string(data, "source", path), f"{path}.source")
    target = _remote_root(_required_string(data, "target", path), f"{path}.target")
    read_only = data.get("read_only", True)
    if not isinstance(read_only, bool):
        raise ConfigError(f"{path}.read_only", "expected a boolean")
    return MountConfig(source=source, target=target, read_only=read_only)


def _parse_container(value: Any, path: str) -> ContainerConfig:
    data = _mapping(value, path)
    _reject_unknown(
        data,
        {
            "runtime",
            "image",
            "workdir",
            "shell",
            "devices",
            "security_options",
            "mounts",
            "environment_from_host",
        },
        path,
    )
    runtime = _required_string(data, "runtime", path)
    if runtime not in _RUNTIMES:
        raise ConfigError(f"{path}.runtime", "expected docker or podman")
    image = _required_string(data, "image", path)
    if not _IMAGE_RE.fullmatch(image):
        raise ConfigError(
            f"{path}.image",
            "expected an immutable image ending in @sha256:<64 hex characters>",
        )
    workdir = _remote_root(_required_string(data, "workdir", path), f"{path}.workdir")
    shell = data.get("shell", "/bin/bash")
    if not isinstance(shell, str) or not PurePosixPath(shell).is_absolute():
        raise ConfigError(f"{path}.shell", "expected an absolute container path")

    devices = _string_list(data.get("devices", []), f"{path}.devices")
    for index, device in enumerate(devices):
        _remote_root(device, f"{path}.devices[{index}]")

    environment = _string_list(
        data.get("environment_from_host", []), f"{path}.environment_from_host"
    )
    for index, name in enumerate(environment):
        if not _ENV_RE.fullmatch(name):
            raise ConfigError(
                f"{path}.environment_from_host[{index}]",
                "expected an environment variable name",
            )

    mounts = tuple(
        _parse_mount(item, f"{path}.mounts[{index}]")
        for index, item in enumerate(
            _sequence(data.get("mounts", []), f"{path}.mounts")
        )
    )
    return ContainerConfig(
        runtime=runtime,
        image=image,
        workdir=workdir,
        shell=shell,
        devices=devices,
        security_options=_string_list(
            data.get("security_options", []), f"{path}.security_options"
        ),
        mounts=mounts,
        environment_from_host=environment,
    )


def _parse_target(name: str, value: Any) -> TargetConfig:
    path = f"targets.{name}"
    if not _NAME_RE.fullmatch(name):
        raise ConfigError(path, "target name contains unsupported characters")
    data = _mapping(value, path)
    _reject_unknown(data, {"ssh_host", "remote_root", "container"}, path)
    ssh_host = _required_string(data, "ssh_host", path)
    if not _SSH_ALIAS_RE.fullmatch(ssh_host):
        raise ConfigError(
            f"{path}.ssh_host",
            "expected a simple SSH config alias without options or shell characters",
        )
    return TargetConfig(
        name=name,
        ssh_host=ssh_host,
        remote_root=_remote_root(
            _required_string(data, "remote_root", path), f"{path}.remote_root"
        ),
        container=_parse_container(data.get("container"), f"{path}.container"),
    )


def _parse_artifact(value: Any, index: int, local_root: Path) -> ArtifactConfig:
    path = f"artifacts[{index}]"
    data = _mapping(value, path)
    _reject_unknown(data, {"remote", "local"}, path)
    remote = _relative_remote(_required_string(data, "remote", path), f"{path}.remote")
    local_raw = _required_string(data, "local", path)
    local_path = _local_path(local_root, local_raw, f"{path}.local")
    return ArtifactConfig(
        remote=remote,
        local=local_path.relative_to(local_root).as_posix(),
    )


def find_config(start: Path | None = None) -> Path:
    cursor = (start or Path.cwd()).resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for directory in (cursor, *cursor.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    raise ConfigError("workspace", f"could not find {CONFIG_FILENAME} from {cursor}")


def load_config(explicit: Path | str | None = None) -> WorkspaceConfig:
    if explicit is None:
        config_file = find_config()
    else:
        supplied = Path(explicit).expanduser().resolve()
        config_file = supplied / CONFIG_FILENAME if supplied.is_dir() else supplied
        if not config_file.is_file():
            raise ConfigError(
                "workspace", f"configuration does not exist: {config_file}"
            )

    try:
        payload = yaml.load(
            config_file.read_text(encoding="utf-8"),
            Loader=_StrictSafeLoader,
        )
    except yaml.YAMLError as exc:
        raise ConfigError("workspace", f"invalid YAML: {exc}") from exc

    root = config_file.parent.resolve()
    data = _mapping(payload, "workspace")
    _reject_unknown(
        data,
        {"schema_version", "project", "default_target", "sync", "targets", "artifacts"},
        "workspace",
    )
    if data.get("schema_version") != 1:
        raise ConfigError("workspace.schema_version", "expected 1")

    project = _mapping(data.get("project"), "project")
    _reject_unknown(project, {"local_root", "state_dir"}, "project")
    local_root = _local_path(
        root,
        _required_string(project, "local_root", "project"),
        "project.local_root",
    )
    state_dir = _local_path(
        root,
        _required_string(project, "state_dir", "project"),
        "project.state_dir",
    )

    sync_data = _mapping(data.get("sync", {}), "sync")
    _reject_unknown(sync_data, {"excludes", "allow_delete"}, "sync")
    allow_delete = sync_data.get("allow_delete", False)
    if not isinstance(allow_delete, bool):
        raise ConfigError("sync.allow_delete", "expected a boolean")
    sync = SyncConfig(
        excludes=_string_list(sync_data.get("excludes", []), "sync.excludes"),
        allow_delete=allow_delete,
    )

    target_data = _mapping(data.get("targets"), "targets")
    if not target_data:
        raise ConfigError("targets", "must contain at least one target")
    non_string_targets = sorted(
        (repr(name) for name in target_data if not isinstance(name, str)),
    )
    if non_string_targets:
        raise ConfigError(
            "targets",
            f"target names must be strings: {', '.join(non_string_targets)}",
        )
    targets = tuple(
        _parse_target(name, value) for name, value in target_data.items()
    )

    default_target = data.get("default_target")
    if default_target is None and len(targets) == 1:
        default_target = targets[0].name
    if not isinstance(default_target, str) or not default_target:
        raise ConfigError(
            "default_target",
            "required when more than one target is configured",
        )
    if default_target not in {target.name for target in targets}:
        raise ConfigError("default_target", f"unknown target {default_target!r}")

    artifacts = tuple(
        _parse_artifact(item, index, local_root)
        for index, item in enumerate(_sequence(data.get("artifacts", []), "artifacts"))
    )
    local_destinations = [artifact.local for artifact in artifacts]
    if len(local_destinations) != len(set(local_destinations)):
        raise ConfigError("artifacts", "local destinations must be unique")

    return WorkspaceConfig(
        config_file=config_file,
        root=root,
        local_root=local_root,
        state_dir=state_dir,
        default_target=default_target,
        sync=sync,
        targets=targets,
        artifacts=artifacts,
    )
