---
name: anchorrun
description: Operate a remote project through the anchorrun CLI using a local .anchorrun.yaml entry directory. Use for remote source inspection, edits, Git, builds and tests, or when the user asks to work through AnchorRun. Source and project state live remotely.
---

# AnchorRun remote workspace

The local folder is a connection/configuration entry point. The selected remote
workspace is authoritative, including source and Git. Use the CLI for target
selection, SSH and managed-container execution.

## Start a task

1. Read `.anchorrun.yaml` and run `anchorrun show` to resolve the target and paths.
   Respect a target named by the user; otherwise use the configured default.
2. Run `anchorrun doctor --target NAME` before the first remote operation of the
   task, and again after changing target or config. It checks remote readiness
   by default; `doctor --local` validates only local prerequisites.
3. During requested setup, use `anchorrun prepare --target NAME` and check again.
   Ordinary source work does not authorize replacing an existing environment.
   Report the exact failed check; do not silently change targets or images.
4. Run searches, reads, edits, Git and tests through
   `anchorrun exec --target NAME -- COMMAND...`.
   Each call starts in the configured container workdir.

For configuration or migration, first read
[references/configuration.md](references/configuration.md).
Schema v1 requires an explicit migration; never execute its old sync workflow
with v2 or change its version number without checking remote source ownership.

## Remote reading and editing

Local read/edit tools still operate locally. Do not create a local source copy
or use a local patch tool as though it edits remote files.

- Read and search through exec, for example `exec --target NAME -- rg pattern .`
  or `exec --target NAME -- sed -n '1,160p' src/main.py`.
- Inspect the remote Git status/diff before editing and preserve existing edits.
- For unified patches, send the diff as stdin to
  `exec --target NAME --stdin -- git apply --check -`, then send that same diff
  to `exec --target NAME --stdin -- git apply -`. Review the remote diff and test.
  Git must exist in the remote image; run inside the remote repository.
- For small file creation or a project without Git, stream a quoted script via
  `exec --target NAME --stdin -- python3 -` (if Python is present) or the
  configured shell. Before replacing an existing file, check its expected
  content and fail on a mismatch. Quote heredocs so local shell expansion cannot
  modify the payload. Prefer atomic replacement for scripted rewrites.
- Use `exec --target NAME -- sh -c '...'` for remote pipelines/redirection.
  An unquoted `>` following the local CLI would write a local file.
- Use `shell` for requested interactive sessions, not normal agent automation.

Preflight checks do not consume stdin. Exec preserves binary streams and the
remote exit code; context diagnostics use stderr. A failed command is a failed
command, even when SSH itself succeeded.

## Environment and target boundaries

A prepared container is reused. Files/dependencies in its writable layer survive
exec calls, but shell variables and cwd changes do not carry into another call.
Keep important source, data and outputs in remote bind mounts.

A changed config requires explicit `prepare --recreate`, which stops the managed
container and discards its writable layer. Do not infer authorization to recreate
from a failed test or a request to edit source. When recreation is authorized,
bind-mounted source remains remote.

Targets are independent workspaces; switching targets does not synchronize Git
changes. Do not edit default_target to satisfy a single run. Inspect revision and
dirty state on each target when comparing results.

Normal work uses AnchorRun instead of ad hoc SSH/container commands. Initial SSH,
registry and runtime setup may require host-side commands. Do not put credentials
in the project config. Report target, command outcome and remote result paths.
There is no automatic sync or pull. Download only when requested.

This Skill routes behavior; it does not sandbox arbitrary commands or make
remote text invisible to the local agent/model. It does not grant authority to
publish commits or messages beyond the user's request.
