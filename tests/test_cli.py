from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from anchorrun.cli import main
from anchorrun.errors import CommandError
from tests.helpers import write_config


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = write_config(self.root)
        self.prefix = ["--config", str(self.config)]

    def test_show_no_connection(self):
        output = io.StringIO()
        with patch("anchorrun.remote.run_command") as run, redirect_stdout(output):
            self.assertEqual(main(self.prefix + ["show"]), 0)
        run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["selected_target"], "gpu")

    def test_exec_stream_and_exit_status(self):
        for code in (0, 9, 255):
            with patch("anchorrun.cli.execute_remote", return_value=code) as execute:
                self.assertEqual(
                    main(self.prefix + ["exec", "--stdin", "--", "cat"]), code
                )
            self.assertEqual(execute.call_args.args[1], ["cat"])
            self.assertTrue(execute.call_args.kwargs["stdin"])

    def test_exec_without_command_or_unknown_target(self):
        with patch("anchorrun.remote.run_command") as run:
            self.assertEqual(main(self.prefix + ["exec"]), 2)
            self.assertEqual(
                main(self.prefix + ["exec", "--target", "absent", "--", "true"]), 2
            )
        run.assert_not_called()

    def test_v1_fails_before_any_ssh(self):
        self.config.write_text("schema_version: 1\n", encoding="utf-8")
        with patch("anchorrun.remote.run_command") as run:
            self.assertEqual(main(self.prefix + ["exec", "--", "true"]), 2)
        run.assert_not_called()

    def test_removed_commands_and_flags_rejected(self):
        for arguments in (
            ["sync"],
            ["pull"],
            ["exec", "--no-sync"],
            ["doctor", "--remote"],
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(SystemExit) as caught,
            ):
                main(self.prefix + arguments)
            self.assertEqual(caught.exception.code, 2)

    def test_doctor_remote_default_and_local_only_scope(self):
        output = io.StringIO()
        with (
            patch("anchorrun.cli.local_issues", return_value=[]),
            patch("anchorrun.cli.probe_target", return_value={"ready": True}) as probe,
            redirect_stdout(output),
        ):
            self.assertEqual(
                main(self.prefix + ["doctor", "--json", "--timeout", "5"]), 0
            )
        self.assertEqual(probe.call_args.kwargs["timeout"], 5)
        output = io.StringIO()
        with (
            patch("anchorrun.cli.local_issues", return_value=[]),
            patch("anchorrun.cli.probe_target") as probe,
            redirect_stdout(output),
        ):
            self.assertEqual(main(self.prefix + ["doctor", "--local", "--json"]), 0)
        probe.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "valid")

    def test_doctor_failures(self):
        with (
            patch("anchorrun.cli.local_issues", return_value=[]),
            patch(
                "anchorrun.cli.probe_target",
                return_value={"ready": False, "target": "gpu", "message": "missing"},
            ),
        ):
            self.assertEqual(main(self.prefix + ["doctor"]), 1)
        with (
            patch("anchorrun.cli.local_issues", return_value=["ssh missing"]),
            patch("anchorrun.cli.probe_target") as probe,
        ):
            self.assertEqual(main(self.prefix + ["doctor"]), 1)
        probe.assert_not_called()

    def test_prepare_recreate_and_shell_dispatch(self):
        with patch("anchorrun.cli.prepare_target", return_value=None) as prepare:
            self.assertEqual(
                main(self.prefix + ["prepare", "--recreate", "--dry-run"]), 0
            )
        self.assertEqual(prepare.call_args.kwargs, {"recreate": True, "dry_run": True})
        with patch("anchorrun.cli.execute_remote", return_value=0) as execute:
            self.assertEqual(main(self.prefix + ["shell"]), 0)
        self.assertEqual(execute.call_args.args[1], ["/bin/sh"])
        self.assertTrue(execute.call_args.kwargs["interactive"])

    def test_transport_and_interrupt_status(self):
        with patch(
            "anchorrun.cli.prepare_target", side_effect=CommandError("ssh", 255)
        ):
            self.assertEqual(main(self.prefix + ["prepare"]), 255)
        with patch("anchorrun.cli.prepare_target", side_effect=KeyboardInterrupt):
            self.assertEqual(main(self.prefix + ["prepare"]), 130)


if __name__ == "__main__":
    unittest.main()
