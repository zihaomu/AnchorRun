# AnchorRun schema v2

Use this reference to create, migrate or diagnose `.anchorrun.yaml`.
The config directory can contain no source at all. The CLI searches upward from
the current directory; global `--config PATH` selects a file or entry directory.

## Minimal configuration

```yaml
schema_version: 2
targets:
  dev:
    ssh_host: gpu-lab
    remote_root: /home/my-user/projects/my-project
    container:
      image: python:3.11-slim
```

With multiple targets, set `default_target`. Commands accept `--target NAME`;
doctor accepts it repeatedly. A target never implies code synchronization with
another machine.

## Fields and defaults

Only `schema_version`, `default_target` and `targets` are top-level fields.
Unknown and duplicate fields fail validation. Schema v1 is explicitly rejected
with migration instructions before any SSH operation.

| Field | Meaning |
| --- | --- |
| `ssh_host` | Simple alias in local SSH config; no flags, credentials or shell code |
| `remote_root` | Authoritative host-side source/Git directory |
| `container.image` | Image name, tag or sha256 digest; resolved to an immutable ID at prepare |
| `container.runtime` | `docker` (default) or `podman` |
| `container.workdir` | Container working directory and root bind mount; defaults to `/workspace` |
| `container.shell` | POSIX-compatible shell, default `/bin/sh` |
| `container.entrypoint` | Optional shell override for the managed keepalive process; defaults to shell |
| `container.user` | Optional image user override, e.g. `1000:1000`; default is the image user |
| `container.devices` | Device paths, default empty |
| `container.security_options` | Runtime security options, default empty |
| `container.mounts` | Additional remote bind mounts, default empty |
| `container.environment_from_host` | Remote SSH process environment variable names, default empty |

Paths are normalized non-root absolute POSIX paths, using letters, digits,
`.`, `_`, `-` and `/`. Mount destinations cannot overlap each other or the
workspace mount. Additional mount sources must already exist on the host.
SSH/network/runtime credentials are configured separately.

The SSH user must be able to access/create remote_root. The container user
must be able to read/write the bind mount. On a typical rootful Docker host,
set `user` to the remote user's numeric UID:GID when matching file ownership is
needed; check with `ssh gpu-lab id`. Rootless Podman's user mapping is different,
so verify permissions with doctor rather than assuming the same numeric mapping.

Example GPU/container extensions:

```yaml
container:
  runtime: docker
  image: registry.example.com/team/dev:2026.10
  shell: /bin/bash
  entrypoint: /bin/bash
  user: '1000:1000'
  devices: [/dev/kfd, /dev/dri]
  security_options: [seccomp=unconfined]
  mounts:
    - source: /data/models
      target: /models
      read_only: true
    - source: /data/cache
      target: /cache
      read_only: false
  environment_from_host: [HF_TOKEN]
```

Images must include a POSIX shell accepting `-c` and `sleep` for the managed
keepalive. The image's application entrypoint is replaced. The optional
`entrypoint` must also be such a shell; `exec` invokes the requested command
directly and does not prefix it with the entrypoint.

Environment names are resolved on the remote host during container creation,
not from the local process or from config values. Non-interactive SSH may not
load interactive shell exports. Captured values persist in the container until
recreation; changing their values requires explicit recreation even if the
configuration fingerprint stays the same.

## Lifecycle

`prepare` inspects ownership and configuration, ensures remote_root and mount
sources, resolves the exact image reference (pulling only when missing), and
creates/starts a named container. Creation uses the resolved ID, so mutable tags
cannot race the create step. Repeating prepare preserves an existing compatible
container and does not refresh tags.

The name derives from remote_root; labels store workspace identity, full config
fingerprint and actual image ID. The same directory on the same runtime belongs
to one AnchorRun-managed environment. Use another root for an independent one.

`exec` requires a matching running container, pins its inspected ID and sets
workdir on every invocation. It never prepares, starts, pulls or synchronizes.
`doctor` checks host paths, running state, labels and container workdir access.
`doctor --local` does not prove remote readiness. Doctor timeouts apply to each
remote check.

For an authorized environment change, run `prepare --recreate`. It checks
paths/resolves the replacement image before stopping/removing the current
managed container. It never removes an unowned name collision. Failure during
creation may leave no running environment; retry prepare after fixing the
reported issue. Bind-mounted data is not deleted. There is no automatic rollback
of container-only changes.

## Migrating v1

See [migration-v2.md](../../../doc/migration-v2.md) in a full checkout. When the
Skill is installed independently, use these steps:

1. Inspect the intended remote_root and decide which existing source/Git tree is
   authoritative. Preserve any local-only changes explicitly before switching.
2. Remove `project`, `sync` and `artifacts`; set `schema_version: 2`.
3. Keep target connections, image, GPU and mount settings; check container paths
   and user permissions. Adapt entrypoint to the managed-shell semantics above.
4. Run show, doctor, explicitly prepare the selected target, then doctor again.
5. Read/edit/test via exec. There is no `sync`, `pull` or `--no-sync`;
   `doctor` now checks remote readiness without `--remote`.

No migration copies, deletes or overwrites source automatically.
