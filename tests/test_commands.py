from __future__ import annotations

import shlex
import tempfile
import unittest
from pathlib import Path

from anchorrun.commands import (
    build_prepare_command,
    build_pull_command,
    build_remote_doctor_script,
    build_remote_exec,
    build_sync_command,
)
from anchorrun.config import load_config
from anchorrun.errors import ConfigError
from tests.helpers import write_config


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = load_config(write_config(self.root))
        self.target = self.config.target()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sync_is_push_only_and_has_no_delete_by_default(self) -> None:
        command = build_sync_command(self.config, self.target)

        self.assertEqual(command[0], "rsync")
        self.assertNotIn("--delete", command)
        self.assertEqual(command[-2], f"{self.root}/")
        self.assertEqual(command[-1], "gpu-lab:/srv/work/project/")

    def test_delete_requires_config_and_cli_gate(self) -> None:
        with self.assertRaisesRegex(ConfigError, "remote deletion is disabled"):
            build_sync_command(self.config, self.target, delete=True)

    def test_remote_exec_quotes_each_argument(self) -> None:
        command = build_remote_exec(
            self.target,
            ["python", "-c", "print('hello world')"],
        )

        self.assertEqual(command[:2], ["ssh", "gpu-lab"])
        parsed = shlex.split(command[-1])
        self.assertEqual(parsed[-3:], ["python", "-c", "print('hello world')"])
        self.assertIn("/srv/work/project:/workspace", parsed)

    def test_pull_has_explicit_remote_and_local_roots(self) -> None:
        command, destination = build_pull_command(
            self.config,
            self.target,
            self.config.artifacts[0],
        )

        self.assertEqual(command[-2], "gpu-lab:/srv/work/project/outputs/")
        self.assertEqual(command[-1], f"{self.root}/artifacts/outputs/")
        self.assertEqual(destination, self.root / "artifacts" / "outputs")

    def test_doctor_walks_to_an_existing_parent_without_mutation(self) -> None:
        script = build_remote_doctor_script(self.target)

        self.assertIn('while [ ! -e "$probe" ]', script)
        self.assertNotIn("mkdir", script)

    def test_prepare_is_explicit_and_uses_the_pinned_image(self) -> None:
        command = build_prepare_command(self.target)

        self.assertEqual(command[:2], ["ssh", "gpu-lab"])
        self.assertIn("mkdir -p -- /srv/work/project", command[-1])
        self.assertIn(self.target.container.image, command[-1])
        self.assertIn("docker pull", command[-1])


if __name__ == "__main__":
    unittest.main()
