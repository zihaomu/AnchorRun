from __future__ import annotations

from pathlib import Path

IMAGE = "registry.example/dev@sha256:" + "a" * 64


def config_text(*, remote_root: str = "/srv/work/project", image: str = IMAGE) -> str:
    return f"""schema_version: 2
targets:
  gpu:
    ssh_host: gpu-lab
    remote_root: {remote_root}
    container:
      image: {image}
"""


def write_config(directory: Path, **kwargs: str) -> Path:
    path = directory / ".anchorrun.yaml"
    path.write_text(config_text(**kwargs), encoding="utf-8")
    return path


def container_info(target, *, running=True):
    from anchorrun.commands import CONFIG_LABEL, IMAGE_LABEL, OWNER_LABEL

    image_id = "sha256:" + "b" * 64
    return {
        "Id": "c" * 64,
        "Image": image_id,
        "Config": {
            "Labels": {
                OWNER_LABEL: target.workspace_id,
                CONFIG_LABEL: target.fingerprint,
                IMAGE_LABEL: image_id,
            }
        },
        "State": {"Running": running},
    }
