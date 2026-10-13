# AnchorRun

> Configure locally. Work remotely.

AnchorRun turns a local `.anchorrun.yaml` into a reliable entry point for an AI
agent working on a remote Linux project. Source, Git history, datasets, models,
build outputs and container state stay remote. Your WSL/local directory can
contain **only the configuration file**.

- Configuration selects the SSH host, authoritative remote directory and image.
- The CLI checks the environment and operates a reusable development container.
- The bundled Skill guides the agent's remote reading, editing, testing and Git work.

There is no source synchronization, local source checkout, artifact registry or
automatic download. Text read by the agent and command output still travel
through the local client and may enter the model context.

**0.2 / schema v2 is a breaking change.** Schema v1 is rejected before any remote
operation. Follow the [migration guide](doc/migration-v2.md) instead of merely
changing the version number.

## Install CLI and Skill

Run in the WSL/Linux environment from which the agent will execute commands.
Local requirements: Python 3.11+, SSH, and access to the configured machines.
Remote requirements: Linux, Docker or Podman accessible to the SSH user, and
a development image with a POSIX shell and `sleep`. Install project tools
(Python, Git, compilers, etc.) in the image as needed. Local rsync is not required.

```bash
git clone https://github.com/zihaomu/AnchorRun.git
cd AnchorRun
uv tool install --editable .
anchorrun --help
```

Without uv, use `python3 -m pip install -e .` in an active Python 3.11+ environment.
Make sure the agent's shell can find `anchorrun`, not just your interactive shell.
The checkout must stay in place for an editable installation.

The CLI installation does not install the Skill. In Codex you can ask:

```text
$skill-installer
Install skills/anchorrun from https://github.com/zihaomu/AnchorRun
```

For local development, link the entire Skill directory (including references)
from the checkout into the agent's skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$PWD/skills/anchorrun" "${CODEX_HOME:-$HOME/.codex}/skills/anchorrun"
```

If it already exists, inspect it before changing it. Existing installations
linked to this checkout pick up Skill changes; separately downloaded copies
need updating with the CLI. Refresh the agent's skill list or reopen it if needed.

Other local agents can load the same `skills/anchorrun` folder from their
supported skill directory, for example `~/.claude/skills/anchorrun` for Claude
Code or `~/.cursor/skills/anchorrun` for Cursor. A Skill does not supply SSH
credentials, CLI installation or network access to a cloud-hosted agent.

## Connect a new local directory to two machines

### 1. Configure SSH

Keep connection details and credentials in local `~/.ssh/config`:

```sshconfig
Host gpu-a
    HostName 192.168.1.101
    User my-user
    IdentityFile ~/.ssh/id_ed25519

Host gpu-b
    HostName 192.168.1.102
    User my-user
    IdentityFile ~/.ssh/id_ed25519
```

Verify the host keys and login interactively once. Then check non-interactive
access, which AnchorRun uses:

```bash
ssh -o BatchMode=yes gpu-a 'hostname && id'
ssh -o BatchMode=yes gpu-b 'hostname && id'
```

The SSH user also needs permission to operate the remote container runtime.
AnchorRun does not install Docker, change group membership or enable sudo.

### 2. Create the local entry directory

```bash
mkdir -p ~/projects/my-project-entry
cd ~/projects/my-project-entry
```

Create `.anchorrun.yaml` here:

```yaml
schema_version: 2
default_target: gpu-a

targets:
  gpu-a:
    ssh_host: gpu-a
    remote_root: /home/my-user/projects/my-project
    container:
      image: python:3.11-slim
  gpu-b:
    ssh_host: gpu-b
    remote_root: /home/my-user/projects/my-project
    container:
      image: python:3.11-slim
```

Replace the host aliases, directories and images with your own. The same path
on different machines represents independent source trees. AnchorRun does not
copy changes between them; use Git on each target when you need matching commits.

Defaults: `runtime: docker`, `workdir: /workspace`, `shell: /bin/sh`.
A single target needs no `default_target`.
Optional GPU devices, mounts, user and environment settings are documented in
the [configuration reference](skills/anchorrun/references/configuration.md).
The [Radeon example](examples/radeon-kernel-workspace.yaml) shows two GPU targets.

### 3. Check and prepare

From the entry directory or a descendant:

```bash
anchorrun show
anchorrun doctor --local
anchorrun doctor --target gpu-a
anchorrun prepare --target gpu-a
anchorrun doctor --target gpu-a

anchorrun prepare --target gpu-b
anchorrun doctor --target gpu-b
```

The first remote doctor may report not-ready because the managed container
does not exist yet. `prepare` creates the remote directory if needed, resolves
the image (pulling only if absent locally on that host), and creates/starts a
named development container. Repeating it reuses the same container.

Existing source in `remote_root` is kept. Additional mount sources must already
exist. AnchorRun does not clone a repository or install project dependencies
implicitly. For a new remote project, create files or clone explicitly through
`exec` using an image that contains Git.

### 4. Work directly on remote files

```bash
anchorrun exec --target gpu-a -- pwd
anchorrun exec --target gpu-a -- ls -la
anchorrun exec --target gpu-a -- python -c 'print("ready")'
```

The command starts in `/workspace`, bound to the chosen host's `remote_root`.
Use an explicit shell for pipes or redirects. Keep the script quoted so that
expansion and file operations happen remotely:

```bash
anchorrun exec --target gpu-a -- sh -c 'mkdir -p outputs && printf "%s\n" ready > outputs/result.txt'
anchorrun exec --target gpu-a -- cat outputs/result.txt
```

To write through stdin without a local source file:

```bash
anchorrun exec --target gpu-a --stdin -- sh -c 'cat > hello.py' <<'PY'
print("hello from the remote project")
PY

anchorrun exec --target gpu-a -- python hello.py
```

The quoted heredoc is a command payload, not a synchronized local source tree.
For an existing remote Git repository, send a unified diff to
`anchorrun exec --target gpu-a --stdin -- git apply --check -`, then send the
same diff to `git apply -`, and inspect `git diff`. Git must be installed in
that container. See the [remote editing workflow](skills/anchorrun/SKILL.md).

Use `anchorrun shell --target gpu-a` for a human-operated interactive session.
Each `exec` is a new process; shell `cd` and `export` do not persist between
calls. Files and installed dependencies in the container do persist until it is
explicitly replaced.

### 5. Ask your agent to use the remote workspace

```text
请使用 AnchorRun Skill。当前目录只有远端配置。
先检查 gpu-a 的环境，再在它的远端工作区读取源码、修改代码和运行测试。
所有源码及 Git 操作都通过 AnchorRun 在远端完成。
需要使用 gpu-b 时明确指定 target，不修改 default_target。
```

A local file-editing tool still edits local files; configuration alone does not
redirect it. The Skill instructs the agent to use remote commands and stdin
patches. Credentials remain in SSH/registry configuration, outside this YAML.

## Container lifecycle and command contract

| Command | Behavior |
| --- | --- |
| `show [--target NAME]` | Resolve config, defaults and container names without connecting |
| `doctor [--target NAME] [--json]` | Read-only remote checks; repeat `--target` to check multiple machines |
| `doctor --local` | Validate config and local SSH availability only; reports valid, not remote-ready |
| `prepare [--target NAME]` | Create or reuse this workspace's managed container |
| `prepare --recreate` | Explicitly replace that managed container |
| `exec [--target NAME] [--stdin] -- COMMAND...` | Execute with no synchronization or implicit preparation |
| `shell [--target NAME]` | Interactive shell in the prepared container |

Global `--config PATH` goes before the command. `prepare`, `exec` and `shell`
support `--dry-run` without connecting. Dry-run describes intent, not observed
remote state.

A container name is derived from the remote directory, so moving the local entry
folder or renaming a target does not create another container. Labels record
workspace identity, configuration fingerprint and resolved image ID. An
incompatible existing container is rejected; unrelated containers are never
adopted or removed.

Changes to image, user, workdir, devices or mounts require
`prepare --target NAME --recreate`. This stops the managed container and
discards its writable layer, including container-only dependency installations.
Remote bind-mounted source and data remain. Prepare does not automatically
refresh a cached image tag: pull the desired tag explicitly on the remote host,
then recreate. Use a digest when reproducibility matters. Changing the remote
root selects a different workspace and leaves the former container alone.

`exec` preserves command stdout, stderr and exit status. Context diagnostics
go to stderr. `--stdin` streams bytes without a TTY; readiness checks do not
consume that input. Configuration/startup errors return 2, failed doctor checks
return 1, and SSH transport failures use 255. A remote command may itself return
255, so use its diagnostic output to distinguish the cause.

A reusable container is not a job scheduler or a persistent shell. Disconnected
long-running tasks are not automatically tracked or recovered. Use an explicit
remote task/session manager for that workflow. Container isolation and SSH
permissions determine access; a configured workdir is not a security sandbox.

## Verify and develop

```bash
uv run python -m unittest discover -s tests -v
uvx ruff check .
uv build
```

The opt-in [two-host smoke test](tests/remote_smoke.py) checks repeated prepare,
remote file creation, Git patches/diffs, rejected patches, container persistence,
binary stdin, quoting, stdout/stderr, exit status and target isolation:

```bash
uv run python -m tests.remote_smoke --config /path/to/disposable-entry/.anchorrun.yaml
```

It requires two dedicated remote roots named `anchorrun-v2-smoke.<random>`,
images with Python 3 and Git, and an entry directory containing only the config.
It leaves test fixtures and containers for inspection. Do not use a production
project directory. See [validation evidence](doc/validation-v2.md).

AnchorRun is licensed under [Apache-2.0](LICENSE).
