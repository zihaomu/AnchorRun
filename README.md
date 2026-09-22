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

If `uv` is unavailable, make sure Python 3 and pip are installed, then install
into an active Python environment with `python3 -m pip install -e .`.

To make the bundled skill available from every project, link it into the Codex
skill directory:

```bash
ln -s "$PWD/skills/anchorrun" "${CODEX_HOME:-$HOME/.codex}/skills/anchorrun"
```

## Quick start: connect a local project to a remote machine

The setup below maps one local project directory to one directory on a remote
Linux host, mounts that remote copy into a container, runs a command, and pulls
declared outputs back to the local project.

### 1. Configure an SSH alias

Add the remote machine to `~/.ssh/config` on the local or WSL machine:

```sshconfig
Host gpu-lab
    HostName 192.168.1.100
    User my-user
    IdentityFile ~/.ssh/id_ed25519
```

Verify that non-interactive SSH works before configuring AnchorRun:

```bash
ssh gpu-lab 'hostname && id -un'
```

AnchorRun accepts an SSH configuration alias such as `gpu-lab`; do not put SSH
options, passwords, or shell commands in `.anchorrun.yaml`.

### 2. Add `.anchorrun.yaml` to the project root

For a new project directory:

```bash
mkdir -p ~/projects/my-project
cd ~/projects/my-project
cp /path/to/AnchorRun/examples/anchorrun.yaml .anchorrun.yaml
```

Edit `.anchorrun.yaml` so that its SSH alias, remote directory, image, mounts,
and artifact paths match the project:

```yaml
schema_version: 1

project:
  local_root: .
  state_dir: ./.anchorrun

default_target: gpu

sync:
  allow_delete: false
  excludes:
    - .git/
    - .anchorrun/
    - __pycache__/
    - "*.pyc"
    - artifacts/

targets:
  gpu:
    ssh_host: gpu-lab
    remote_root: /home/my-user/anchorrun-workspaces/my-project
    container:
      runtime: docker
      image: registry.example.com/team/dev@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
      workdir: /workspace
      shell: /bin/bash
      devices: []
      security_options: []
      mounts:
        - source: /data/models
          target: /models
          read_only: true
        - source: /data/datasets
          target: /datasets
          read_only: true
      environment_from_host: []

artifacts:
  - remote: outputs
    local: artifacts/outputs
  - remote: reports
    local: artifacts/reports
```

Use a different `remote_root` for every project. The additional mount sources,
such as `/data/models`, must already exist on the remote host; AnchorRun does not
copy model or dataset directories from the local machine.

For AMD GPUs, a target will commonly add:

```yaml
devices:
  - /dev/kfd
  - /dev/dri
security_options:
  - seccomp=unconfined
```

Images must use an immutable digest rather than a tag such as `latest`. One way
to retrieve the digest on the remote host is:

```bash
ssh gpu-lab \
  'docker pull registry.example.com/team/dev:tag &&
   docker image inspect --format "{{index .RepoDigests 0}}" registry.example.com/team/dev:tag'
```

Log in to a private registry on the remote host first. For Podman targets,
replace `docker` with `podman` in both the configuration and command.

The resulting path mapping is:

```text
local project (project.local_root)
        │  rsync, local to remote
        ▼
remote host (target.remote_root)
        │  container bind mount
        ▼
container (target.container.workdir)
```

The local project remains authoritative. Do not edit the synchronized remote
copy and expect those changes to flow back automatically.

### 3. Validate and prepare the remote target

Run these commands from the project root or any child directory. AnchorRun
searches upward for `.anchorrun.yaml`.

```bash
# Resolve and display the configuration without changing anything.
anchorrun show

# Check the local project, ssh, and rsync prerequisites.
anchorrun doctor

# Check SSH, the remote runtime, image, and path. A new target may be not-ready.
anchorrun doctor --remote

# Create remote_root and pull the pinned image if it is absent.
anchorrun prepare

# The target should now report ready.
anchorrun doctor --remote
```

`prepare` initializes only the configured target. It does not upload source or
create additional model and dataset mount sources.

### 4. Preview synchronization and execute

Preview the first local-to-remote synchronization:

```bash
anchorrun sync --dry-run
```

Normal commands can then use `exec` directly. It synchronizes the local project
before starting the configured remote container:

```bash
anchorrun exec -- python -m pytest
```

Use an explicit shell when the command contains pipes, redirects, or `&&`:

```bash
anchorrun exec -- bash -lc 'cmake -S . -B build && cmake --build build -j'
```

Use `anchorrun shell` only when an interactive container session is needed.

### 5. Pull declared artifacts

Artifact paths are relative to `remote_root`. With `workdir: /workspace`, a
program that writes `/workspace/outputs/result.json` creates
`remote_root/outputs/result.json` on the remote host. The mapping above pulls it
to `artifacts/outputs/result.json` locally.

```bash
anchorrun pull --dry-run
anchorrun pull
```

Only paths declared under `artifacts` can be pulled. Normal synchronization is
local-to-remote only, and remote deletion additionally requires both
`sync.allow_delete: true` and an explicit `anchorrun sync --delete`.

`examples/radeon-kernel-workspace.yaml` contains a fuller Radeon workspace
migration example.

## Command reference

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
