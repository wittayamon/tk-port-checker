"""Per-user Windows startup registration without Tk or administrator access.

Only frozen builds may register themselves.  This prevents a development
checkout (and its Python interpreter path) from being persisted accidentally.
Registry access is injectable so unit tests never touch the user's profile.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

try:  # Importing this module must remain safe on non-Windows test hosts.
    import winreg as _winreg
except ImportError:  # pragma: no cover - exercised on non-Windows CI
    _winreg = None


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MultiPortChecker"
START_HIDDEN_ARGUMENT = "--start-hidden"


@dataclass(frozen=True)
class StartupStatus:
    """Structured, UI-independent result for a startup registry operation."""

    supported: bool
    success: bool
    enabled: bool
    command_valid: bool
    command: Optional[str] = None
    summary: str = ""
    error: Optional[str] = None


def startup_hidden_from_config(config) -> bool:
    """Read the optional preference while preserving old config compatibility."""
    if not isinstance(config, dict):
        return False
    value = config.get("start_hidden_on_windows_startup", False)
    return value if isinstance(value, bool) else False


def startup_requested_hidden(argv=None) -> bool:
    """Recognize the one packaging-safe CLI switch and ignore unrelated args."""
    return START_HIDDEN_ARGUMENT in list(sys.argv[1:] if argv is None else argv)


def apply_start_hidden_window(window, *, requested: bool, tray_available: bool) -> bool:
    """Withdraw the existing root only when its restore path (tray) is ready."""
    if not requested or not tray_available:
        return False
    window.withdraw()
    return True


def _is_supported(platform_name=None, frozen=None) -> bool:
    platform_value = sys.platform if platform_name is None else platform_name
    frozen_value = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    return platform_value == "win32" and frozen_value


def _quote_windows_executable(path: str) -> str:
    # Windows Run values are command lines, so always quote the executable even
    # when its current path has no spaces; a later install path may have them.
    return '"' + path.replace('"', '\\"') + '"'


def build_startup_command(
    executable_path=None, *, start_hidden=True, frozen=None, platform_name=None
) -> str:
    """Build the canonical frozen-EXE Run command or raise on unsupported use."""
    if not _is_supported(platform_name, frozen):
        raise RuntimeError("Windows startup is available only in the packaged application")
    path = os.path.abspath(executable_path or sys.executable)
    if not path or '"' in path:
        raise ValueError("The application executable path is invalid")
    command = _quote_windows_executable(path)
    if start_hidden:
        command += f" {START_HIDDEN_ARGUMENT}"
    return command


def _unsupported() -> StartupStatus:
    return StartupStatus(
        False, False, False, False,
        summary="Available only in the packaged Windows application",
        error="unsupported",
    )


def get_startup_command(
    *, registry=None, frozen=None, platform_name=None
) -> Optional[str]:
    """Return the current-user Run value, or ``None`` when absent/unavailable."""
    if not _is_supported(platform_name, frozen):
        return None
    registry = _winreg if registry is None else registry
    if registry is None:
        return None
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_READ) as key:
            value, _kind = registry.QueryValueEx(key, VALUE_NAME)
        return value if isinstance(value, str) else None
    except FileNotFoundError:
        return None


def is_startup_enabled(
    *, start_hidden=True, executable_path=None, registry=None, frozen=None,
    platform_name=None, path_exists=os.path.isfile,
) -> StartupStatus:
    """Inspect registry state and validate it against the current frozen EXE."""
    if not _is_supported(platform_name, frozen):
        return _unsupported()
    try:
        expected = build_startup_command(
            executable_path, start_hidden=start_hidden, frozen=True,
            platform_name="win32",
        )
        command = get_startup_command(
            registry=registry, frozen=True, platform_name="win32"
        )
        if command is None:
            return StartupStatus(True, True, False, True, summary="Disabled")
        executable = os.path.abspath(executable_path or sys.executable)
        valid = command == expected and bool(path_exists(executable))
        return StartupStatus(
            True, True, True, valid, command=command,
            summary="Enabled" if valid else "Enabled, but the command is stale or invalid",
        )
    except (OSError, ValueError, RuntimeError) as exc:
        return StartupStatus(
            True, False, False, False, summary="Unable to read Windows startup settings",
            error=type(exc).__name__,
        )


def enable_startup(
    *, start_hidden=True, executable_path=None, registry=None, frozen=None,
    platform_name=None, path_exists=os.path.isfile,
) -> StartupStatus:
    """Create/update the HKCU Run value; HKLM and elevation are never used."""
    if not _is_supported(platform_name, frozen):
        return _unsupported()
    registry = _winreg if registry is None else registry
    try:
        command = build_startup_command(
            executable_path, start_hidden=start_hidden, frozen=True,
            platform_name="win32",
        )
        executable = os.path.abspath(executable_path or sys.executable)
        if not path_exists(executable):
            raise ValueError("The application executable is unavailable")
        with registry.CreateKeyEx(
            registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE
        ) as key:
            registry.SetValueEx(key, VALUE_NAME, 0, registry.REG_SZ, command)
        return StartupStatus(True, True, True, True, command, "Enabled")
    except (AttributeError, OSError, ValueError, RuntimeError) as exc:
        return StartupStatus(
            True, False, False, False, summary="Unable to enable Windows startup",
            error=type(exc).__name__,
        )


def disable_startup(*, registry=None, frozen=None, platform_name=None) -> StartupStatus:
    """Remove the per-user value idempotently without changing other Run items."""
    if not _is_supported(platform_name, frozen):
        return _unsupported()
    registry = _winreg if registry is None else registry
    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE
        ) as key:
            try:
                registry.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        return StartupStatus(True, True, False, True, summary="Disabled")
    except FileNotFoundError:
        return StartupStatus(True, True, False, True, summary="Disabled")
    except (AttributeError, OSError) as exc:
        return StartupStatus(
            True, False, False, False, summary="Unable to disable Windows startup",
            error=type(exc).__name__,
        )
