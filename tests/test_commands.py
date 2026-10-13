from __future__ import annotations

import shlex
import unittest
from dataclasses import replace

from anchorrun.commands import (
    CONFIG_LABEL,
    IMAGE_LABEL,
    build_container_create,
    build_remote_exec,
)
from anchorrun.model import ContainerConfig, MountConfig, TargetConfig


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.target = TargetConfig(
            "gpu", "gpu-lab", "/srv/project", ContainerConfig("dev:v2")
        )

    def test_create_persistent_container_with_resolved_image(self):
        argv = build_container_create(self.target, "sha256:" + "a" * 64)
        self.assertEqual(argv[:2], ["docker", "create"])
        self.assertNotIn("--rm", argv)
        self.assertIn(f"{CONFIG_LABEL}={self.target.fingerprint}", argv)
        self.assertIn(f"{IMAGE_LABEL}=sha256:" + "a" * 64, argv)
        self.assertIn("type=bind,src=/srv/project,dst=/workspace", argv)
        self.assertEqual(argv[argv.index("--entrypoint") + 1], "/bin/sh")
        self.assertNotIn("dev:v2", argv)

    def test_advanced_container_options_and_entrypoint(self):
        target = replace(
            self.target,
            container=ContainerConfig(
                "dev:v2",
                runtime="podman",
                entrypoint="/bin/bash",
                user="1000",
                devices=("/dev/kfd",),
                security_options=("seccomp=unconfined",),
                mounts=(
                    MountConfig("/models", "/models"),
                    MountConfig("/cache", "/cache", False),
                ),
                environment_from_host=("HF_TOKEN",),
            ),
        )
        argv = build_container_create(target, "sha256:" + "b" * 64)
        self.assertEqual(argv[:2], ["podman", "create"])
        for arg in (
            "/bin/bash",
            "--user",
            "1000",
            "--device",
            "/dev/kfd",
            "seccomp=unconfined",
            "HF_TOKEN",
        ):
            self.assertIn(arg, argv)
        self.assertIn("type=bind,src=/models,dst=/models,readonly", argv)
        self.assertIn("type=bind,src=/cache,dst=/cache", argv)

    def test_exec_argument_boundaries_and_no_sync(self):
        payload = "a b; $(touch /tmp/not-executed)\n'quoted'"
        argv = build_remote_exec(
            self.target, ["printf", "%s", payload], container_id="container-id"
        )
        self.assertEqual(
            shlex.split(argv[-1]),
            [
                "docker",
                "exec",
                "--workdir",
                "/workspace",
                "container-id",
                "printf",
                "%s",
                payload,
            ],
        )
        self.assertIn("-T", argv)
        self.assertNotIn("rsync", argv)
        self.assertIn("BatchMode=yes", argv)

    def test_stdin_is_distinct_from_tty(self):
        stream = build_remote_exec(self.target, ["cat"], stdin=True)
        self.assertIn("-i", shlex.split(stream[-1]))
        self.assertNotIn("-t", shlex.split(stream[-1]))
        interactive = build_remote_exec(self.target, ["/bin/sh"], interactive=True)
        self.assertIn("-t", interactive)
        self.assertIn("-t", shlex.split(interactive[-1]))


if __name__ == "__main__":
    unittest.main()
