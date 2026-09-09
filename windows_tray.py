"""Native Windows notification-area support with no third-party dependencies."""

import ctypes
import os
import queue
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Mapping, Optional


TRAY_ACTION_OPEN = "open"
TRAY_ACTION_CHECK_ALL = "check_all"
TRAY_ACTION_START_AUTO = "start_auto"
TRAY_ACTION_STOP_AUTO = "stop_auto"
TRAY_ACTION_EVENT_HISTORY = "event_history"
TRAY_ACTION_AVAILABILITY_REPORT = "availability_report"
TRAY_ACTION_NOTIFICATION_SETTINGS = "notification_settings"
TRAY_ACTION_NOTIFICATION_HISTORY = "notification_history"
TRAY_ACTION_EXIT = "exit"

TRAY_MENU_ACTIONS = {
    1001: TRAY_ACTION_OPEN,
    1002: TRAY_ACTION_CHECK_ALL,
    1003: TRAY_ACTION_START_AUTO,
    1004: TRAY_ACTION_STOP_AUTO,
    1005: TRAY_ACTION_EVENT_HISTORY,
    1006: TRAY_ACTION_NOTIFICATION_SETTINGS,
    1007: TRAY_ACTION_NOTIFICATION_HISTORY,
    1008: TRAY_ACTION_AVAILABILITY_REPORT,
    1009: TRAY_ACTION_EXIT,
}


@dataclass(frozen=True)
class TrayPreferences:
    minimize_to_tray: bool = False
    close_to_tray: bool = True


def _optional_bool(config: Mapping, key: str, default: bool) -> bool:
    value = config.get(key, default)
    return value if isinstance(value, bool) else default


def tray_preferences_from_config(config: Mapping) -> TrayPreferences:
    """Load optional tray settings without breaking older or malformed configs."""
    if not isinstance(config, Mapping):
        return TrayPreferences()
    return TrayPreferences(
        minimize_to_tray=_optional_bool(config, "minimize_to_tray", False),
        close_to_tray=_optional_bool(config, "close_to_tray", True),
    )


def should_close_to_tray(
    close_to_tray: bool, tray_available: bool, *, real_exit: bool = False
) -> bool:
    """Return whether a main-window close request should hide instead of exit."""
    return bool(close_to_tray and tray_available and not real_exit)


def tray_menu_state(auto_running: bool) -> dict:
    """Return UI-independent enablement for the Auto Refresh tray actions."""
    return {
        TRAY_ACTION_START_AUTO: not bool(auto_running),
        TRAY_ACTION_STOP_AUTO: bool(auto_running),
    }


def tray_icon_relative_path() -> str:
    return os.path.join("assets", "icon_network_transparent.ico")


class ShutdownGuard:
    """Allow exactly one caller to enter the canonical shutdown path."""

    def __init__(self):
        self._lock = threading.Lock()
        self._started = False

    def begin(self) -> bool:
        with self._lock:
            if self._started:
                return False
            self._started = True
            return True

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started


class WindowsTrayIcon:
    """Thin Shell_NotifyIcon wrapper running one native message loop thread.

    Native callbacks cross a Windows message-loop boundary and therefore only
    dispatch symbolic actions; the application queue marshals them back to Tk.
    """

    def __init__(self, icon_path: str, dispatch: Callable[[str], None]):
        self.icon_path = os.path.abspath(icon_path)
        self._dispatch = dispatch
        self._state_lock = threading.Lock()
        self._auto_running = False
        self._lifecycle_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._hwnd = None
        self._running = False
        self._notification_queue = queue.Queue(maxsize=64)
        self.startup_error: Optional[str] = None

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return self._running

    def update_state(self, *, auto_running: bool) -> None:
        with self._state_lock:
            self._auto_running = bool(auto_running)

    def health_summary(self) -> dict:
        """Return stable lifecycle facts without exposing Win32 callback state."""
        with self._lifecycle_lock:
            thread = self._thread
            running = self._running
            icon_registered = bool(self._hwnd and self._running)
        return {
            "thread_alive": bool(thread and thread.is_alive()),
            "icon_registered": icon_registered,
            "running": running,
            "shutdown_requested": bool(thread and not thread.is_alive() and not running),
        }

    def start(self, timeout: float = 5.0) -> bool:
        if sys.platform != "win32":
            self.startup_error = "Windows notification area is unavailable"
            return False
        with self._lifecycle_lock:
            if self._running:
                return True
            if self._thread is not None and self._thread.is_alive():
                return False
            self._ready.clear()
            self.startup_error = None
            self._thread = threading.Thread(
                target=self._run,
                name="windows-tray",
                daemon=True,
            )
            self._thread.start()
        self._ready.wait(timeout)
        return self.running

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            hwnd = self._hwnd
        if hwnd:
            post_message = ctypes.windll.user32.PostMessageW
            post_message.argtypes = (
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            post_message.restype = wintypes.BOOL
            post_message(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def show_notification(self, title: str, message: str, warning: bool = False) -> bool:
        """Queue a native balloon without calling Shell APIs from the caller thread."""
        with self._lifecycle_lock:
            hwnd = self._hwnd
            running = self._running
        if not running or not hwnd:
            return False
        try:
            self._notification_queue.put_nowait(
                (str(title)[:63], str(message)[:255], bool(warning))
            )
        except queue.Full:
            return False
        post_message = ctypes.windll.user32.PostMessageW
        post_message.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        post_message.restype = wintypes.BOOL
        return bool(post_message(hwnd, 0x8002, 0, 0))

    def _run(self) -> None:
        try:
            self._run_windows()
        except Exception as exc:
            self.startup_error = str(exc)
            self._ready.set()
        finally:
            with self._lifecycle_lock:
                self._running = False
                self._hwnd = None
            self._ready.set()

    def _run_windows(self) -> None:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        WM_APP = 0x8000
        WM_TRAYICON = WM_APP + 1
        WM_SHOW_NOTIFICATION = WM_APP + 2
        WM_CLOSE = 0x0010
        WM_DESTROY = 0x0002
        WM_COMMAND = 0x0111
        WM_LBUTTONDBLCLK = 0x0203
        WM_RBUTTONUP = 0x0205
        WM_CONTEXTMENU = 0x007B
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        NIM_ADD = 0x00000000
        NIM_MODIFY = 0x00000001
        NIM_DELETE = 0x00000002
        NIM_SETVERSION = 0x00000004
        NIF_MESSAGE = 0x00000001
        NIF_ICON = 0x00000002
        NIF_TIP = 0x00000004
        NIF_INFO = 0x00000010
        NIIF_INFO = 0x00000001
        NIIF_WARNING = 0x00000002
        NOTIFYICON_VERSION_4 = 4

        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = (
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            )

        class GUID(ctypes.Structure):
            _fields_ = (
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            )

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = (
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID),
                ("hBalloonIcon", wintypes.HICON),
            )

        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = (
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        )
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.LoadImageW.argtypes = (
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        )
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.TrackPopupMenu.restype = wintypes.UINT
        user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = (wintypes.HWND,)
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.IsWindow.argtypes = (wintypes.HWND,)
        user32.IsWindow.restype = wintypes.BOOL
        user32.DestroyIcon.argtypes = (wintypes.HICON,)
        user32.DestroyIcon.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        shell32.Shell_NotifyIconW.argtypes = (
            wintypes.DWORD,
            ctypes.c_void_p,
        )
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        class_name = f"MultiPortCheckerTray_{id(self):x}"
        taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        notify_data = NOTIFYICONDATAW()
        icon_handle = None
        icon_added = False
        hwnd = None

        def add_icon() -> bool:
            nonlocal icon_added
            notify_data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            notify_data.hWnd = self._hwnd
            notify_data.uID = 1
            notify_data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            notify_data.uCallbackMessage = WM_TRAYICON
            notify_data.hIcon = icon_handle
            notify_data.szTip = "MultiPortChecker"
            icon_added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(notify_data)))
            if icon_added:
                notify_data.uVersion = NOTIFYICON_VERSION_4
                shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(notify_data))
            return icon_added

        def window_proc(hwnd, message, wparam, lparam):
            nonlocal icon_added
            if message == taskbar_created:
                add_icon()
                return 0
            if message == WM_TRAYICON:
                mouse_message = int(lparam) & 0xFFFF
                if mouse_message == WM_LBUTTONDBLCLK:
                    self._dispatch(TRAY_ACTION_OPEN)
                    return 0
                if mouse_message in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu(hwnd, user32)
                    return 0
            if message == WM_SHOW_NOTIFICATION:
                try:
                    title, body, warning = self._notification_queue.get_nowait()
                except queue.Empty:
                    return 0
                notify_data.uFlags = NIF_INFO
                notify_data.szInfoTitle = title
                notify_data.szInfo = body
                notify_data.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(notify_data))
                return 0
            if message == WM_COMMAND:
                action = TRAY_MENU_ACTIONS.get(int(wparam) & 0xFFFF)
                if action:
                    self._dispatch(action)
                    return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                if icon_added:
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(notify_data))
                    icon_added = False
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._wndproc = WNDPROC(window_proc)
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = instance
        window_class.lpszClassName = class_name
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom:
            raise ctypes.WinError()

        try:
            hwnd = user32.CreateWindowExW(
                0, class_name, "MultiPortChecker Tray", 0, 0, 0, 0, 0,
                None, None, instance, None,
            )
            if not hwnd:
                raise ctypes.WinError()
            with self._lifecycle_lock:
                self._hwnd = hwnd

            icon_handle = user32.LoadImageW(
                None,
                self.icon_path,
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if not icon_handle:
                raise OSError("Unable to load the notification-area icon resource")
            if not add_icon():
                raise OSError("Unable to add the notification-area icon")

            with self._lifecycle_lock:
                self._running = True
            self._ready.set()

            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError()
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if icon_added:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(notify_data))
            if hwnd and user32.IsWindow(hwnd):
                user32.DestroyWindow(hwnd)
            if icon_handle:
                user32.DestroyIcon(icon_handle)
            user32.UnregisterClassW(class_name, instance)

    def _show_menu(self, hwnd, user32) -> None:
        MF_STRING = 0x00000000
        MF_GRAYED = 0x00000001
        MF_SEPARATOR = 0x00000800
        TPM_RIGHTBUTTON = 0x0002
        TPM_RETURNCMD = 0x0100

        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            with self._state_lock:
                states = tray_menu_state(self._auto_running)

            def add_item(command_id: int, label: str, enabled: bool = True) -> None:
                flags = MF_STRING if enabled else MF_STRING | MF_GRAYED
                user32.AppendMenuW(menu, flags, command_id, label)

            add_item(1001, "Open MultiPortChecker")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            add_item(1002, "Check All")
            add_item(1003, "Start Auto Refresh", states[TRAY_ACTION_START_AUTO])
            add_item(1004, "Stop Auto Refresh", states[TRAY_ACTION_STOP_AUTO])
            add_item(1005, "Event History")
            add_item(1008, "Availability Report")
            add_item(1006, "Notification Settings")
            add_item(1007, "Notification History")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            add_item(1009, "Exit")

            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(hwnd)
            command_id = user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD,
                point.x,
                point.y,
                0,
                hwnd,
                None,
            )
            action = TRAY_MENU_ACTIONS.get(int(command_id))
            if action:
                self._dispatch(action)
            user32.PostMessageW(hwnd, 0, 0, 0)
        finally:
            user32.DestroyMenu(menu)
