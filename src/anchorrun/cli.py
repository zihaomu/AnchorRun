from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from anchorrun.config import load_config
from anchorrun.errors import AnchorRunError
from anchorrun.remote import (
    execute_remote,
    local_issues,
    prepare_target,
    probe_target,
    pull_artifacts,
    sync_workspace,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anchorrun",
        description="Run a locally owned project in a configured remote container.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="configuration file or directory; defaults to upward discovery",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    show = commands.add_parser("show", help="print the resolved configuration")
    show.add_argument("--target", help="verify and highlight one target")

    doctor = commands.add_parser("doctor", help="validate local and remote readiness")
    doctor.add_argument("--target", action="append", default=[])
    doctor.add_argument("--remote", action="store_true")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--timeout", type=int, default=20)

    prepare = commands.add_parser(
        "prepare",
        help="create the remote root and pull the pinned container image if absent",
    )
    prepare.add_argument("--target")
    prepare.add_argument("--dry-run", action="store_true")

    sync = commands.add_parser("sync", help="push the local project to a remote target")
    sync.add_argument("--target")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument(
        "--delete",
        action="store_true",
        help="delete remote extras; also requires sync.allow_delete in config",
    )

    execute = commands.add_parser(
        "exec",
        help="sync, then run a command in the remote container",
    )
    execute.add_argument("--target")
    execute.add_argument("--no-sync", action="store_true")
    execute.add_argument("--dry-run", action="store_true")
    execute.add_argument("command_args", nargs=argparse.REMAINDER)

    shell = commands.add_parser(
        "shell", help="open an interactive remote container shell"
    )
    shell.add_argument("--target")
    shell.add_argument("--no-sync", action="store_true")
    shell.add_argument("--dry-run", action="store_true")

    pull = commands.add_parser(
        "pull", help="pull declared artifacts into the local project"
    )
    pull.add_argument("--target")
    pull.add_argument("--dry-run", action="store_true")
    return parser


def _selected_targets(config, names: list[str]):
    if not names:
        return (config.target(),)
    return tuple(config.target(name) for name in names)


def _show(config, target_name: str | None) -> int:
    payload = config.to_dict()
    if target_name:
        payload["selected_target"] = config.target(target_name).name
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _doctor(config, args: argparse.Namespace) -> int:
    issues = local_issues(config)
    selected = _selected_targets(config, args.target)
    probes = (
        [probe_target(target, timeout_seconds=args.timeout) for target in selected]
        if args.remote
        else []
    )
    payload = {
        "status": "ready"
        if not issues and all(probe.ready for probe in probes)
        else "not-ready",
        "config_file": str(config.config_file),
        "local_root": str(config.local_root),
        "local_issues": issues,
        "targets": [target.name for target in selected],
        "remote": [probe.to_dict() for probe in probes],
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"status: {payload['status']}")
        print(f"config: {config.config_file}")
        print(f"local root: {config.local_root}")
        for issue in issues:
            print(f"local: {issue}")
        for probe in probes:
            print(f"remote {probe.target}: {probe.message}")
    return 0 if payload["status"] == "ready" else 1


def _clean_remainder(arguments: list[str]) -> list[str]:
    if arguments and arguments[0] == "--":
        return arguments[1:]
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "show":
            return _show(config, args.target)
        if args.command == "doctor":
            return _doctor(config, args)

        target = config.target(args.target)
        if args.command == "prepare":
            prepare_target(target, dry_run=args.dry_run)
            return 0
        if args.command == "sync":
            sync_workspace(
                config,
                target,
                dry_run=args.dry_run,
                delete=args.delete,
            )
            return 0
        if args.command == "exec":
            command_args = _clean_remainder(args.command_args)
            if not args.no_sync:
                sync_workspace(config, target, dry_run=args.dry_run)
            execute_remote(target, command_args, dry_run=args.dry_run)
            return 0
        if args.command == "shell":
            if not args.no_sync:
                sync_workspace(config, target, dry_run=args.dry_run)
            execute_remote(
                target,
                [target.container.shell],
                interactive=True,
                dry_run=args.dry_run,
            )
            return 0
        if args.command == "pull":
            pull_artifacts(config, target, dry_run=args.dry_run)
            return 0
        raise AssertionError(f"unhandled command: {args.command}")
    except AnchorRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
