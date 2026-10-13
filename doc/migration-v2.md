# Migrate to remote-authoritative schema v2

AnchorRun 0.2 changes ownership: the remote directory is the project, and the
local directory is an entry point containing configuration. V1 configs are
rejected before any SSH command. There is no automatic migration or file copy.

1. Preserve your v1 config and any local-only source changes. Inspect the remote
   source/Git directory and choose the authoritative tree. Do not point v2 at a
   stale synchronized copy without deliberately reconciling it.
2. Set `schema_version: 2`. Remove the top-level `project`, `sync` and `artifacts`
   sections. Keep `targets` and `default_target`; verify every remote_root.
3. Keep GPU devices, security options, mounts and environment variable names.
   Runtime defaults to Docker, workdir to `/workspace`, shell to `/bin/sh`.
   Image tags are accepted; digest references remain supported.
4. The managed container replaces the image entrypoint with a keepalive shell.
   If an `entrypoint` override was used, it must be a POSIX shell accepting `-c`.
   Instead of `exec -- -lc '...'`, invoke the shell explicitly:
   `exec -- bash -lc '...'`. Application entrypoint initialization is not run.
5. Check container user/remote directory permissions. `container.user` can
   explicitly select a user or numeric UID:GID. It defaults to the image user.
6. Run `anchorrun show`, `anchorrun doctor --local`, then
   `anchorrun doctor --target NAME`. Explicitly run `prepare --target NAME` and
   repeat doctor. Only prepare targets you intend to use.
7. Update the installed Skill along with the CLI. The old Skill requires local
   edits and synchronization, which conflicts with v2. Reopen/refresh the agent
   if its session still contains old instructions.

| Old | V2 |
| --- | --- |
| `exec` synchronizes then creates a temporary container | `exec` uses a prepared persistent container, no sync |
| `exec --no-sync` | `exec` |
| `doctor --remote` | `doctor` |
| local-only `doctor` | `doctor --local` |
| `sync`, `pull` | Removed; source remains remote, explicit transfers are separate |
| Local Git and edits | Remote Git and edits through exec |
| Image digest required | Tag/name/digest accepted, actual image ID recorded |

Changing config does not replace a container implicitly. `prepare --recreate`
stops/removes only this workspace's managed container, discards its writable
layer, and preserves bind-mounted source/data. Back up container-only work first.
Changing remote_root selects another workspace and leaves the old one intact.

There is no automatic cross-target synchronization, remote task recovery or
automatic rollback of container-only changes. You can retain AnchorRun 0.1 in
an isolated environment for v1 workflows while migrating projects individually.
