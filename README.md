# AnchorRun

> Source stays anchored. Compute runs remote.

AnchorRun keeps the local project tree—including projects hosted in WSL—as the
source of truth while it runs builds, tests, and development commands inside a
container on a configured remote machine.

The project has three deliberately separate layers:

- `.anchorrun.yaml` contains per-project facts.
- The `anchorrun` CLI performs deterministic SSH, rsync, and container work.
- `skills/anchorrun` tells Codex when and how to use the CLI.

## Install for development

```bash
git clone https://github.com/zihaomu/AnchorRun.git
cd AnchorRun
uv tool install --editable .
```

If `uv` is unavailable, install into an active Python environment with
`python -m pip install -e .`.

To make the bundled skill available from every project, link it into the Codex
skill directory:

```bash
ln -s "$PWD/skills/anchorrun" "${CODEX_HOME:-$HOME/.codex}/skills/anchorrun"
```

## Configure a project

Copy `examples/anchorrun.yaml` to the project root as
`.anchorrun.yaml`, then edit the target, image, and path values. The CLI
searches the current directory and its parents for that file.

`examples/radeon-kernel-workspace.yaml` is a direct migration of the existing
Radeon workspace mapping and can be copied into that workspace when it is ready
to adopt AnchorRun.

The local copy is authoritative. Normal synchronization only pushes from local to
the remote workspace. Pulling is limited to artifact mappings declared in the
configuration. Remote deletion requires both `sync.allow_delete: true` in the
configuration and an explicit `--delete` command-line flag.

## Commands

```bash
# Validate configuration and local prerequisites.
anchorrun doctor

# Also test SSH, the container runtime, the image, and remote path access.
anchorrun doctor --remote

# Explicit setup step: create the remote root and pull the pinned image if absent.
anchorrun prepare

# Show the fully resolved configuration without changing anything.
anchorrun show

# Preview or perform a local-to-remote synchronization.
anchorrun sync --dry-run
anchorrun sync

# Synchronize, then execute inside the configured remote container.
anchorrun exec -- python -m pytest

# Start an interactive container shell.
anchorrun shell

# Pull only the configured artifact directories back into the local project.
anchorrun pull --dry-run
anchorrun pull
```

Use `--target NAME` with `doctor`, `prepare`, `sync`, `exec`, `shell`, or `pull`
to override the configured default target. `doctor` checks the default target
unless one or more explicit `--target NAME` arguments are supplied.

## Safety model

- SSH destinations must be simple aliases from the user's SSH configuration.
- Remote roots and artifact paths use a conservative, normalized POSIX-path
  character set so they remain safe when passed through rsync's remote shell.
- Container images must be pinned by `sha256` digest.
- Project, state, and artifact destinations must remain within the local project
  root.
- Synchronization does not delete remote files unless two independent gates are
  enabled.
- Interactive commands never change which target is selected implicitly.
- Credentials stay in SSH configuration, credential stores, or environment
  variables; they do not belong in `.anchorrun.yaml`.

## Development

```bash
uv run python -m unittest discover -s tests -v
uvx ruff check .
python3 /home/zmu/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/anchorrun
```

## License

AnchorRun is licensed under the [Apache License 2.0](LICENSE).
