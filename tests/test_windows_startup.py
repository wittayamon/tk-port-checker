import os
import unittest

from windows_startup import (
    RUN_KEY,
    START_HIDDEN_ARGUMENT,
    VALUE_NAME,
    apply_start_hidden_window, build_startup_command,
    disable_startup,
    enable_startup,
    is_startup_enabled,
    startup_hidden_from_config,
    startup_requested_hidden,
)


class _Key:
    def __init__(self, registry):
        self.registry = registry
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False


class FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.writes = []
        self.deletes = []

    def OpenKey(self, root, key, _reserved, access):
        if self.error:
            raise self.error
        if self.value is None and access == self.KEY_READ:
            raise FileNotFoundError
        return _Key(self)

    def CreateKeyEx(self, root, key, _reserved, access):
        if self.error:
            raise self.error
        return _Key(self)

    def QueryValueEx(self, _key, name):
        if self.value is None:
            raise FileNotFoundError
        return self.value, self.REG_SZ

    def SetValueEx(self, _key, name, _reserved, kind, value):
        self.value = value
        self.writes.append((name, kind, value))

    def DeleteValue(self, _key, name):
        if self.value is None:
            raise FileNotFoundError
        self.value = None
        self.deletes.append(name)


class WindowsStartupTests(unittest.TestCase):
    exe = r"C:\Program Files\MultiPortChecker\MultiPortChecker.exe"

    def command(self, **kwargs):
        return build_startup_command(
            self.exe, frozen=True, platform_name="win32", **kwargs
        )

    def test_01_executable_is_quoted(self):
        self.assertTrue(self.command().startswith('"'))

    def test_02_path_with_spaces_is_one_quoted_argument(self):
        self.assertIn(f'"{self.exe}"', self.command())

    def test_03_hidden_argument_is_included(self):
        self.assertTrue(self.command().endswith(START_HIDDEN_ARGUMENT))

    def test_04_hidden_argument_can_be_omitted(self):
        self.assertNotIn(START_HIDDEN_ARGUMENT, self.command(start_hidden=False))

    def test_05_enable_writes_expected_hkcu_value(self):
        registry = FakeRegistry()
        result = enable_startup(
            executable_path=self.exe, registry=registry, frozen=True,
            platform_name="win32", path_exists=lambda _path: True,
        )
        self.assertTrue(result.success)
        self.assertEqual(registry.writes[0][0], VALUE_NAME)

    def test_06_enable_uses_expected_run_key(self):
        self.assertEqual(RUN_KEY, r"Software\Microsoft\Windows\CurrentVersion\Run")

    def test_07_disable_removes_only_expected_value(self):
        registry = FakeRegistry(self.command())
        result = disable_startup(registry=registry, frozen=True, platform_name="win32")
        self.assertTrue(result.success)
        self.assertEqual(registry.deletes, [VALUE_NAME])

    def test_08_missing_value_is_disabled(self):
        result = is_startup_enabled(
            executable_path=self.exe, registry=FakeRegistry(), frozen=True,
            platform_name="win32", path_exists=lambda _path: True,
        )
        self.assertFalse(result.enabled)

    def test_09_stale_path_is_invalid(self):
        registry = FakeRegistry('"C:\\Old\\MultiPortChecker.exe" --start-hidden')
        result = is_startup_enabled(
            executable_path=self.exe, registry=registry, frozen=True,
            platform_name="win32", path_exists=lambda _path: True,
        )
        self.assertTrue(result.enabled)
        self.assertFalse(result.command_valid)

    def test_10_missing_executable_is_invalid(self):
        registry = FakeRegistry(self.command())
        result = is_startup_enabled(
            executable_path=self.exe, registry=registry, frozen=True,
            platform_name="win32", path_exists=lambda _path: False,
        )
        self.assertFalse(result.command_valid)

    def test_11_malformed_non_string_value_is_disabled(self):
        result = is_startup_enabled(
            executable_path=self.exe, registry=FakeRegistry(123), frozen=True,
            platform_name="win32", path_exists=lambda _path: True,
        )
        self.assertFalse(result.enabled)

    def test_12_permission_read_error_is_structured(self):
        result = is_startup_enabled(
            executable_path=self.exe, registry=FakeRegistry(error=PermissionError()),
            frozen=True, platform_name="win32",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "PermissionError")

    def test_13_permission_write_error_is_structured(self):
        result = enable_startup(
            executable_path=self.exe, registry=FakeRegistry(error=PermissionError()),
            frozen=True, platform_name="win32", path_exists=lambda _path: True,
        )
        self.assertFalse(result.success)

    def test_14_unsupported_platform(self):
        result = is_startup_enabled(frozen=True, platform_name="linux")
        self.assertFalse(result.supported)

    def test_15_source_mode_does_not_register_python(self):
        result = enable_startup(registry=FakeRegistry(), frozen=False, platform_name="win32")
        self.assertFalse(result.supported)

    def test_16_source_command_is_rejected(self):
        with self.assertRaises(RuntimeError):
            build_startup_command(frozen=False, platform_name="win32")

    def test_17_correct_command_detected(self):
        result = is_startup_enabled(
            executable_path=self.exe, registry=FakeRegistry(self.command()), frozen=True,
            platform_name="win32", path_exists=lambda _path: True,
        )
        self.assertTrue(result.command_valid)

    def test_18_unicode_path(self):
        path = r"C:\แอป\MultiPortChecker.exe"
        command = build_startup_command(path, frozen=True, platform_name="win32")
        self.assertIn("แอป", command)

    def test_19_value_name_is_public_safe_and_stable(self):
        self.assertEqual(VALUE_NAME, "MultiPortChecker")

    def test_20_repeated_enable_is_idempotent(self):
        registry = FakeRegistry()
        for _ in range(2):
            self.assertTrue(enable_startup(
                executable_path=self.exe, registry=registry, frozen=True,
                platform_name="win32", path_exists=lambda _path: True,
            ).success)
        self.assertEqual(registry.writes[-1][2], self.command())

    def test_21_repeated_disable_is_idempotent(self):
        registry = FakeRegistry(self.command())
        self.assertTrue(disable_startup(registry=registry, frozen=True, platform_name="win32").success)
        self.assertTrue(disable_startup(registry=registry, frozen=True, platform_name="win32").success)

    def test_22_hidden_config_default_and_validation(self):
        self.assertFalse(startup_hidden_from_config({}))
        self.assertTrue(startup_hidden_from_config({"start_hidden_on_windows_startup": True}))
        self.assertFalse(startup_hidden_from_config({"start_hidden_on_windows_startup": "yes"}))

    def test_23_cli_hidden_flag(self):
        self.assertTrue(startup_requested_hidden(["--start-hidden"]))
        self.assertFalse(startup_requested_hidden([]))

    def test_24_no_machine_registry_or_admin_path(self):
        self.assertNotIn("HKEY_LOCAL_MACHINE", RUN_KEY)

    def test_25_start_hidden_with_tray_withdraws_existing_root(self):
        class Window:
            withdrawn = False
            def withdraw(self): self.withdrawn = True
        window = Window()
        self.assertTrue(apply_start_hidden_window(window, requested=True, tray_available=True))
        self.assertTrue(window.withdrawn)

    def test_26_normal_launch_does_not_withdraw(self):
        class Window:
            def withdraw(self): raise AssertionError("must remain visible")
        self.assertFalse(apply_start_hidden_window(Window(), requested=False, tray_available=True))

    def test_27_hidden_launch_requires_restore_path(self):
        class Window:
            def withdraw(self): raise AssertionError("must remain visible")
        self.assertFalse(apply_start_hidden_window(Window(), requested=True, tray_available=False))


if __name__ == "__main__":
    unittest.main()
