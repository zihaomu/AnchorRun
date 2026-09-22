from __future__ import annotations

from pathlib import Path

IMAGE = "registry.example/dev@sha256:" + "a" * 64


def config_text(*, remote_root: str = "/srv/work/project", image: str = IMAGE) -> str:
    return f"""\
schema_version: 1
project:
  local_root: .
  state_dir: .anchorrun
default_target: gpu
sync:
  allow_delete: false
  excludes: [.git/, .anchorrun/]
targets:
  gpu:
    ssh_host: gpu-lab
    remote_root: {remote_root}
    container:
      runtime: docker
      image: {image}
      workdir: /workspace
      devices: [/dev/kfd]
      security_options: [seccomp=unconfined]
      mounts: []
      environment_from_host: [HF_TOKEN]
artifacts:
  - remote: outputs
    local: artifacts/outputs
"""


def write_config(directory: Path, **kwargs: str) -> Path:
    path = directory / ".anchorrun.yaml"
    path.write_text(config_text(**kwargs), encoding="utf-8")
    return path
