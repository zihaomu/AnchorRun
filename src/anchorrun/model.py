from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from anchorrun.errors import ConfigError


@dataclass(frozen=True)
class MountConfig:
    source: str
    target: str
    read_only: bool = True


@dataclass(frozen=True)
class ContainerConfig:
    image: str
    runtime: str = "docker"
    workdir: str = "/workspace"
    shell: str = "/bin/sh"
    entrypoint: str | None = None
    user: str | None = None
    devices: tuple[str, ...] = ()
    security_options: tuple[str, ...] = ()
    mounts: tuple[MountConfig, ...] = ()
    environment_from_host: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetConfig:
    name: str
    ssh_host: str
    remote_root: str
    container: ContainerConfig

    @property
    def workspace_id(self) -> str:
        # Host-local identity, independent of local paths and SSH alias spelling.
        return hashlib.sha256(self.remote_root.encode()).hexdigest()

    @property
    def container_name(self) -> str:
        stem = PurePosixPath(self.remote_root).name[:32]
        return f"anchorrun-{stem}-{self.workspace_id[:12]}"

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": 2,
            "remote_root": self.remote_root,
            "container": asdict(self.container),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class WorkspaceConfig:
    config_file: Path
    default_target: str
    targets: tuple[TargetConfig, ...]

    def target(self, name: str | None = None) -> TargetConfig:
        selected = name or self.default_target
        for target in self.targets:
            if target.name == selected:
                return target
        choices = ", ".join(target.name for target in self.targets)
        raise ConfigError(
            "target", f"unknown target {selected!r}; choose one of: {choices}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "config_file": str(self.config_file),
            "default_target": self.default_target,
            "targets": {
                target.name: {
                    "ssh_host": target.ssh_host,
                    "remote_root": target.remote_root,
                    "container": asdict(target.container),
                    "container_name": target.container_name,
                }
                for target in self.targets
            },
        }
