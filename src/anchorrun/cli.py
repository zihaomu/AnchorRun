from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from anchorrun.config import load_config
from anchorrun.errors import AnchorRunError, CommandError
from anchorrun.remote import execute_remote, local_issues, prepare_target, probe_target


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anchorrun",
        description="Operate a remote workspace from a local configuration.",
    )
    parser.add_argument(
        "--config", type=Path, help="file or directory; defaults to upward discovery"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser(
        "show", help="show resolved configuration without connecting"
    )
    show.add_argument("--target")
    doctor = commands.add_parser(
        "doctor", help="check SSH, paths and the managed container"
    )
    doctor.add_argument("--target", action="append", default=[])
    doctor.add_argument(
        "--local",
        action="store_true",
        help="only validate config and local SSH availability",
    )
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument(
        "--timeout", type=_positive_int, default=20, help="timeout per remote check"
    )
    prepare = commands.add_parser(
        "prepare", help="create or reuse the managed development container"
    )
    prepare.add_argument("--target")
    prepare.add_argument(
        "--recreate",
        action="store_true",
        help="replace only this workspace's managed container; discards its writable layer",
    )
    prepare.add_argument("--dry-run", action="store_true")
    execute = commands.add_parser(
        "exec", help="run directly in the prepared remote workspace"
    )
    execute.add_argument("--target")
    execute.add_argument(
        "--stdin",
        action="store_true",
        help="forward stdin without allocating a terminal (scripts, patches, binary input)",
    )
    execute.add_argument("--dry-run", action="store_true")
    execute.add_argument("command_args", nargs=argparse.REMAINDER)
    shell = commands.add_parser(
        "shell", help="open an interactive shell in the managed container"
    )
    shell.add_argument("--target")
    shell.add_argument("--dry-run", action="store_true")
    return parser


def _doctor(config, args: argparse.Namespace) -> int:
    issues = local_issues()
    selected = (
        [config.target(name) for name in args.target]
        if args.target
        else [config.target()]
    )
    probes = (
        []
        if args.local or issues
        else [probe_target(target, timeout=args.timeout) for target in selected]
    )
    ready = not issues and all(probe["ready"] for probe in probes)
    payload = {
        "status": ("valid" if args.local else "ready") if ready else "not-ready",
        "scope": "local" if args.local else "remote",
        "config_file": str(config.config_file),
        "local_issues": issues,
        "targets": [target.name for target in selected],
        "remote": probes,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"status: {payload['status']}")
        for issue in issues:
            print(f"local: {issue}")
        for probe in probes:
            print(f"{probe['target']}: {probe['message']}")
    return 0 if ready else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "show":
            payload = config.to_dict()
            payload["selected_target"] = config.target(args.target).name
            print(json.dumps(payload, indent=2))
            return 0
        if args.command == "doctor":
            return _doctor(config, args)
        target = config.target(args.target)
        if args.command == "prepare":
            result = prepare_target(
                target, recreate=args.recreate, dry_run=args.dry_run
            )
            if result is not None:
                print(json.dumps(result, indent=2))
            return 0
        if args.command == "exec":
            command = args.command_args
            if command and command[0] == "--":
                command = command[1:]
            return execute_remote(
                target, command, stdin=args.stdin, dry_run=args.dry_run
            )
        if args.command == "shell":
            return execute_remote(
                target, [target.container.shell], interactive=True, dry_run=args.dry_run
            )
        raise AssertionError(args.command)
    except CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.returncode if exc.returncode >= 0 else 128 - exc.returncode
    except AnchorRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
