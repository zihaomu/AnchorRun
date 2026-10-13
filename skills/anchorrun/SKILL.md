---
name: anchorrun
description: Read a project's .anchorrun.yaml to run project commands over SSH in the configured host directory or existing Docker container. Use when the user asks for AnchorRun or a project supplies this configuration. Not for ordinary local-only work or environment provisioning.
---

# AnchorRun

Route project work to the configured location using existing SSH and Docker
commands. There is no AnchorRun CLI, file-tool redirection or environment manager.

## Resolve the execution context

Use a config path explicitly supplied by the user; otherwise find the nearest
`.anchorrun.yaml` from the current directory up to the current project/workspace
root. Do not search unrelated projects. If the boundary or config is unclear,
ask for its path before connecting.

Read the whole config. This is the complete supported format:

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

- Only `schema`, `default_target`, and `targets` are top-level fields. Require
  exactly `schema: anchorrun-context/v1` and a nonempty mapping of named targets.
- Each target has nonempty string `ssh_host` and `workdir`; the only optional
  field is a nonempty string `container`, naming an existing Docker container.
- `ssh_host` is a local SSH alias, not a command or a `user@host` expression.
  Target names, SSH aliases and container names use letters, digits, `_`, `.`
  and `-`, starting with a letter or digit. Credentials belong in SSH settings.
- `workdir` is an absolute POSIX directory in the execution environment: host
  without `container`, inside the container otherwise. Treat it as literal data;
  never expand `~`, variables or substitutions from config. Reject control
  characters in values, duplicate keys, unknown fields, and ambiguous YAML.
- Use the user's explicit target, otherwise `default_target`; with only one
  target it may be omitted. An unknown target or ambiguous selection is an error,
  not permission to choose another machine or edit the default.
- Old `schema_version` configs are not this format. Stop and explain the manual
  mapping: keep SSH aliases, choose host or existing-container execution, and set
  that environment's `workdir`. Do not just rename the version field or infer a
  container from an image. Preserve local-only source before changing ownership.

Before the first remote operation, report the config path, target, SSH alias,
host/container and workdir. Resolve and check again after changing config/target.

## Check and execute

Use noninteractive SSH (`-T -o BatchMode=yes`); retain host-key verification.
First make a read-only check that the connection and selected directory work.
For container mode also inspect the named container's running state. A missing
directory/container, stopped container, or failed connection stops the task:
report the failure, without creating, starting, restarting or replacing anything.

Every project command must set its own workdir. A previous `cd` does not persist.
These examples use the config above; substitute the resolved values safely:

```bash
ssh -T -o BatchMode=yes gpu-a 'cd /home/user/my-project && python -m pytest'
ssh -T -o BatchMode=yes gpu-b 'docker exec -w /workspace/my-project project-dev python -m pytest'
```

Quote each value for every shell layer it passes through, including paths with
spaces or shell characters. Never evaluate config as shell code. Keep the whole
host command or pipeline behind a successful `cd ... &&`; use a remote shell
explicitly for compound commands and a container shell for container pipelines.
Do not let local expansion or redirection move part of the work outside the
selected execution environment.

Use remote commands for project searches, reads, edits, tests and Git. Local file
tools still edit local files; use them for the local config, not remote source.
For patch/script payloads, send stdin over SSH without a TTY; add `docker exec -i`
in container mode. Use quoted heredocs when constructing payloads locally.
Check a Git patch before applying it, preserve existing edits, then inspect the
remote diff. Do not create a synchronized local source tree.

Preserve stdout, stderr and exit status; a nonzero remote result is a failure,
even when SSH connected. Report the selected target and actual outcome. Never
fall back to local execution or another target after an error.

## Boundary

No image pulls, container lifecycle, dependency installation, synchronization or
task scheduling. If setup is needed, explain what is missing; handle it only as
a separate explicitly requested setup task. Targets are independent workspaces.
This Skill guides the agent, not a sandbox or command interceptor. Remote text
still passes through the local agent/model. Configuration never grants authority
for destructive operations, publishing or downloads beyond the user's request.
