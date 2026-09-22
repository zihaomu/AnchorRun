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

    def test_requires_digest_pinned_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".anchorrun.yaml"
            path.write_text(
                config_text(image="registry.example/dev:latest"), encoding="utf-8"
            )

            with self.assertRaisesRegex(ConfigError, "immutable image"):
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


if __name__ == "__main__":
    unittest.main()
