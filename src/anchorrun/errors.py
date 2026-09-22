from __future__ import annotations


class AnchorRunError(Exception):
    """Base class for expected user-facing errors."""


class ConfigError(AnchorRunError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


class CommandError(AnchorRunError):
    def __init__(self, command_name: str, returncode: int) -> None:
        super().__init__(f"{command_name} failed with exit code {returncode}")
        self.command_name = command_name
        self.returncode = returncode


class CommandStartError(AnchorRunError):
    def __init__(self, command_name: str, reason: str) -> None:
        super().__init__(f"{command_name} could not start: {reason}")
        self.command_name = command_name
        self.reason = reason
