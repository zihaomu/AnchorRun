from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anchorrun.errors import ConfigError


@dataclass(frozen=True)
class SyncConfig:
    excludes: tuple[str, ...]
    allow_delete: bool


@dataclass(frozen=True)
class MountConfig:
    source: str
    target: str
    read_only: bool


@dataclass(frozen=True)
class ContainerConfig:
    runtime: str
    image: str
    workdir: str
    shell: str
    devices: tuple[str, ...]
    security_options: tuple[str, ...]
    mounts: tuple[MountConfig, ...]
    environment_from_host: tuple[str, ...]


@dataclass(frozen=True)
class TargetConfig:
    name: str
    ssh_host: str
    remote_root: str
    container: ContainerConfig


@dataclass(frozen=True)
class ArtifactConfig:
    remote: str
    local: str


@dataclass(frozen=True)
class WorkspaceConfig:
    config_file: Path
    root: Path
    local_root: Path
    state_dir: Path
    default_target: str
    sync: SyncConfig
    targets: tuple[TargetConfig, ...]
    artifacts: tuple[ArtifactConfig, ...]

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
            "schema_version": 1,
            "config_file": str(self.config_file),
            "root": str(self.root),
            "project": {
                "local_root": str(self.local_root),
                "state_dir": str(self.state_dir),
            },
            "default_target": self.default_target,
            "sync": {
                "allow_delete": self.sync.allow_delete,
                "excludes": list(self.sync.excludes),
            },
            "targets": {
                target.name: {
                    "ssh_host": target.ssh_host,
                    "remote_root": target.remote_root,
                    "container": {
                        "runtime": target.container.runtime,
                        "image": target.container.image,
                        "workdir": target.container.workdir,
                        "shell": target.container.shell,
                        "devices": list(target.container.devices),
                        "security_options": list(target.container.security_options),
                        "mounts": [
                            {
                                "source": mount.source,
                                "target": mount.target,
                                "read_only": mount.read_only,
                            }
                            for mount in target.container.mounts
                        ],
                        "environment_from_host": list(
                            target.container.environment_from_host
                        ),
                    },
                }
                for target in self.targets
            },
            "artifacts": [
                {"remote": artifact.remote, "local": artifact.local}
                for artifact in self.artifacts
            ],
        }
