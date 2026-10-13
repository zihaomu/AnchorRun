from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from anchorrun.commands import CONFIG_LABEL, IMAGE_LABEL, OWNER_LABEL
from anchorrun.errors import CommandError, CommandStartError, ConfigError
from anchorrun.model import ContainerConfig, TargetConfig
from anchorrun.remote import (
    execute_remote,
    inspect_container,
    local_issues,
    prepare_target,
    probe_target,
    run_command,
)
from tests.helpers import container_info


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.target = TargetConfig(
            "gpu", "gpu-lab", "/srv/project", ContainerConfig("dev:v2")
        )
        self.info = container_info(self.target)

    def test_inspect_absent_and_malformed(self):
        with patch("anchorrun.remote._capture", return_value=""):
            self.assertIsNone(inspect_container(self.target))
        for raw in ("oops", "[]", "[{}]", "null", '{"a":1}'):
            with (
                self.subTest(raw=raw),
                patch("anchorrun.remote._capture", side_effect=["id", raw]),
                self.assertRaises(ConfigError),
            ):
                inspect_container(self.target)
        with patch(
            "anchorrun.remote._capture", side_effect=["id", json.dumps([self.info])]
        ):
            self.assertEqual(inspect_container(self.target)["Id"], self.info["Id"])

    def test_prepare_reuses_running_container_without_pull_or_create(self):
        with (
            patch("anchorrun.remote.inspect_container", return_value=self.info),
            patch("anchorrun.remote._capture", return_value="") as capture,
        ):
            result = prepare_target(self.target)
        self.assertEqual(result["container_id"], self.info["Id"])
        verbs = [call.args[1][1] for call in capture.call_args_list]
        self.assertNotIn("pull", verbs)
        self.assertNotIn("create", verbs)
        self.assertNotIn("start", verbs)

    def test_prepare_starts_stopped_container(self):
        stopped = container_info(self.target, running=False)
        with (
            patch(
                "anchorrun.remote.inspect_container", side_effect=[stopped, self.info]
            ),
            patch("anchorrun.remote._capture", return_value="") as capture,
        ):
            prepare_target(self.target)
        self.assertIn(
            ["docker", "start", self.info["Id"]],
            [call.args[1] for call in capture.call_args_list],
        )

    def test_prepare_creates_by_image_id_and_pulls_only_when_absent(self):
        for images in ("", "existing"):
            with (
                self.subTest(images=images),
                patch(
                    "anchorrun.remote.inspect_container",
                    side_effect=[None, self.info, self.info],
                ),
                patch("anchorrun.remote._capture") as capture,
                patch(
                    "anchorrun.remote.run_command",
                    return_value=Mock(
                        returncode=0 if images else 1,
                        stdout=self.info["Image"],
                        stderr="No such image",
                    ),
                ),
            ):

                def response(target, command, images=images, **kwargs):
                    if command[1:3] == ["image", "ls"]:
                        return images
                    if command[1:3] == ["image", "inspect"]:
                        return self.info["Image"]
                    return ""

                capture.side_effect = response
                result = prepare_target(self.target)
                commands = [call.args[1] for call in capture.call_args_list]
                self.assertEqual(
                    any(cmd[1] == "pull" for cmd in commands), not bool(images)
                )
                created = next(cmd for cmd in commands if cmd[1] == "create")
                self.assertIn(self.info["Image"], created)
                self.assertEqual(result["status"], "ready")

    def test_foreign_container_never_used_or_removed_even_with_recreate(self):
        foreign = deepcopy(self.info)
        foreign["Config"]["Labels"][OWNER_LABEL] = "someone-else"
        for recreate in (False, True):
            with (
                patch("anchorrun.remote.inspect_container", return_value=foreign),
                patch("anchorrun.remote._capture") as capture,
                self.assertRaisesRegex(ConfigError, "not owned"),
            ):
                prepare_target(self.target, recreate=recreate)
            capture.assert_not_called()
        with (
            patch("anchorrun.remote.inspect_container", return_value=foreign),
            patch("anchorrun.remote.run_command") as run,
            self.assertRaises(ConfigError),
        ):
            execute_remote(self.target, ["true"])
        run.assert_not_called()

    def test_config_and_image_mismatch_require_explicit_action(self):
        for label in (CONFIG_LABEL, IMAGE_LABEL):
            info = deepcopy(self.info)
            info["Config"]["Labels"][label] = "different"
            with (
                self.subTest(label=label),
                patch("anchorrun.remote.inspect_container", return_value=info),
                patch("anchorrun.remote._capture") as capture,
                self.assertRaises(ConfigError),
            ):
                prepare_target(self.target)
            capture.assert_not_called()

    def test_recreate_targets_inspected_id_and_resolves_image_before_removal(self):
        old = deepcopy(self.info)
        old["Id"] = "old-id"
        old["Config"]["Labels"][CONFIG_LABEL] = "old-config"
        with (
            patch(
                "anchorrun.remote.inspect_container",
                side_effect=[old, self.info, self.info],
            ),
            patch("anchorrun.remote._capture") as capture,
            patch(
                "anchorrun.remote.run_command",
                return_value=Mock(returncode=1, stderr="No such image"),
            ),
        ):
            capture.side_effect = lambda target, cmd, **kwargs: (
                self.info["Image"] if cmd[1:3] == ["image", "inspect"] else "present"
            )
            prepare_target(self.target, recreate=True)
        commands = [call.args[1] for call in capture.call_args_list]
        self.assertIn(["docker", "stop", "old-id"], commands)
        self.assertIn(["docker", "rm", "old-id"], commands)
        resolve = next(
            i for i, cmd in enumerate(commands) if cmd[1:3] == ["image", "inspect"]
        )
        remove = commands.index(["docker", "rm", "old-id"])
        self.assertLess(resolve, remove)

    def test_recreate_validation_failure_preserves_old_container(self):
        with (
            patch("anchorrun.remote.inspect_container", return_value=self.info),
            patch(
                "anchorrun.remote._capture", side_effect=CommandError("paths", 1)
            ) as capture,
            self.assertRaises(CommandError),
        ):
            prepare_target(self.target, recreate=True)
        self.assertEqual(capture.call_count, 1)

    def test_daemon_error_does_not_create_or_pull(self):
        with (
            patch(
                "anchorrun.remote._capture", side_effect=CommandError("daemon", 125)
            ) as capture,
            self.assertRaises(CommandError),
        ):
            prepare_target(self.target)
        self.assertEqual(capture.call_count, 1)

    def test_dry_runs_do_not_connect(self):
        with patch("anchorrun.remote.run_command") as run, patch("builtins.print"):
            prepare_target(self.target, dry_run=True)
            self.assertEqual(
                execute_remote(self.target, ["echo", "hi"], dry_run=True), 0
            )
        run.assert_not_called()

    def test_empty_missing_stopped_and_paused_exec_fail(self):
        paused = deepcopy(self.info)
        paused["State"]["Paused"] = True
        for info in (None, container_info(self.target, running=False), paused):
            with (
                patch("anchorrun.remote.inspect_container", return_value=info),
                patch("anchorrun.remote.run_command") as run,
                self.assertRaises(ConfigError),
            ):
                execute_remote(self.target, ["true"])
            run.assert_not_called()
        with self.assertRaises(ConfigError):
            execute_remote(self.target, [])

    def test_exec_exit_codes_and_input_routing(self):
        for code in (0, 7, 42, 125, 255, -2):
            with (
                patch("anchorrun.remote.inspect_container", return_value=self.info),
                patch(
                    "anchorrun.remote.run_command", return_value=Mock(returncode=code)
                ) as run,
            ):
                result = execute_remote(self.target, ["cat"], stdin=True)
            self.assertEqual(result, code if code >= 0 else 130)
            self.assertTrue(run.call_args.kwargs["stdin"])
            self.assertIn(self.info["Id"], run.call_args.args[0][-1])

    def test_probe_readiness_and_no_mutations(self):
        with (
            patch("anchorrun.remote.inspect_container", return_value=self.info),
            patch("anchorrun.remote._capture", return_value="") as capture,
        ):
            result = probe_target(self.target, timeout=3)
        self.assertTrue(result["ready"])
        self.assertEqual(result["image_id"], self.info["Image"])
        self.assertNotIn("mkdir", capture.call_args_list[0].args[1][-1])
        with patch(
            "anchorrun.remote._capture", side_effect=CommandStartError("ssh", "timeout")
        ):
            result = probe_target(self.target)
        self.assertFalse(result["ready"])
        self.assertIn("timeout", result["message"])

    def test_run_command_passes_streams_and_handles_transport(self):
        with patch(
            "anchorrun.remote.subprocess.run", return_value=Mock(returncode=0)
        ) as run:
            run_command(["ssh"], stdin=True)
        self.assertIsNone(run.call_args.kwargs["stdin"])
        self.assertFalse(run.call_args.kwargs["text"])
        self.assertFalse(run.call_args.kwargs["capture_output"])
        for error in (FileNotFoundError("ssh"), subprocess.TimeoutExpired("ssh", 3)):
            with (
                patch("anchorrun.remote.subprocess.run", side_effect=error),
                self.assertRaises(CommandStartError),
            ):
                run_command(["ssh"], capture=True)
        with (
            patch(
                "anchorrun.remote.subprocess.run",
                return_value=Mock(returncode=255, stderr="denied"),
            ),
            self.assertRaises(CommandError) as caught,
        ):
            run_command(["ssh"], capture=True)
        self.assertEqual(caught.exception.returncode, 255)

    def test_only_ssh_required_locally(self):
        with patch("anchorrun.remote.shutil.which", return_value="/bin/ssh") as which:
            self.assertEqual(local_issues(), [])
        which.assert_called_once_with("ssh")
        with patch("anchorrun.remote.shutil.which", return_value=None):
            self.assertEqual(len(local_issues()), 1)


if __name__ == "__main__":
    unittest.main()
