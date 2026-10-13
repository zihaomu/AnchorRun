from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from anchorrun.cli import main
from anchorrun.errors import CommandError, CommandStartError, ConfigError
from anchorrun.model import ContainerConfig, TargetConfig
from anchorrun.remote import (
    _resolve_image,
    execute_remote,
    inspect_container,
    prepare_target,
    probe_target,
)
from tests.helpers import container_info, write_config


class LifecycleEdgeTests(unittest.TestCase):
    def setUp(self):
        self.target = TargetConfig(
            "gpu", "gpu-lab", "/srv/project", ContainerConfig("dev:v2")
        )
        self.info = container_info(self.target)
        transport = patch(
            "anchorrun.remote.run_command",
            side_effect=AssertionError("unit test attempted a real remote operation"),
        )
        transport.start()
        self.addCleanup(transport.stop)

    def test_malformed_inspect_fields_are_user_facing_errors(self):
        cases = []
        for labels in ([], ["invalid"], "invalid", True):
            info = deepcopy(self.info)
            info["Config"]["Labels"] = labels
            cases.append((f"labels={labels!r}", info))
        for image in (None, "", [], 123):
            info = deepcopy(self.info)
            info["Image"] = image
            cases.append((f"image={image!r}", info))
        for field in ("Running", "Paused", "Restarting"):
            for value in ("false", 1, [], None):
                info = deepcopy(self.info)
                info["State"][field] = value
                cases.append((f"{field}={value!r}", info))
        info = deepcopy(self.info)
        del info["State"]["Running"]
        cases.append(("missing Running", info))
        for name, info in cases:
            with (
                self.subTest(name=name),
                patch(
                    "anchorrun.remote._capture",
                    side_effect=["existing-id", json.dumps([info])],
                ),
                self.assertRaises(ConfigError),
            ):
                inspect_container(self.target)

    def test_failed_image_resolution_never_removes_existing_container(self):
        for failed_step in ("initial-inspect", "pull", "inspect", "invalid-id"):
            calls = []

            def capture(
                target, command, calls=calls, failed_step=failed_step, **kwargs
            ):
                calls.append(command)
                if command[1] == "pull" and failed_step == "pull":
                    raise CommandError("image pull", 1)
                if command[1:3] == ["image", "inspect"]:
                    if failed_step == "inspect":
                        raise CommandError("image inspect", 1)
                    return "invalid-image-id"
                return ""

            with (
                self.subTest(failed_step=failed_step),
                patch("anchorrun.remote.inspect_container", return_value=self.info),
                patch("anchorrun.remote._capture", side_effect=capture),
                patch(
                    "anchorrun.remote.run_command",
                    return_value=Mock(
                        returncode=125 if failed_step == "initial-inspect" else 1,
                        stderr="permission denied"
                        if failed_step == "initial-inspect"
                        else "No such image",
                        stdout="",
                    ),
                ),
                redirect_stderr(io.StringIO()),
                self.assertRaises((CommandError, ConfigError)),
            ):
                prepare_target(self.target, recreate=True)
            self.assertFalse(
                any(command[1] in ("stop", "rm", "create") for command in calls)
            )

    def test_create_name_conflict_does_not_remove_a_concurrent_container(self):
        calls = []

        def capture(target, command, **kwargs):
            calls.append(command)
            if command[1:3] == ["image", "inspect"]:
                return self.info["Image"]
            if command[1] == "create":
                raise CommandError("container name conflict", 125)
            return "present"

        with (
            patch("anchorrun.remote.inspect_container", return_value=None),
            patch("anchorrun.remote._capture", side_effect=capture),
            patch("anchorrun.remote._resolve_image", return_value=self.info["Image"]),
            self.assertRaises(CommandError),
        ):
            prepare_target(self.target)
        self.assertFalse(any(command[1] in ("stop", "rm") for command in calls))

    def test_disappeared_container_after_create_fails_without_start_or_retry(self):
        with (
            patch("anchorrun.remote.inspect_container", side_effect=[None, None]),
            patch("anchorrun.remote._capture") as capture,
            patch("anchorrun.remote._resolve_image", return_value=self.info["Image"]),
            self.assertRaisesRegex(ConfigError, "disappeared"),
        ):
            capture.side_effect = lambda target, command, **kwargs: (
                self.info["Image"]
                if command[1:3] == ["image", "inspect"]
                else "present"
            )
            prepare_target(self.target)
        commands = [call.args[1] for call in capture.call_args_list]
        self.assertEqual(sum(command[1] == "create" for command in commands), 1)
        self.assertFalse(any(command[1] in ("start", "rm") for command in commands))

    def test_stop_failure_prevents_removal(self):
        calls = []

        def capture(target, command, **kwargs):
            calls.append(command)
            if command[1:3] == ["image", "inspect"]:
                return self.info["Image"]
            if command[1] == "stop":
                raise CommandError("container stop", 1)
            return "present"

        with (
            patch("anchorrun.remote.inspect_container", return_value=self.info),
            patch("anchorrun.remote._capture", side_effect=capture),
            patch("anchorrun.remote._resolve_image", return_value=self.info["Image"]),
            redirect_stderr(io.StringIO()),
            self.assertRaises(CommandError),
        ):
            prepare_target(self.target, recreate=True)
        self.assertFalse(any(command[1] in ("rm", "create") for command in calls))

    def test_missing_runtime_is_not_reported_as_missing_container(self):
        with (
            patch(
                "anchorrun.remote._capture",
                side_effect=["", CommandError("docker not found", 127)],
            ) as capture,
        ):
            result = probe_target(self.target)
        self.assertFalse(result["ready"])
        self.assertIn("127", result["message"])
        self.assertEqual(capture.call_count, 2)

    def test_restart_in_progress_never_runs_the_requested_command(self):
        info = deepcopy(self.info)
        info["State"]["Restarting"] = True
        with (
            patch("anchorrun.remote.inspect_container", return_value=info),
            patch("anchorrun.remote.run_command") as run,
            self.assertRaisesRegex(ConfigError, "not running"),
        ):
            execute_remote(self.target, ["touch", "must-not-exist"])
        run.assert_not_called()

    def test_cached_image_and_podman_bare_ids_never_pull(self):
        for runtime, image_id in (
            ("docker", self.info["Image"]),
            ("podman", self.info["Image"].removeprefix("sha256:")),
        ):
            target = TargetConfig(
                "gpu",
                "gpu-lab",
                "/srv/project",
                ContainerConfig("dev", runtime=runtime),
            )
            with (
                self.subTest(runtime=runtime),
                patch(
                    "anchorrun.remote.run_command",
                    return_value=Mock(returncode=0, stdout=image_id + "\n", stderr=""),
                ) as run,
                patch("anchorrun.remote._capture") as capture,
            ):
                self.assertEqual(_resolve_image(target), self.info["Image"])
            self.assertIn("image inspect", run.call_args.args[0][-1])
            self.assertIn("dev", run.call_args.args[0][-1])
            self.assertFalse(run.call_args.kwargs["check"])
            capture.assert_not_called()

    def test_image_daemon_transport_and_permission_failures_never_pull(self):
        for code, message in (
            (125, "Cannot connect to the Docker daemon"),
            (1, "permission denied"),
            (127, "docker: command not found"),
            (255, "No such image"),
        ):
            with (
                self.subTest(code=code, message=message),
                patch(
                    "anchorrun.remote.run_command",
                    return_value=Mock(returncode=code, stdout="", stderr=message),
                ),
                patch("anchorrun.remote._capture") as capture,
                redirect_stderr(io.StringIO()),
                self.assertRaises(CommandError) as caught,
            ):
                _resolve_image(self.target)
            self.assertEqual(caught.exception.returncode, code)
            capture.assert_not_called()

    def test_inspected_podman_image_id_normalizes_before_label_validation(self):
        info = deepcopy(self.info)
        info["Image"] = info["Image"].removeprefix("sha256:")
        with patch("anchorrun.remote._capture", side_effect=["id", json.dumps([info])]):
            inspected = inspect_container(self.target)
        self.assertEqual(inspected["Image"], self.info["Image"])


class StreamEdgeTests(unittest.TestCase):
    def test_real_subprocess_forwards_binary_stdin_stdout_stderr_and_status(self):
        child = (
            "import sys; data=sys.stdin.buffer.read(); "
            "sys.stdout.buffer.write(data); sys.stderr.buffer.write(b'error\\x00\\xff'); "
            "sys.exit(23)"
        )
        wrapper = (
            "import sys\n"
            "from anchorrun.remote import run_command\n"
            f"result = run_command([sys.executable, '-c', {child!r}], stdin=True)\n"
            "sys.exit(result.returncode)\n"
        )
        payload = b"patch\n\x00\xff\r\n" + bytes(range(256)) * 512
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            input=payload,
            capture_output=True,
            check=False,
            timeout=10,
            env=self._environment(),
        )
        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, payload)
        self.assertEqual(result.stderr, b"error\x00\xff")

    def test_default_subprocess_stdin_is_eof(self):
        wrapper = (
            "import sys\n"
            "from anchorrun.remote import run_command\n"
            "run_command([sys.executable, '-c', "
            "'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'])\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            input=b"must not reach child",
            capture_output=True,
            check=False,
            timeout=10,
            env=self._environment(),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    @staticmethod
    def _environment():
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        return environment


class CliEdgeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = write_config(Path(directory.name))
        self.prefix = ["--config", str(self.config)]

    def test_prepare_returns_transport_signal_and_start_errors_cleanly(self):
        for error, status in (
            (CommandError("ssh", -15), 143),
            (CommandStartError("ssh", "unavailable"), 2),
        ):
            stderr = io.StringIO()
            with (
                self.subTest(error=error),
                patch("anchorrun.cli.prepare_target", side_effect=error),
                redirect_stderr(stderr),
            ):
                self.assertEqual(main(self.prefix + ["prepare"]), status)
            self.assertIn("error:", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_successful_prepare_prints_machine_readable_result(self):
        payload = {"target": "gpu", "status": "ready", "container_id": "prepared"}
        output = io.StringIO()
        with (
            patch("anchorrun.cli.prepare_target", return_value=payload),
            redirect_stdout(output),
        ):
            self.assertEqual(main(self.prefix + ["prepare"]), 0)
        self.assertEqual(json.loads(output.getvalue()), payload)

    def test_doctor_unknown_target_never_connects(self):
        with (
            patch("anchorrun.cli.local_issues", return_value=[]),
            patch("anchorrun.cli.probe_target") as probe,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(self.prefix + ["doctor", "--target", "absent"]), 2)
        probe.assert_not_called()

    def test_doctor_rejects_invalid_timeouts_before_remote_work(self):
        for value in ("0", "-1", "nan"):
            with (
                self.subTest(value=value),
                patch("anchorrun.cli.probe_target") as probe,
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as caught,
            ):
                main(self.prefix + ["doctor", "--timeout", value])
            self.assertEqual(caught.exception.code, 2)
            probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
