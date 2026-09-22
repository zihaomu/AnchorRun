# AnchorRun configuration

Read this reference when creating, migrating, or diagnosing
`.anchorrun.yaml`.

## Ownership model

- `project.local_root` is the authoritative local source tree.
- Each target maps that source tree to one remote host directory and one container
  work directory.
- `sync` controls only local-to-remote source synchronization.
- `artifacts` is the complete allowlist for remote-to-local copying.

## Minimal shape

```yaml
schema_version: 1

project:
  local_root: .
  state_dir: ./.anchorrun

default_target: gpu

sync:
  allow_delete: false
  excludes: [.git/, .anchorrun/]

targets:
  gpu:
    ssh_host: my-gpu-host
    remote_root: /home/me/workspaces/my-project
    container:
      runtime: docker
      image: registry.example/dev@sha256:<64 hexadecimal characters>
      workdir: /workspace
      shell: /bin/bash
      devices: []
      security_options: []
      mounts: []
      environment_from_host: []

artifacts:
  - remote: outputs
    local: artifacts/outputs
```

## Fields

`project.local_root` and `project.state_dir` are relative to the configuration
file and must remain inside that directory. Local artifact destinations are
relative to `project.local_root` and must remain below it.

`ssh_host` is an alias from the user's SSH configuration. It cannot contain SSH
options or shell syntax. Authentication belongs in SSH configuration rather than
this file.

`remote_root` is the host-side copy of the project. It must be a non-root absolute
POSIX path. Remote paths use a conservative normalized character set and reject
shell metacharacters because rsync passes remote operands through a shell. The CLI
mounts the root at `container.workdir` for every container command.

Images must be immutable digest references, use a conservative OCI reference
character set, and cannot begin with an option marker. Tags such as `latest` are
rejected.

Additional mounts use host-side absolute `source` and container-side absolute
`target` paths:

```yaml
mounts:
  - source: /data/models
    target: /models
    read_only: true
```

`environment_from_host` contains variable names, not values. The remote container
runtime copies those values from the remote host environment.

Each artifact mapping names a directory below `remote_root` and an explicit
destination below `local_root`. No arbitrary pull path is supported.

## Multiple targets

Put project-specific machines under `targets` and set `default_target`. Commands
may select another configured machine with `--target NAME`. Do not change the
default merely to satisfy one run.

## Migration from split configuration

When migrating a workspace that has one file for local paths and another target
inventory file:

1. Move the local project and state paths into `project`.
2. Move each SSH alias, remote root, and container block under a named `targets`
   entry.
3. Choose one explicit `default_target`.
4. Convert any expected output downloads into artifact mappings.
5. Run `anchorrun show`, `anchorrun doctor`, and then
   `anchorrun doctor --remote` before the first synchronization.
