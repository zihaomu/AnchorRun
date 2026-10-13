# Changelog

## [0.2.0] - 2026-10-13

### Changed

- Keep source, Git and project outputs on the remote host; local entry directories
  need only `.anchorrun.yaml` using schema v2.
- Reuse managed development containers across commands. Explicitly recreate
  containers when their configuration changes.
- Check remote readiness with `doctor` by default; use `--local` for local checks.
- Accept image names/tags and digests, resolving an immutable ID at preparation.
- Route agent reading, editing, Git and testing through the remote-workspace Skill.

### Added

- Binary stdin forwarding for scripts and patches, separate stdout/stderr, and
  remote exit-code propagation.
- Container ownership/configuration checks, explicit user and keepalive shell
  overrides, and recorded image identities.
- A v1 migration guide and opt-in two-machine end-to-end validation.

### Removed

- Automatic source synchronization, `sync`, `pull`, `--no-sync`, and the
  `project`, `sync` and `artifacts` configuration sections.

Schema v1 is rejected with migration guidance before any remote operation.
