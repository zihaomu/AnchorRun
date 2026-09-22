---
name: anchorrun
description: Use a local project as the source of truth while building, testing, or running it in a configured container on a remote machine through the anchorrun CLI. Use when a project contains .anchorrun.yaml or the user asks to work through AnchorRun. Do not use for ordinary local-only projects without that configuration.
---

# AnchorRun

Treat the local project tree as authoritative. Let the CLI perform target selection,
path validation, synchronization, SSH transport, and container invocation.

## Workflow

1. Run `anchorrun doctor --remote` from anywhere inside the project before
   the first remote operation of the task. If it reports `not-ready`, report the
   exact failed check. Do not silently switch targets, images, or paths.
   When the user is explicitly setting up or adapting the configured target, use
   `anchorrun prepare` to create the remote root and fetch the pinned image,
   then run the doctor again. Do not prepare unrelated targets.
2. Make source edits only in the local project.
3. Use `anchorrun exec -- <command...>` for non-interactive builds, tests,
   benchmarks, and inspection commands. It synchronizes before execution.
4. Use `anchorrun shell` only when the user explicitly needs an interactive
   session.
5. Use `anchorrun pull` only when declared remote artifacts need to be
   copied back to the local project.

Use `--target NAME` only when the user selects a non-default configured target or
the task already names that target.

## Invariants

- Do not edit files directly on the remote workspace and later treat them as
  source. Changes belong in the local project and flow outward.
- Do not construct ad hoc `rsync`, `ssh`, `docker`, or `podman` commands for normal
  work. Diagnose configuration or CLI failures instead of bypassing AnchorRun.
- Never pass `--delete` unless the user explicitly asks to delete remote extras.
  The CLI also requires `sync.allow_delete: true` as a second gate.
- Do not pull undeclared paths or place artifacts outside the configured local
  project root.
- Do not place credentials in `.anchorrun.yaml`.

When reporting a remote result, name the selected target, the command executed,
and any artifact mapping pulled back. Avoid repeating full private registry names
unless they are relevant to a failure.

## Configuration work

For setup, migration, or configuration diagnosis, read
[references/configuration.md](references/configuration.md) before editing the
project configuration.
