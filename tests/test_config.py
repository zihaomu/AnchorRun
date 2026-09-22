from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from anchorrun.config import find_config, load_config
from anchorrun.errors import ConfigError
from tests.helpers import IMAGE, config_text, write_config


class ConfigTests(unittest.TestCase):
    def test_loads_and_resolves_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_config(root)
            config = load_config(path)

            self.assertEqual(config.root, root.resolve())
            self.assertEqual(config.default_target, "gpu")
            self.assertEqual(config.target().container.image, IMAGE)
            self.assertEqual(config.artifacts[0].local, "artifacts/outputs")

    def test_discovers_config_from_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = write_config(root)
            descendant = root / "a" / "b"
            descendant.mkdir(parents=True)

            self.assertEqual(find_config(descendant), expected)

    def test_rejects_remote_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(config_text(remote_root="/"), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "non-root absolute POSIX path"):
                load_config(path)

    def test_rejects_shell_characters_in_remote_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(
                config_text(remote_root="/srv/work/project;touch-pwned"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "normalized non-root"):
                load_config(path)

    def test_rejects_shell_characters_in_ssh_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(
                config_text().replace("ssh_host: gpu-lab", "ssh_host: gpu-lab;id"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "simple SSH config alias"):
                load_config(path)

    def test_requires_digest_pinned_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(
                config_text(image="registry.example/dev:latest"), encoding="utf-8"
            )

            with self.assertRaisesRegex(ConfigError, "immutable image"):
                load_config(path)

    def test_rejects_option_shaped_image_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            image = "--mount=type=bind,src=/,dst=/host@sha256:" + "a" * 64
            path.write_text(config_text(image=image), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "immutable image"):
                load_config(path)

    def test_rejects_non_string_yaml_keys_without_type_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(config_text() + "123: unsupported\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "field names must be strings"):
                load_config(path)

    def test_rejects_duplicate_security_sensitive_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(
                config_text().replace(
                    "  allow_delete: false",
                    "  allow_delete: false\n  allow_delete: true",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "duplicate key 'allow_delete'"):
                load_config(path)

    def test_rejects_artifact_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(
                config_text().replace("local: artifacts/outputs", "local: ../outputs"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "inside the configuration"):
                load_config(path)

    def test_rejects_shell_characters_in_remote_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(
                config_text().replace("remote: outputs", "remote: outputs;touch-pwned"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "normalized relative path"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
