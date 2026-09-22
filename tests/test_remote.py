from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from anchorrun.config import load_config
from anchorrun.errors import CommandError, CommandStartError, ConfigError
from anchorrun.remote import (
    RemoteProbe,
    execute_remote,
    local_issues,
    probe_target,
    pull_artifacts,
    run_command,
    sync_workspace,
)
from tests.helpers import write_config


class RemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = load_config(write_config(self.root))
        self.target = self.config.target()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_probe_ready_and_serialization(self) -> None:
        with patch("anchorrun.remote.subprocess.run") as run:
            run.return_value = Mock(
                returncode=0,
                stdout="user=alice\nruntime=yes\nimage=yes\npath=yes\n",
                stderr="",
            )

            probe = probe_target(self.target, timeout_seconds=7)

        self.assertTrue(probe.ready)
        self.assertEqual(probe.user, "alice")
        self.assertEqual(probe.to_dict()["ready"], True)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_probe_reports_timeout_without_raising(self) -> None:
        with patch(
            "anchorrun.remote.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["ssh"], 3),
        ):
            probe = probe_target(self.target, timeout_seconds=3)

        self.assertFalse(probe.reachable)
        self.assertIn("timed out", probe.message)

    def test_probe_reports_missing_ssh_without_traceback(self) -> None:
        with patch(
            "anchorrun.remote.subprocess.run",
            side_effect=FileNotFoundError("ssh is unavailable"),
        ):
            probe = probe_target(self.target)

        self.assertFalse(probe.reachable)
        self.assertIn("could not start", probe.message)

    def test_probe_reports_missing_remote_requirements(self) -> None:
        with patch("anchorrun.remote.subprocess.run") as run:
            run.return_value = Mock(
                returncode=0,
                stdout="user=alice\nruntime=no\nimage=no\npath=no\n",
                stderr="",
            )

            probe = probe_target(self.target)

        self.assertFalse(probe.ready)
        self.assertIn("docker is unavailable", probe.message)
        self.assertIn("image digest", probe.message)
        self.assertIn("not writable", probe.message)

    def test_run_command_honors_dry_run_and_reports_failure(self) -> None:
        with patch("anchorrun.remote.subprocess.run") as run:
            run_command(["false"], name="test", dry_run=True)
            run.assert_not_called()

            run.return_value = Mock(returncode=9)
            with self.assertRaisesRegex(CommandError, "exit code 9"):
                run_command(["false"], name="test")

    def test_run_command_converts_start_failure_to_user_facing_error(self) -> None:
        with (
            patch(
                "anchorrun.remote.subprocess.run",
                side_effect=FileNotFoundError("rsync is unavailable"),
            ),
            self.assertRaisesRegex(CommandStartError, "could not start"),
        ):
            run_command(["rsync"], name="workspace synchronization")

    def test_local_issues_reports_missing_root_and_tools(self) -> None:
        missing_config = self.config.__class__(
            **{**self.config.__dict__, "local_root": self.root / "missing"}
        )
        with patch("anchorrun.remote.shutil.which", return_value=None):
            issues = local_issues(missing_config)

        self.assertEqual(len(issues), 3)
        self.assertIn("does not exist", issues[0])

    def test_sync_runs_mkdir_before_rsync(self) -> None:
        with patch("anchorrun.remote.run_command") as run:
            sync_workspace(self.config, self.target)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].kwargs["name"], "remote workspace creation")
        self.assertEqual(run.call_args_list[1].kwargs["name"], "workspace synchronization")

    def test_execute_rejects_empty_command_before_subprocess(self) -> None:
        with (
            patch("anchorrun.remote.run_command") as run,
            self.assertRaisesRegex(ConfigError, "expected a command"),
        ):
            execute_remote(self.target, [])
        run.assert_not_called()

    def test_pull_creates_destination_and_runs_rsync(self) -> None:
        with patch("anchorrun.remote.run_command") as run:
            pull_artifacts(self.config, self.target)

        destination = self.root / "artifacts" / "outputs"
        self.assertTrue(destination.is_dir())
        self.assertEqual(
            run.call_args,
            call(
                unittest.mock.ANY,
                name="artifact pull (outputs)",
                dry_run=False,
            ),
        )

    def test_remote_probe_ready_requires_all_checks(self) -> None:
        probe = RemoteProbe(
            target="gpu",
            ssh_host="gpu-lab",
            reachable=True,
            runtime_available=True,
            image_present=True,
            remote_path_writable=False,
            user="alice",
            message="not ready",
        )

        self.assertFalse(probe.ready)


if __name__ == "__main__":
    unittest.main()
