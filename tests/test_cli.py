from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anchorrun.cli import main
from tests.helpers import write_config


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_path = write_config(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_show_succeeds(self) -> None:
        with patch("builtins.print") as output:
            result = main(["--config", str(self.config_path), "show"])

        self.assertEqual(result, 0)
        self.assertIn('"default_target": "gpu"', output.call_args.args[0])

    def test_exec_without_command_does_not_sync(self) -> None:
        with patch("anchorrun.cli.sync_workspace") as sync:
            result = main(["--config", str(self.config_path), "exec"])

        self.assertEqual(result, 2)
        sync.assert_not_called()

    def test_exec_no_sync_dispatches_command(self) -> None:
        with (
            patch("anchorrun.cli.sync_workspace") as sync,
            patch("anchorrun.cli.execute_remote") as execute,
        ):
            result = main(
                [
                    "--config",
                    str(self.config_path),
                    "exec",
                    "--no-sync",
                    "--",
                    "python",
                    "-V",
                ]
            )

        self.assertEqual(result, 0)
        sync.assert_not_called()
        self.assertEqual(execute.call_args.args[1], ["python", "-V"])

    def test_doctor_dispatches_remote_probe(self) -> None:
        with (
            patch("anchorrun.cli.local_issues", return_value=[]),
            patch("anchorrun.cli.probe_target") as probe,
        ):
            probe.return_value.ready = True
            probe.return_value.target = "gpu"
            probe.return_value.message = "ready"
            result = main(
                [
                    "--config",
                    str(self.config_path),
                    "doctor",
                    "--remote",
                    "--timeout",
                    "5",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(probe.call_args.kwargs["timeout_seconds"], 5)

    def test_config_error_returns_two(self) -> None:
        result = main(["--config", str(self.root / "missing.yaml"), "show"])

        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
