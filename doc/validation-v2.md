# Schema v2 validation

Validated on 2026-10-13 from WSL against two separate Linux machines using Docker.
The local entry directory contained only `.anchorrun.yaml`, before and after the
complete run. This tests remote-authoritative operation without a local source
tree or local runtime-state directory.

## Automated checks

- 55 unit tests passed, including malformed/legacy configs, command quoting,
  ownership collisions, config mismatch, container reuse and explicit recreation,
  failure ordering, immutable IDs, stdin preservation, and exit-code propagation.
- Coverage with branches enabled: 96% overall. This is measured test coverage,
  not a guarantee of correctness.
- Ruff lint/format checks, distribution build, and Skill metadata validation
  passed. Installing the built wheel in a fresh environment and running remote
  doctor against both targets also passed. CI repeats lint, unit tests and
  distribution builds on Python 3.11/3.13.

Run locally:

```bash
uv run python -m unittest discover -s tests -v
uv run --with coverage coverage run --branch --source=anchorrun -m unittest discover -s tests -q
uv run --with coverage coverage report -m
uvx ruff check .
uv build
```

## Actual two-machine run

Used target labels `r9700` and `halo4`, different SSH machines, independent
temporary remote roots under `/tmp/anchorrun-v2-smoke.<random>`, and pinned cached
development images containing Python and Git. Runtime access used the existing
SSH identities; no credentials or project source were copied into the repository.
Containers ran with each remote user's numeric UID:GID.

| Check | r9700 | halo4 |
| --- | --- | --- |
| Prepare and remote doctor | Pass | Pass |
| Repeated prepare retains container ID | Pass | Pass |
| Working directory maps to the selected remote root | Pass | Pass |
| Create/read source through remote stdin/exec | Pass | Pass |
| Initialize Git, check/apply a patch, read diff | Pass | Pass |
| Invalid patch is rejected without changing the file | Pass | Pass |
| Container-only file survives repeated prepare | Pass | Pass |
| Stopped container resumes with the same ID and preserved writable layer | Pass | Pass |
| 32,768-byte binary stdin round trip | Pass | Pass |
| Separate stdout/stderr and remote exit code 37 | Pass | Pass |
| Literal shell-sensitive arguments remain unchanged | Pass | Pass |
| Other target's fixture is absent | Pass | Pass |

Selecting either target did not change `default_target`. The local entry
directory still contained exactly its original config. The test used new fixture
directories; no existing project or running project container was changed.

An additional live configuration-change check on the disposable halo4 container
confirmed that normal prepare rejects a changed image. Explicit `--recreate`
then replaced that test container successfully.

After validation, both dedicated test containers were stopped. Their writable
layers and bind-mounted fixtures were retained for inspection. Ordinary
`prepare` can resume them; no production container was stopped or replaced.

## Reproduce safely

Create a disposable config-only local directory with exactly two distinct SSH
targets and fresh, dedicated remote roots whose basenames start with
`anchorrun-v2-smoke.`. Use images containing Python 3 and Git. Set container user
and devices appropriately for your machines. Then run:

```bash
uv run python -m tests.remote_smoke --config /path/to/disposable-entry/.anchorrun.yaml
```

The runner prints a JSON report with actual container IDs and check results.
It leaves remote fixtures and containers for inspection; cleanup is explicit.
Never use production project roots for this test.

## Limits of this evidence

- Both live machines used Docker. Podman command construction and bare image-ID
  normalization are unit-tested, but this release has not had a live Podman run.
- The test proves the remote file/edit/execute workflow, not GPU performance or
  training correctness. It does not claim cross-host source synchronization.
- SSH disconnection recovery, long-task scheduling and automatic rollback are
  outside the v2 scope.
- Source is not synchronized locally, but requested file contents, commands and
  results pass through the local agent and may enter its model context.
