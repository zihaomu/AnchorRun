from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from anchorrun.config import find_config, load_config
from anchorrun.errors import ConfigError
from tests.helpers import config_text, write_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = write_config(self.root)

    def load(self, text):
        self.path.write_text(text, encoding="utf-8")
        return load_config(self.path)

    def test_config_only_directory_defaults(self):
        config = load_config(self.root)
        self.assertEqual(list(self.root.iterdir()), [self.path])
        self.assertEqual(config.target().container.runtime, "docker")
        self.assertEqual(config.target().container.workdir, "/workspace")
        self.assertEqual(config.target().container.shell, "/bin/sh")
        self.assertEqual(config.to_dict()["schema_version"], 2)
        self.assertNotIn("project", config.to_dict())
        self.assertNotIn("sync", config.to_dict())

    def test_discovery_and_missing(self):
        child = self.root / "a" / "b"
        child.mkdir(parents=True)
        self.assertEqual(find_config(child), self.path)
        self.assertEqual(find_config(self.path), self.path)
        with self.assertRaises(ConfigError):
            load_config(self.root / "absent")
        self.path.unlink()
        with self.assertRaises(ConfigError):
            find_config(child)

    def test_v1_migration_is_explicit(self):
        with self.assertRaisesRegex(ConfigError, "Migrate explicitly"):
            self.load(
                "schema_version: 1\nproject: {local_root: .}\nsync: {}\nartifacts: []\n"
            )

    def test_removed_fields_and_invalid_versions(self):
        for key in ("project", "sync", "artifacts", "state_dir"):
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ConfigError, "unknown field"),
            ):
                self.load(config_text() + f"{key}: {{}}\n")
        for version in ("3", "2.0", "true", "null", "'2'"):
            with self.subTest(version=version), self.assertRaises(ConfigError):
                self.load(
                    config_text().replace(
                        "schema_version: 2", f"schema_version: {version}"
                    )
                )

    def test_tags_and_digest_supported(self):
        for image in (
            "python:3.11-slim",
            "localhost:5000/team/dev:v2",
            "team/dev@sha256:" + "a" * 64,
        ):
            self.assertEqual(
                self.load(config_text(image=image)).target().container.image, image
            )

    def test_rejects_bad_paths_hosts_images(self):
        for root in ("/", "relative", "/a/../b", "/a//b", "/a;id", "/a b", "//a"):
            with self.subTest(root=root), self.assertRaises(ConfigError):
                self.load(config_text(remote_root=root))
        for host in ("'-oProxyCommand=id'", "'lab;id'", "'lab\nid'"):
            with self.subTest(host=host), self.assertRaises(ConfigError):
                self.load(config_text().replace("gpu-lab", host))
        for image in ("--privileged", "dev;id", "dev@sha256:abcd", "'dev\nid'"):
            with self.subTest(image=image), self.assertRaises(ConfigError):
                self.load(config_text(image=image))

    def test_duplicate_unknown_and_malformed_yaml(self):
        for text in (
            config_text() + "targets: {}\n",
            config_text() + "123: x\n",
            "schema_version: 2\ntargets: {}\n",
            "schema_version: 2\ntargets: {123: {}}\n",
            "[]",
            ":",
            config_text().replace("container:", "unsupported:"),
            config_text().replace("gpu:", "'bad name':"),
        ):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                self.load(text)
        self.path.write_bytes(b"\xff")
        with self.assertRaisesRegex(ConfigError, "could not read"):
            load_config(self.path)

    def test_target_selection_and_default(self):
        two = config_text() + config_text().split("targets:\n")[1].replace(
            "gpu:", "cpu:"
        ).replace("gpu-lab", "cpu-lab")
        with self.assertRaisesRegex(ConfigError, "required when"):
            self.load(two)
        config = self.load(two + "default_target: cpu\n")
        self.assertEqual(config.target().ssh_host, "cpu-lab")
        self.assertEqual(config.target("gpu").ssh_host, "gpu-lab")
        with self.assertRaisesRegex(ConfigError, "unknown target"):
            config.target("missing")
        with self.assertRaisesRegex(ConfigError, "unknown target"):
            self.load(two + "default_target: missing\n")

    def test_entrypoint_user_and_advanced_fields(self):
        extra = """      entrypoint: /bin/bash
      shell: /bin/bash
      user: '1000:1000'
      devices: [/dev/kfd, /dev/dri]
      security_options: [seccomp=unconfined]
      environment_from_host: [HF_TOKEN]
      mounts:
        - source: /data/models
          target: /models
"""
        target = self.load(config_text() + extra).target()
        self.assertEqual(target.container.entrypoint, "/bin/bash")
        self.assertEqual(target.container.user, "1000:1000")
        self.assertTrue(target.container.mounts[0].read_only)
        for field, value in (
            ("entrypoint", "bin/bash"),
            ("shell", '"/bin/sh\\0bad"'),
            ("user", "'root;id'"),
            ("devices", "[/dev/kfd, /dev/kfd]"),
            ("devices", "'/dev/kfd'"),
            ("environment_from_host", "['TOKEN=value']"),
            ("runtime", "other"),
            ("image", "null"),
        ):
            text = config_text() + f"      {field}: {value}\n"
            if field == "image":
                text = (
                    config_text().replace("      image:", "      image_disabled:")
                    + f"      image: {value}\n"
                )
            with self.subTest(field=field), self.assertRaises(ConfigError):
                self.load(text)

    def test_mounts_cannot_shadow_workspace_or_each_other(self):
        for destinations in (
            ["/workspace"],
            ["/workspace/sub"],
            ["/models", "/models"],
            ["/models", "/models/sub"],
        ):
            text = config_text() + "      mounts:\n"
            for destination in destinations:
                text += (
                    f"        - source: /data/models\n          target: {destination}\n"
                )
            with (
                self.subTest(destinations=destinations),
                self.assertRaisesRegex(ConfigError, "overlap"),
            ):
                self.load(text)
        with self.assertRaisesRegex(ConfigError, "boolean"):
            self.load(
                config_text()
                + "      mounts: [{source: /data, target: /data, read_only: yesplease}]\n"
            )

    def test_container_identity_stable_across_local_paths_and_target_aliases(self):
        target = load_config(self.path).target()
        moved = replace(target, name="renamed", ssh_host="different-alias")
        self.assertEqual(target.container_name, moved.container_name)
        self.assertEqual(target.fingerprint, moved.fingerprint)
        changed = replace(target, container=replace(target.container, image="dev:v3"))
        self.assertEqual(target.container_name, changed.container_name)
        self.assertNotEqual(target.fingerprint, changed.fingerprint)
        other = replace(target, remote_root="/srv/another")
        self.assertNotEqual(target.container_name, other.container_name)


if __name__ == "__main__":
    unittest.main()
