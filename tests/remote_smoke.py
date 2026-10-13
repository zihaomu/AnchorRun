"""Opt-in live smoke test: two disposable targets, only a local config.

Run: python -m tests.remote_smoke --config /path/to/disposable/.anchorrun.yaml
Requires Python 3 and Git in both container images. Uses only AnchorRun for
normal remote operations. Leaves remote fixture files and containers for review.
Never point this test at an existing project: every target root must have an
anchorrun-v2-smoke. prefix, with a fresh randomized directory recommended.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

from anchorrun.config import load_config


def run(config: Path, *args: str, data: bytes | None = None, expected: int = 0):
    result = subprocess.run(
        [sys.executable, "-m", "anchorrun", "--config", str(config), *args],
        input=data,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"{args}: expected {expected}, got {result.returncode}\n{result.stdout.decode(errors='replace')}\n{result.stderr.decode(errors='replace')}"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    if len(config.targets) != 2:
        parser.error("exactly two disposable targets are required")
    if len({target.ssh_host for target in config.targets}) != 2:
        parser.error("targets must use distinct SSH aliases")
    if any(
        not Path(target.remote_root).name.startswith("anchorrun-v2-smoke.")
        for target in config.targets
    ):
        parser.error(
            "use dedicated remote directories named anchorrun-v2-smoke.<random>"
        )
    before = set(config.config_file.parent.iterdir())
    if before != {config.config_file}:
        parser.error("local entry directory must contain only .anchorrun.yaml")
    reports = []
    token = uuid.uuid4().hex
    for target in config.targets:
        name = target.name
        prepare = json.loads(
            run(config.config_file, "prepare", "--target", name).stdout
        )
        again = json.loads(run(config.config_file, "prepare", "--target", name).stdout)
        assert prepare["container_id"] == again["container_id"], (
            "prepare replaced the container"
        )
        doctor = json.loads(
            run(config.config_file, "doctor", "--target", name, "--json").stdout
        )
        assert doctor["status"] == "ready"
        assert (
            run(
                config.config_file, "exec", "--target", name, "--", "pwd"
            ).stdout.strip()
            == target.container.workdir.encode()
        )
        # Every fixture stays remote. Do not overwrite a prior run's files.
        folder = f"smoke-{token}-{name}"
        content = f"{name}-before\n".encode()
        create = f"""from pathlib import Path
p = Path({folder!r})
p.mkdir()
(p / 'sample.txt').write_bytes({content!r})
Path('/tmp/anchorrun-layer-{token}').write_text('kept')
"""
        run(
            config.config_file,
            "exec",
            "--target",
            name,
            "--stdin",
            "--",
            "python3",
            "-",
            data=create.encode(),
        )
        run(
            config.config_file,
            "exec",
            "--target",
            name,
            "--",
            "git",
            "init",
            "--quiet",
            folder,
        )
        run(
            config.config_file,
            "exec",
            "--target",
            name,
            "--",
            "git",
            "-C",
            folder,
            "add",
            "sample.txt",
        )
        patch = f"""diff --git a/sample.txt b/sample.txt
--- a/sample.txt
+++ b/sample.txt
@@ -1 +1 @@
-{name}-before
+{name}-after
""".encode()
        prefix = (
            "exec",
            "--target",
            name,
            "--stdin",
            "--",
            "git",
            "-C",
            folder,
            "apply",
        )
        run(config.config_file, *prefix, "--check", "-", data=patch)
        run(config.config_file, *prefix, "-", data=patch)
        result = run(
            config.config_file,
            "exec",
            "--target",
            name,
            "--",
            "cat",
            f"{folder}/sample.txt",
        )
        assert result.stdout == f"{name}-after\n".encode()
        diff = run(
            config.config_file,
            "exec",
            "--target",
            name,
            "--",
            "git",
            "-C",
            folder,
            "diff",
        )
        assert f"+{name}-after".encode() in diff.stdout
        # A rejected patch must leave the source unchanged.
        bad = patch.replace(f"-{name}-before".encode(), b"-missing-context")
        failed = subprocess.run(
            [
                sys.executable,
                "-m",
                "anchorrun",
                "--config",
                str(config.config_file),
                *prefix,
                "-",
            ],
            input=bad,
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert failed.returncode != 0
        assert (
            run(
                config.config_file,
                "exec",
                "--target",
                name,
                "--",
                "cat",
                f"{folder}/sample.txt",
            ).stdout
            == result.stdout
        )
        # Container writable layer survives separate executions and prepare.
        reused = json.loads(run(config.config_file, "prepare", "--target", name).stdout)
        assert reused["container_id"] == prepare["container_id"]
        assert (
            run(
                config.config_file,
                "exec",
                "--target",
                name,
                "--",
                "cat",
                f"/tmp/anchorrun-layer-{token}",
            ).stdout
            == b"kept"
        )
        binary = bytes(range(256)) * 128
        assert (
            run(
                config.config_file,
                "exec",
                "--target",
                name,
                "--stdin",
                "--",
                "cat",
                data=binary,
            ).stdout
            == binary
        )
        split = run(
            config.config_file,
            "exec",
            "--target",
            name,
            "--",
            "sh",
            "-c",
            "printf output; printf error >&2; exit 37",
            expected=37,
        )
        assert split.stdout == b"output"
        assert b"error" in split.stderr
        tricky = "spaces; $(touch should-not-exist) 'quotes'\nline two"
        assert (
            run(
                config.config_file,
                "exec",
                "--target",
                name,
                "--",
                "printf",
                "%s",
                tricky,
            ).stdout
            == tricky.encode()
        )
        run(
            config.config_file,
            "exec",
            "--target",
            name,
            "--",
            "test",
            "!",
            "-e",
            "should-not-exist",
        )
        # Explicit target selection never changes the default.
        assert load_config(config.config_file).default_target == config.default_target
        reports.append(
            {
                "target": name,
                "container_id": prepare["container_id"],
                "image_id": prepare["image_id"],
                "fixture": folder,
                "checks": [
                    "config-only",
                    "prepare-reuse",
                    "doctor",
                    "remote-cwd",
                    "stdin-create",
                    "git-patch",
                    "patch-reject-no-change",
                    "git-diff",
                    "layer-persistence",
                    "binary-stdin",
                    "stdout-stderr-exit37",
                    "argv-quoting",
                    "default-unchanged",
                ],
            }
        )
        print(f"PASS {name}: {len(reports[-1]['checks'])} checks", flush=True)
    # Markers created on one target must not appear on the other.
    for target in config.targets:
        other = next(t for t in config.targets if t.name != target.name)
        run(
            config.config_file,
            "exec",
            "--target",
            target.name,
            "--",
            "test",
            "!",
            "-e",
            f"smoke-{token}-{other.name}",
        )
    assert set(config.config_file.parent.iterdir()) == before, (
        "local source/state was created"
    )
    print(
        json.dumps(
            {"status": "pass", "targets": reports, "target_isolation": True}, indent=2
        )
    )


if __name__ == "__main__":
    main()
