# AnchorRun

A Skill that reads a project's `.anchorrun.yaml` and guides an AI agent to run
commands on the right remote machine, in the right host directory or existing
Docker container. Source and Git stay remote; the local folder can contain only
the config.

There is no AnchorRun CLI or Python package to install. SSH and Docker do the
execution; the Skill supplies the location and operating rules. It does not
create environments, manage containers, synchronize files or schedule jobs.

## Use

Install the complete [skills/anchorrun](skills/anchorrun) directory in your agent's
supported skill location. Place [the example config](examples/anchorrun.yaml) in
your project entry directory as `.anchorrun.yaml`, replacing the illustrative
values. The agent must have local command execution and SSH access.

```text
请使用 AnchorRun Skill，读取当前目录的 .anchorrun.yaml。
在默认目标的配置目录里检查 Git 状态，并运行项目测试。
```

The [self-contained Skill](skills/anchorrun/SKILL.md) defines the configuration
and execution rules. It guides agent behavior; it does not intercept local file
tools or guarantee that every agent follows the instructions. Requested remote
file contents and results may enter the local agent/model context.

Licensed under [Apache-2.0](LICENSE).
