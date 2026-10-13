# AnchorRun

A Skill that reads a project's `.anchorrun.yaml` and guides an AI agent to run
commands on the right remote machine, in the right host directory or existing
Docker container. Source and Git stay remote; the local folder can contain only
the config.

There is no AnchorRun CLI or Python package to install. SSH and Docker do the
execution; the Skill supplies the location and operating rules. It does not
create environments, manage containers, synchronize files or schedule jobs.

## 1. Install the Skill

The agent needs command execution in your WSL/Linux environment, working SSH
access, and a remote Linux directory that already exists. Container mode also
needs Docker access and an already-running container on the remote host.

For a local Codex installation, link the complete Skill directory:

```bash
git clone https://github.com/zihaomu/AnchorRun.git
cd AnchorRun
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$PWD/skills/anchorrun" "${CODEX_HOME:-$HOME/.codex}/skills/anchorrun"
```

If the destination exists, inspect it before replacing anything. Keep the linked
checkout in place and reload the agent's skills or reopen the session. Other
agents can install the same directory using their supported skill mechanism.
The Skill does not give a cloud agent access to your local SSH credentials.

## 2. Configure the project entry directory

Set up aliases in local `~/.ssh/config` first. For example:

```sshconfig
Host gpu-a
    HostName 192.168.1.101
    User my-user

Host gpu-b
    HostName 192.168.1.102
    User my-user
```

Verify host keys and authentication yourself, then check noninteractive access
with `ssh -T -o BatchMode=yes gpu-a pwd` (and `gpu-b`). Do not disable host-key
checking to bypass an error.

Create a local entry directory and put `.anchorrun.yaml` in it:

```yaml
schema: anchorrun-context/v1
default_target: dev
targets:
  dev:
    ssh_host: gpu-a
    workdir: /home/user/my-project
  train:
    ssh_host: gpu-b
    container: project-dev
    workdir: /workspace/my-project
```

Replace the sample values with your existing environment. Without `container`,
`workdir` is a host directory; with it, `workdir` is inside that named Docker
container. An image name is not a container name. No local source tree is needed.

The [example file](examples/anchorrun.yaml) is ready to copy. The
[self-contained Skill](skills/anchorrun/SKILL.md) defines all supported fields
and selection rules; it requires no companion scripts or references.

## 3. Ask the agent to work there

```text
请使用 AnchorRun Skill，读取当前目录的 .anchorrun.yaml。
在默认目标的配置目录里检查 Git 状态，并运行项目测试。
```

To switch, say: `这次使用 train 目标，不修改 default_target。`

The agent reports its selected location, checks access, and sets the workdir on
every command. A missing directory, stopped container or connection error stops
the task; it does not fall back to local execution or provision an environment.
Each target is independent: switching does not synchronize code between machines.

This is behavioral guidance, not an interceptor or security sandbox. Local file
tools still operate locally, and not every agent is guaranteed to follow a Skill.
Requested remote file contents and results may enter the local agent/model context.

## Migrating from the CLI editions

`schema_version: 1` and `schema_version: 2` are different formats, not aliases for
`schema: anchorrun-context/v1`. The Skill stops on old configs; it does not migrate
or copy files automatically.

Preserve local-only changes and your old config. Keep the SSH aliases, explicitly
choose host or existing-container execution, and set the correct `workdir` in
that environment. Remove old source/sync/artifact/image/lifecycle settings from
the new config. Do not simply rename the version field or guess a container name.

Update the installed Skill as well as the project config. The old `anchorrun`
commands and Python package are no longer part of this repository. Existing
installations are not automatically uninstalled; keep a separate old checkout
if you still need a CLI workflow, especially with an editable installation.

Licensed under [Apache-2.0](LICENSE).
