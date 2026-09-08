import os
import sys
import json
import locale
import queue
import subprocess
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

from availability_report import (
    ConfiguredTarget,
    PERIODS,
    PERIOD_CUSTOM,
    AvailabilityReport,
    build_availability_report,
    export_outages_csv,
    export_summary_csv,
    filter_outages,
    filter_report_rows,
    report_period,
    sort_report_rows,
)
from event_history import EventHistoryStore, EventRecord, export_events_csv
from network_checks import (
    CHECK_WORKERS,
    DEFAULT_TRACE_MAX_HOPS,
    DEFAULT_TRACE_TIMEOUT_MS,
    IPv4ScanPlan,
    build_tracert_command,
    check_target,
    normalize_target_key,
)
from monitoring_state import (
    EVENT_DOWN,
    EVENT_MAINTENANCE_ENDED,
    EVENT_MAINTENANCE_STARTED,
    TcpStateTracker,
    alert_enabled_from_config,
    format_duration,
    make_target_record,
    normalize_target_record,
)
from maintenance import (
    DURATION_OPTIONS,
    MANUAL_DURATION,
    MaintenanceState,
    current_group_list,
    filter_operational_alerts,
    group_matches,
    is_maintenance_active,
    maintenance_has_expired,
    normalize_groups,
    normalize_maintenance,
    start_maintenance,
)
from notification_manager import NotificationManager
from notification_history import NotificationHistoryStore
from notification_models import (
    DeliveryResult,
    NotificationEvent,
    NotificationSettings,
    PROVIDER_GENERIC,
    PROVIDER_TEAMS,
    PROVIDER_WINDOWS,
    notification_settings_from_config,
)
from webhook_notifications import (
    GenericWebhookProvider,
    TeamsWebhookProvider,
    endpoint_is_valid,
)
from windows_notifications import WindowsNotificationProvider
from windows_tray import (
    ShutdownGuard,
    TRAY_ACTION_CHECK_ALL,
    TRAY_ACTION_EVENT_HISTORY,
    TRAY_ACTION_AVAILABILITY_REPORT,
    TRAY_ACTION_EXIT,
    TRAY_ACTION_NOTIFICATION_SETTINGS,
    TRAY_ACTION_NOTIFICATION_HISTORY,
    TRAY_ACTION_OPEN,
    TRAY_ACTION_START_AUTO,
    TRAY_ACTION_STOP_AUTO,
    WindowsTrayIcon,
    should_close_to_tray,
    tray_icon_relative_path,
    tray_preferences_from_config,
)

# ===================== Global flags =====================

auto_running = False
check_in_progress = False
auto_after_id = None
active_checks = []
scan_running = False
scan_plan = None
scan_port = 0
scan_pending = {}
scan_completed = 0
scan_show_all = False
transient_scan_items = set()
editing_item_id = None
target_metadata = {}
target_order = []
maintenance_after_id = None

network_executor = ThreadPoolExecutor(max_workers=CHECK_WORKERS, thread_name_prefix="network-check")
trace_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="trace-route")
availability_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="availability-report")
trace_windows = set()
event_history_windows = set()
availability_report_windows = set()
notification_settings_windows = set()
notification_history_windows = set()
tcp_state_tracker = TcpStateTracker()
event_history_store = None
notification_history_store = None
notification_settings = NotificationSettings()
notification_manager = None
notification_result_queue = queue.Queue()
notification_poll_after_id = None
notification_last_results = {}
tray_action_queue = queue.Queue()
tray_icon = None
tray_poll_after_id = None
tray_available = False
main_window_hidden = False
pending_hidden_alerts = []
shutdown_guard = ShutdownGuard()
current_theme = "light"   # "light" หรือ "dark"

# ไฟล์ config สำหรับจำ theme + host list
CONFIG_NAME = "mpc_config.json"
EVENT_DB_NAME = "events.db"
COL_NAME = 0
COL_HOST = 1
COL_PORT = 2
COL_GROUPS = 3
COL_PING = 4
COL_STATUS = 5
COL_MAINTENANCE = 6


# ===================== Helper =====================

def get_app_dir() -> str:
    """ตำแหน่งโฟลเดอร์โปรแกรม (รองรับทั้ง .py และ .exe)"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path() -> str:
    return os.path.join(get_app_dir(), CONFIG_NAME)


def get_event_db_path() -> str:
    """Return a writable runtime DB path, never the PyInstaller temp directory."""
    return os.path.join(get_app_dir(), EVENT_DB_NAME)


def get_event_history_store():
    global event_history_store
    if event_history_store is None:
        event_history_store = EventHistoryStore(get_event_db_path())
    return event_history_store


def get_notification_history_store():
    global notification_history_store
    if notification_history_store is None:
        notification_history_store = NotificationHistoryStore(get_event_db_path())
    return notification_history_store


def resource_path(relative_path: str) -> str:
    """ใช้หา path resource ตอน run จาก .py หรือ .exe (อ่าน icon)"""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def apply_window_icon(window) -> None:
    """Apply the shared app icon without failing when the resource is unavailable."""
    try:
        window.iconbitmap(resource_path("assets/icon_network_transparent.ico"))
    except Exception:
        pass


def all_persistent_items():
    return [item for item in target_order if item in target_metadata and tree.exists(item)]


def all_known_items():
    items = list(all_persistent_items())
    items.extend(item for item in transient_scan_items if tree.exists(item) and item not in items)
    return items


def maintenance_state_for(item_id) -> MaintenanceState:
    return normalize_maintenance(target_metadata.get(item_id, {}).get("maintenance"))


def maintenance_display(state: MaintenanceState, now=None) -> str:
    if not is_maintenance_active(state, now):
        return "Inactive"
    if state.until is None:
        return "Active (manual)"
    return f"Until {state.until.astimezone():%Y-%m-%d %H:%M}"


def insert_persistent_target(record, *, position="end"):
    clean = normalize_target_record(record)
    item = tree.insert(
        "", position,
        values=(clean["name"], clean["host"], clean["port"],
                ", ".join(clean["groups"]), "N/A", "Not checked",
                maintenance_display(normalize_maintenance(clean["maintenance"]))),
        tags=("unknown",),
    )
    target_metadata[item] = {
        "groups": clean["groups"], "maintenance": clean["maintenance"]
    }
    target_order.append(item)
    return item


def configured_target_records():
    records = []
    for item in all_persistent_items():
        values = tree.item(item, "values")
        metadata = target_metadata[item]
        records.append(make_target_record(
            values[COL_NAME], values[COL_HOST], values[COL_PORT],
            metadata["groups"], metadata["maintenance"],
        ))
    return records


def refresh_group_choices():
    groups = current_group_list(configured_target_records())
    group_filter_combo.configure(values=("All Groups", *groups))
    if group_filter_var.get() != "All Groups" and not any(
        group_filter_var.get().casefold() == group.casefold() for group in groups
    ):
        group_filter_var.set("All Groups")
    for history_window in tuple(event_history_windows):
        if not history_window._closed:
            history_window.group_combo.configure(values=("All Groups", *groups))
    for report_window in tuple(availability_report_windows):
        if not report_window._closed:
            report_window.group_combo.configure(values=("All Groups", *groups))


def configured_groups_by_key():
    result = {}
    for item in all_persistent_items():
        values = tree.item(item, "values")
        try:
            key = normalize_target_key(values[COL_HOST], int(values[COL_PORT]))
        except (TypeError, ValueError):
            continue
        result[key] = tuple(target_metadata[item]["groups"])
    return result


def apply_group_filter(_event=None):
    selected = group_filter_var.get()
    for item in all_persistent_items():
        groups = target_metadata[item]["groups"]
        if group_matches(groups, selected):
            tree.reattach(item, "", target_order.index(item))
        else:
            tree.detach(item)
    # Scan results are transient and stay visible only in the unfiltered view.
    for item in tuple(transient_scan_items):
        if not tree.exists(item):
            continue
        if selected == "All Groups":
            tree.reattach(item, "", "end")
        else:
            tree.detach(item)


# ===================== Logic: add / remove / update =====================

def add_target():
    global editing_item_id
    name = entry_name.get().strip()
    host = entry_host.get().strip()
    port_text = entry_port.get().strip()
    try:
        groups = normalize_groups(entry_groups.get(), strict=True)
    except ValueError as exc:
        messagebox.showwarning("Groups / Tags", str(exc))
        return

    if not host:
        messagebox.showwarning("Input Error", "กรุณาใส่ Host หรือ IP")
        return

    if not port_text.isdigit():
        messagebox.showwarning("Input Error", "Port ต้องเป็นตัวเลขเท่านั้น")
        return

    port = int(port_text)

    if editing_item_id is not None and tree.exists(editing_item_id):
        duplicate_item = find_existing_target(host, port, exclude_item=editing_item_id)
        if duplicate_item is not None:
            messagebox.showwarning(
                "Edit Target", "Another target already uses this Host/IP and Port."
            )
            return
        old_values = tree.item(editing_item_id, "values")
        try:
            old_key = normalize_target_key(
                str(old_values[COL_HOST]), int(old_values[COL_PORT])
            )
        except (TypeError, ValueError):
            old_key = None
        ping_text = old_values[COL_PING]
        status_text = old_values[COL_STATUS]
        previous_state = maintenance_state_for(editing_item_id)
        new_key = normalize_target_key(host, port)
        if old_key != new_key and is_maintenance_active(previous_state):
            end_maintenance_for_item(editing_item_id, end_reason="target edited")
            previous_state = MaintenanceState()
        target_metadata[editing_item_id] = {
            "groups": groups, "maintenance": previous_state.to_config()
        }
        tree.item(
            editing_item_id,
            values=(name, host, port, ", ".join(groups), ping_text, status_text,
                    maintenance_display(previous_state)),
        )
        if old_key != new_key:
            tcp_state_tracker.forget(editing_item_id)
        transient_scan_items.discard(editing_item_id)
        tree.selection_set(editing_item_id)
        finish_editing(clear_entries=False)
        refresh_group_choices()
        apply_group_filter()
        save_config()
        return

    existing_item = find_existing_target(host, port)
    if existing_item is not None:
        values = tree.item(existing_item, "values")
        existing_name = str(values[COL_NAME])
        if name or existing_item in transient_scan_items:
            existing_name = name
        tree.item(
            existing_item,
            values=(
                existing_name,
                values[COL_HOST],
                values[COL_PORT],
                ", ".join(groups),
                values[COL_PING],
                values[COL_STATUS],
                values[COL_MAINTENANCE],
            ),
        )
        if existing_item not in target_metadata:
            target_metadata[existing_item] = {
                "groups": groups, "maintenance": MaintenanceState().to_config()
            }
            target_order.append(existing_item)
        else:
            target_metadata[existing_item]["groups"] = groups
        transient_scan_items.discard(existing_item)
        tree.selection_set(existing_item)
        tree.focus(existing_item)
        tree.see(existing_item)
        refresh_group_choices()
        apply_group_filter()
        save_config()
        return

    insert_persistent_target(make_target_record(name, host, port, groups))
    refresh_group_choices()
    apply_group_filter()
    save_config()


def finish_editing(clear_entries: bool = False):
    global editing_item_id
    editing_item_id = None
    btn_add.config(text="Add")
    if clear_entries:
        entry_name.delete(0, "end")
        entry_groups.delete(0, "end")


def edit_selected():
    global editing_item_id
    selected = tree.selection()
    if len(selected) != 1:
        messagebox.showinfo("Edit Selected", "Please select exactly one target to edit.")
        return
    values = tree.item(selected[0], "values")
    if len(values) < 7 or selected[0] in transient_scan_items:
        return
    editing_item_id = selected[0]
    for entry_widget, value in (
        (entry_name, values[COL_NAME]),
        (entry_host, values[COL_HOST]),
        (entry_port, values[COL_PORT]),
        (entry_groups, values[COL_GROUPS]),
    ):
        entry_widget.delete(0, "end")
        entry_widget.insert(0, value)
    btn_add.config(text="Apply")
    entry_name.focus_set()


def remove_selected():
    selected = tree.selection()
    if not selected:
        messagebox.showinfo("Remove", "กรุณาเลือกอย่างน้อย 1 รายการ")
        return

    for item in selected:
        if item in target_metadata and maintenance_state_for(item).enabled:
            end_maintenance_for_item(item, end_reason="target removed")
        transient_scan_items.discard(item)
        target_metadata.pop(item, None)
        if item in target_order:
            target_order.remove(item)
        tcp_state_tracker.forget(item)
        tree.delete(item)
    if editing_item_id in selected:
        finish_editing(clear_entries=False)
    refresh_group_choices()
    apply_group_filter()
    save_config()


def find_existing_target(host: str, port: int, exclude_item=None):
    """Find an existing row by normalized Host/IP + Port."""
    wanted_key = normalize_target_key(host, port)
    for item_id in all_known_items():
        if item_id == exclude_item:
            continue
        values = tree.item(item_id, "values")
        if len(values) < 3:
            continue
        try:
            existing_key = normalize_target_key(
                str(values[COL_HOST]), int(values[COL_PORT])
            )
        except (TypeError, ValueError):
            continue
        if existing_key == wanted_key:
            return item_id
    return None


def update_row_status(
    item_id: str,
    host: str,
    port: int,
    ping_text: str,
    ok: bool,
    *,
    track_state: bool = True,
):
    """Apply a completed result on Tk's main thread."""
    if not tree.exists(item_id):
        return None
    values = tree.item(item_id, "values")
    if (
        len(values) < 7
        or values[COL_HOST] != host
        or str(values[COL_PORT]) != str(port)
    ):
        return None

    status_text = "✅ ONLINE" if ok else "❌ OFFLINE"
    tag = "online" if ok else "offline"
    tree.item(
        item_id,
        values=(values[COL_NAME], host, port, values[COL_GROUPS], ping_text,
                status_text, values[COL_MAINTENANCE]),
        tags=(tag,),
    )
    if not track_state:
        return None
    event = tcp_state_tracker.observe(
        item_id, ok, persistent=item_id not in transient_scan_items
    )
    if event is None:
        return None
    return {
        "event": event,
        "name": str(values[COL_NAME]).strip(),
        "host": host,
        "port": port,
        "ping": ping_text,
        "maintenance_active": is_maintenance_active(maintenance_state_for(item_id), event.occurred_at),
    }


def show_state_change_alerts(alerts, *, allow_defer=True):
    """Display state changes from Tk's main thread with simple flood protection."""
    if not alerts or not state_change_alerts_var.get():
        return
    if allow_defer and main_window_hidden:
        pending_hidden_alerts.extend(alerts)
        return
    if len(alerts) > 3:
        lines = []
        for alert in alerts:
            identifier = alert["name"] or alert["host"]
            lines.append(
                f'{alert["event"].kind}: {identifier} '
                f'({alert["host"]}:{alert["port"]})'
            )
        messagebox.showwarning(
            "STATE CHANGES",
            f"{len(alerts)} TCP services changed state:\n\n" + "\n".join(lines),
        )
        return

    for alert in alerts:
        event = alert["event"]
        identifier = alert["name"] or alert["host"]
        timestamp = event.occurred_at.strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"Device: {identifier}",
            f'Host: {alert["host"]}',
            f'Port: {alert["port"]}',
            f'Ping: {alert["ping"]}',
        ]
        if event.kind == EVENT_DOWN:
            lines.append(f"Time: {timestamp}")
            messagebox.showwarning("DEVICE DOWN", "\n".join(lines))
        else:
            downtime = (
                format_duration(event.downtime_seconds)
                if event.downtime_seconds is not None
                else "Unknown"
            )
            lines.extend((f"Downtime: {downtime}", f"Time: {timestamp}"))
            messagebox.showinfo("DEVICE RECOVERED", "\n".join(lines))


def persist_state_change_events(alerts):
    """Persist main-thread TCP transitions and refresh any open history windows."""
    if not alerts:
        return
    store = get_event_history_store()
    inserted = False
    for alert in alerts:
        event = EventRecord.from_state_change(
            alert["event"],
            device_name=alert["name"],
            host=alert["host"],
            port=alert["port"],
            ping=alert["ping"],
            suppressed_by_maintenance=alert.get("maintenance_active", False),
        )
        inserted = store.insert(event) or inserted
    if inserted:
        refresh_event_history_windows()


def enqueue_state_change_notifications(alerts):
    """Convert canonical TCP transitions into provider delivery jobs once."""
    if not alerts or notification_manager is None:
        return
    for alert in alerts:
        if alert.get("maintenance_active"):
            continue
        event = NotificationEvent.from_state_change(
            alert["event"],
            device_name=alert["name"],
            host=alert["host"],
            port=alert["port"],
            ping=alert["ping"],
        )
        notification_manager.enqueue(event)


def finish_check_cycle():
    global check_in_progress, active_checks
    check_in_progress = False
    active_checks = []
    btn_check_sel.config(state="normal")
    btn_check_all.config(state="normal")
    if auto_running and auto_after_id is None:
        schedule_next_auto()


def poll_check_cycle():
    """Poll futures and update widgets only from Tk's event loop."""
    if any(not future.done() for _item, _host, _port, future in active_checks):
        root.after(50, poll_check_cycle)
        return

    alerts = []
    for item_id, host, port, future in active_checks:
        try:
            ping_text, port_online = future.result()
        except Exception:
            ping_text, port_online = "Timeout", False
        alert = update_row_status(item_id, host, port, ping_text, port_online)
        if alert is not None:
            alerts.append(alert)
    persist_state_change_events(alerts)
    operational_alerts = filter_operational_alerts(alerts)
    enqueue_state_change_notifications(operational_alerts)
    show_state_change_alerts(operational_alerts)
    finish_check_cycle()


def start_check_cycle(item_ids) -> bool:
    """Capture UI values, then submit a bounded set of background checks."""
    global check_in_progress, active_checks
    if check_in_progress or scan_running:
        return False

    targets = []
    for item_id in item_ids:
        values = tree.item(item_id, "values")
        if len(values) < 3:
            continue
        host, port_text = str(values[COL_HOST]), values[COL_PORT]
        try:
            port = int(port_text)
        except (TypeError, ValueError):
            continue
        targets.append((item_id, host, port))

    if not targets:
        return False

    check_in_progress = True
    btn_check_sel.config(state="disabled")
    btn_check_all.config(state="disabled")
    active_checks = [
        (item_id, host, port, network_executor.submit(check_target, host, port))
        for item_id, host, port in targets
    ]
    root.after(50, poll_check_cycle)
    return True


def check_all():
    items = all_persistent_items()
    if not items:
        messagebox.showinfo("Check All", "ยังไม่มีรายการให้เช็ค")
        return

    start_check_cycle(items)


def check_selected():
    selected = tree.selection()
    if not selected:
        messagebox.showinfo("Check Selected", "กรุณาเลือกรายการที่ต้องการเช็ค")
        return

    start_check_cycle(selected)


# ===================== Planned Maintenance =====================

def selected_persistent_item(title="Maintenance"):
    selected = tree.selection()
    if len(selected) != 1 or selected[0] in transient_scan_items:
        messagebox.showinfo(title, "Please select exactly one persistent target.")
        return None
    return selected[0]


def persist_maintenance_event(item_id, event_type, *, state, end_reason="", occurred_at=None):
    if not tree.exists(item_id):
        return False
    values = tree.item(item_id, "values")
    event = EventRecord.maintenance_event(
        event_type,
        occurred_at=occurred_at or datetime.now().astimezone(),
        device_name=values[COL_NAME], host=values[COL_HOST], port=int(values[COL_PORT]),
        reason=state.reason, until=state.until, end_reason=end_reason,
    )
    inserted = get_event_history_store().insert(event)
    if inserted:
        refresh_event_history_windows()
        refresh_availability_report_windows()
    return inserted


def set_maintenance_for_item(item_id, state, *, persist=True):
    target_metadata[item_id]["maintenance"] = state.to_config()
    values = list(tree.item(item_id, "values"))
    values[COL_MAINTENANCE] = maintenance_display(state)
    tree.item(item_id, values=values)
    if persist:
        save_config()


def begin_maintenance_for_item(item_id, state):
    if is_maintenance_active(maintenance_state_for(item_id)):
        raise ValueError("Maintenance is already active for this target.")
    set_maintenance_for_item(item_id, state, persist=False)
    persist_maintenance_event(item_id, EVENT_MAINTENANCE_STARTED, state=state,
                              occurred_at=state.started_at)
    save_config()


def end_maintenance_for_item(item_id, *, end_reason="manual", occurred_at=None):
    state = maintenance_state_for(item_id)
    if not state.enabled:
        return False
    ended_at = occurred_at or datetime.now().astimezone()
    set_maintenance_for_item(item_id, MaintenanceState(), persist=False)
    persist_maintenance_event(item_id, EVENT_MAINTENANCE_ENDED, state=state,
                              end_reason=end_reason, occurred_at=ended_at)
    save_config()
    return True


class MaintenanceDialog:
    def __init__(self, parent, item_id):
        self.item_id = item_id
        values = tree.item(item_id, "values")
        self.window = tk.Toplevel(parent)
        apply_window_icon(self.window)
        self.window.title("Start Maintenance")
        self.window.resizable(False, False)
        self.frame = tk.Frame(self.window)
        self.frame.pack(padx=16, pady=14)
        self.device_label = tk.Label(
            self.frame, text=f"Device: {values[COL_NAME] or values[COL_HOST]} ({values[COL_HOST]}:{values[COL_PORT]})",
            anchor="w",
        )
        self.device_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.duration_label = tk.Label(self.frame, text="Duration:")
        self.duration_label.grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.duration_var = tk.StringVar(value=MANUAL_DURATION)
        self.duration_combo = ttk.Combobox(
            self.frame, textvariable=self.duration_var, values=DURATION_OPTIONS,
            state="readonly", width=24, style="Maintenance.TCombobox",
        )
        self.duration_combo.grid(row=1, column=1, sticky="ew")
        self.duration_combo.bind("<<ComboboxSelected>>", self.update_custom_state)
        self.custom_label = tk.Label(self.frame, text="Custom End:")
        self.custom_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.custom_var = tk.StringVar(value=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"))
        self.custom_entry = tk.Entry(self.frame, textvariable=self.custom_var, width=27)
        self.custom_entry.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        self.reason_label = tk.Label(self.frame, text="Reason:")
        self.reason_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.reason_var = tk.StringVar()
        self.reason_entry = tk.Entry(self.frame, textvariable=self.reason_var, width=27)
        self.reason_entry.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        self.buttons = tk.Frame(self.frame)
        self.buttons.grid(row=4, column=0, columnspan=2, pady=(14, 0))
        self.start_button = tk.Button(self.buttons, text="Start", width=12, command=self.submit)
        self.start_button.grid(row=0, column=0, padx=4)
        self.cancel_button = tk.Button(self.buttons, text="Cancel", width=12, command=self.window.destroy)
        self.cancel_button.grid(row=0, column=1, padx=4)
        self.update_custom_state()
        self.apply_theme()
        self.window.transient(parent)
        self.window.grab_set()

    def update_custom_state(self, _event=None):
        self.custom_entry.configure(
            state="normal" if self.duration_var.get() == "Custom End Time" else "disabled"
        )

    def submit(self):
        try:
            state = start_maintenance(
                self.duration_var.get(), reason=self.reason_var.get(),
                custom_end=self.custom_var.get(),
            )
            begin_maintenance_for_item(self.item_id, state)
        except ValueError as exc:
            messagebox.showwarning("Start Maintenance", str(exc), parent=self.window)
            return
        self.window.destroy()

    def apply_theme(self):
        palette = get_theme_palette(current_theme)
        self.window.configure(bg=palette["bg"])
        for frame in (self.frame, self.buttons):
            frame.configure(bg=palette["bg"])
        for label in (self.device_label, self.duration_label, self.custom_label, self.reason_label):
            label.configure(bg=palette["bg"], fg=palette["fg"])
        for entry in (self.custom_entry, self.reason_entry):
            entry.configure(bg=palette["entry_bg"], fg=palette["entry_fg"], insertbackground=palette["entry_fg"])
        for button in (self.start_button, self.cancel_button):
            button.configure(bg=palette["button_bg"], fg=palette["fg"])


def start_selected_maintenance():
    item = selected_persistent_item("Start Maintenance")
    if item is None:
        return
    if is_maintenance_active(maintenance_state_for(item)):
        messagebox.showinfo("Start Maintenance", "Maintenance is already active for this target.")
        return
    MaintenanceDialog(root, item)


def end_selected_maintenance():
    item = selected_persistent_item("End Maintenance")
    if item is None:
        return
    if not is_maintenance_active(maintenance_state_for(item)):
        messagebox.showinfo("End Maintenance", "Maintenance is not active for this target.")
        return
    if messagebox.askyesno("End Maintenance", "End maintenance for the selected target?"):
        end_maintenance_for_item(item)


def poll_maintenance_expiry():
    global maintenance_after_id
    maintenance_after_id = None
    if shutdown_guard.started:
        return
    now = datetime.now().astimezone()
    for item in all_persistent_items():
        state = maintenance_state_for(item)
        if maintenance_has_expired(state, now):
            end_maintenance_for_item(item, end_reason="expired", occurred_at=state.until or now)
        elif state.enabled:
            values = list(tree.item(item, "values"))
            values[COL_MAINTENANCE] = maintenance_display(state, now)
            tree.item(item, values=values)
    maintenance_after_id = root.after(15_000, poll_maintenance_expiry)


# ===================== Trace Route =====================

class TraceRouteWindow:
    """Stream one tracert process into a themed Toplevel without blocking Tk."""

    def __init__(self, parent, host: str):
        self.host = host
        self.window = tk.Toplevel(parent)
        apply_window_icon(self.window)
        self.window.title(f"Trace Route - {host}")
        self.window.geometry("760x500")
        self.window.minsize(560, 360)

        self._messages = queue.Queue()
        self._process_lock = threading.Lock()
        self._process = None
        self._future = None
        self._stop_event = None
        self._run_id = 0
        self._running = False
        self._closed = False
        self._poll_after_id = None

        self.details_frame = tk.Frame(self.window)
        self.details_frame.pack(fill="x", padx=10, pady=(10, 5))
        self.destination_label = tk.Label(
            self.details_frame, text=f"Destination: {host}", anchor="w"
        )
        self.destination_label.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self.max_hops_label = tk.Label(self.details_frame, text="Max Hops:")
        self.max_hops_label.grid(row=1, column=0, sticky="w")
        self.max_hops_entry = tk.Entry(self.details_frame, width=8)
        self.max_hops_entry.grid(row=1, column=1, sticky="w", padx=(5, 20))
        self.max_hops_entry.insert(0, str(DEFAULT_TRACE_MAX_HOPS))

        self.timeout_label = tk.Label(self.details_frame, text="Timeout (ms):")
        self.timeout_label.grid(row=1, column=2, sticky="w")
        self.timeout_entry = tk.Entry(self.details_frame, width=10)
        self.timeout_entry.grid(row=1, column=3, sticky="w", padx=(5, 0))
        self.timeout_entry.insert(0, str(DEFAULT_TRACE_TIMEOUT_MS))

        self.output_frame = tk.Frame(self.window)
        self.output_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.output_text = tk.Text(self.output_frame, wrap="none", state="disabled")
        self.output_scroll_y = ttk.Scrollbar(
            self.output_frame, orient="vertical", command=self.output_text.yview
        )
        self.output_scroll_x = ttk.Scrollbar(
            self.output_frame, orient="horizontal", command=self.output_text.xview
        )
        self.output_text.configure(
            yscrollcommand=self.output_scroll_y.set,
            xscrollcommand=self.output_scroll_x.set,
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        self.output_scroll_y.grid(row=0, column=1, sticky="ns")
        self.output_scroll_x.grid(row=1, column=0, sticky="ew")
        self.output_frame.grid_rowconfigure(0, weight=1)
        self.output_frame.grid_columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(self.window, textvariable=self.status_var, anchor="w")
        self.status_label.pack(fill="x", padx=10)

        self.button_frame = tk.Frame(self.window)
        self.button_frame.pack(pady=(5, 10))
        self.run_button = tk.Button(
            self.button_frame, text="Run Again", width=12, command=self.run_trace
        )
        self.run_button.grid(row=0, column=0, padx=4)
        self.stop_button = tk.Button(
            self.button_frame,
            text="Stop",
            width=12,
            state="disabled",
            command=self.stop_trace,
        )
        self.stop_button.grid(row=0, column=1, padx=4)
        self.copy_button = tk.Button(
            self.button_frame, text="Copy", width=12, command=self.copy_output
        )
        self.copy_button.grid(row=0, column=2, padx=4)
        self.close_button = tk.Button(
            self.button_frame, text="Close", width=12, command=self.close
        )
        self.close_button.grid(row=0, column=3, padx=4)

        trace_windows.add(self)
        self.apply_theme(current_theme)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._schedule_poll()
        self.window.after_idle(self.run_trace)

    def _schedule_poll(self):
        if not self._closed:
            self._poll_after_id = self.window.after(50, self._poll_messages)

    def _poll_messages(self):
        if self._closed:
            return
        try:
            while True:
                run_id, message_type, payload = self._messages.get_nowait()
                if run_id != self._run_id:
                    continue
                if message_type == "line":
                    if self._stop_event is None or not self._stop_event.is_set():
                        self._append_output(payload)
                elif message_type == "error":
                    self._append_output(f"\nError: {payload}\n")
                    self.status_var.set("Trace failed")
                elif message_type == "done":
                    self._finish_run(payload)
        except queue.Empty:
            pass
        self._schedule_poll()

    def _append_output(self, text: str):
        if self._closed:
            return
        self.output_text.configure(state="normal")
        self.output_text.insert("end", text)
        self.output_text.see("end")
        self.output_text.configure(state="disabled")

    def _clear_output(self):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    def run_trace(self):
        if self._closed or self._running:
            return
        try:
            command = build_tracert_command(
                self.host, self.max_hops_entry.get(), self.timeout_entry.get()
            )
        except ValueError as exc:
            self.status_var.set(str(exc))
            messagebox.showwarning("Trace Route", str(exc), parent=self.window)
            return

        self._clear_output()
        self._append_output(f"Command: {' '.join(command)}\n\n")
        self._run_id += 1
        run_id = self._run_id
        self._stop_event = threading.Event()
        self._running = True
        self.status_var.set("Tracing...")
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        try:
            self._future = trace_executor.submit(
                self._trace_worker, run_id, command, self._stop_event
            )
        except RuntimeError as exc:
            self._messages.put((run_id, "error", f"Unable to start trace: {exc}"))
            self._messages.put((run_id, "done", "failed"))

    def _trace_worker(self, run_id, command, stop_event):
        process = None
        try:
            if stop_event.is_set():
                self._messages.put((run_id, "done", "stopped"))
                return

            output_encoding = "oem" if os.name == "nt" else locale.getpreferredencoding(False)
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=output_encoding,
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                ),
            )
            with self._process_lock:
                self._process = process

            if stop_event.is_set():
                self._terminate_process(process)

            if process.stdout is not None:
                for line in iter(process.stdout.readline, ""):
                    if stop_event.is_set():
                        break
                    self._messages.put((run_id, "line", line))

            if stop_event.is_set():
                self._terminate_process(process)
                result = "stopped"
            else:
                return_code = process.wait()
                result = "completed" if return_code == 0 else "failed"
                if return_code != 0:
                    self._messages.put(
                        (run_id, "line", f"\ntracert exited with code {return_code}.\n")
                    )
            self._messages.put((run_id, "done", result))
        except FileNotFoundError:
            self._messages.put(
                (run_id, "error", "Windows tracert.exe is not available on this system.")
            )
            self._messages.put((run_id, "done", "failed"))
        except (OSError, ValueError) as exc:
            self._messages.put((run_id, "error", f"Unable to run tracert: {exc}"))
            self._messages.put((run_id, "done", "failed"))
        finally:
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                if process.poll() is None:
                    self._terminate_process(process)
                with self._process_lock:
                    if self._process is process:
                        self._process = None

    @staticmethod
    def _terminate_process(process):
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass

    def _terminate_active_process(self):
        with self._process_lock:
            process = self._process
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass

    def stop_trace(self):
        if not self._running or self._stop_event is None:
            return
        self._stop_event.set()
        self.stop_button.configure(state="disabled")
        self.status_var.set("Stopping trace...")
        self._append_output("\nTrace stopped by user.\n")
        if self._future is not None and self._future.cancel():
            self._finish_run("stopped")
            return
        self._terminate_active_process()

    def _finish_run(self, result: str):
        if not self._running:
            return
        self._running = False
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if result == "completed":
            self.status_var.set("Trace completed")
        elif result == "stopped":
            self.status_var.set("Trace stopped")
        else:
            self.status_var.set("Trace failed; see output above")

    def copy_output(self):
        output = self.output_text.get("1.0", "end-1c")
        if not output:
            self.status_var.set("There is no trace output to copy")
            return
        self.window.clipboard_clear()
        self.window.clipboard_append(output)
        self.status_var.set("Trace output copied to clipboard")

    def apply_theme(self, theme: str):
        if self._closed:
            return
        palette = get_theme_palette(theme)
        for frame in (self.details_frame, self.output_frame, self.button_frame):
            frame.configure(bg=palette["bg"])
        for label in (
            self.destination_label,
            self.max_hops_label,
            self.timeout_label,
            self.status_label,
        ):
            label.configure(bg=palette["bg"], fg=palette["fg"])
        for entry in (self.max_hops_entry, self.timeout_entry):
            entry.configure(
                bg=palette["entry_bg"],
                fg=palette["entry_fg"],
                insertbackground=palette["entry_fg"],
            )
        for button in (
            self.run_button, self.stop_button, self.copy_button, self.close_button
        ):
            button.configure(
                bg=palette["button_bg"],
                fg=palette["fg"],
                activebackground=palette["button_bg"],
                activeforeground=palette["fg"],
            )
        self.output_text.configure(
            bg=palette["tree_bg"],
            fg=palette["tree_fg"],
            insertbackground=palette["entry_fg"],
        )
        self.window.configure(bg=palette["bg"])

    def close(self):
        if self._closed:
            return
        self.stop_trace()
        self._closed = True
        trace_windows.discard(self)
        if self._poll_after_id is not None:
            try:
                self.window.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def open_trace_route():
    selected = tree.selection()
    if not selected:
        messagebox.showinfo("Trace Route", "Please select a Host/IP first.")
        return
    if len(selected) != 1:
        messagebox.showinfo("Trace Route", "Please select only one Host/IP.")
        return
    values = tree.item(selected[0], "values")
    if len(values) < 3 or not str(values[COL_HOST]).strip():
        messagebox.showinfo("Trace Route", "Please select a valid Host/IP.")
        return
    TraceRouteWindow(root, str(values[COL_HOST]).strip())


# ===================== Event History =====================

def format_event_timestamp(timestamp: str) -> str:
    try:
        value = datetime.fromisoformat(timestamp)
        if value.tzinfo is not None:
            value = value.astimezone()
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(timestamp)


class EventHistoryWindow:
    """Display, filter, export, and clear persistent TCP state changes."""

    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        apply_window_icon(self.window)
        self.window.title("Event History")
        self.window.geometry("1040x560")
        self.window.minsize(760, 400)
        self._closed = False

        self.filter_frame = tk.Frame(self.window)
        self.filter_frame.pack(fill="x", padx=10, pady=(10, 5))
        self.search_label = tk.Label(self.filter_frame, text="Device / Host:")
        self.search_label.grid(row=0, column=0, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            self.filter_frame, textvariable=self.search_var, width=28
        )
        self.search_entry.grid(row=0, column=1, padx=(0, 12))
        self.search_entry.bind("<Return>", lambda _event: self.refresh())

        self.type_label = tk.Label(self.filter_frame, text="Event Type:")
        self.type_label.grid(row=0, column=2, padx=(0, 5))
        self.type_var = tk.StringVar(value="All")
        self.type_combo = ttk.Combobox(
            self.filter_frame,
            textvariable=self.type_var,
            values=("All", "DOWN", "RECOVERED", "MAINTENANCE_STARTED", "MAINTENANCE_ENDED"),
            state="readonly",
            style="History.TCombobox",
            width=23,
        )
        self.type_combo.grid(row=0, column=3, padx=(0, 12))
        self.type_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        self.group_label = tk.Label(self.filter_frame, text="Group:")
        self.group_label.grid(row=0, column=4, padx=(0, 5))
        self.group_var = tk.StringVar(value="All Groups")
        self.group_combo = ttk.Combobox(
            self.filter_frame, textvariable=self.group_var,
            values=("All Groups", *current_group_list(configured_target_records())),
            state="readonly", style="History.TCombobox", width=16,
        )
        self.group_combo.grid(row=0, column=5, padx=(0, 12))
        self.group_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        self.filter_button = tk.Button(
            self.filter_frame, text="Apply Filter", width=12, command=self.refresh
        )
        self.filter_button.grid(row=0, column=6, padx=(0, 5))
        self.reset_button = tk.Button(
            self.filter_frame, text="Reset", width=10, command=self.reset_filters
        )
        self.reset_button.grid(row=0, column=7)

        self.table_frame = tk.Frame(self.window)
        self.table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        columns = ("timestamp", "device", "host", "port", "event", "details", "downtime")
        self.tree = ttk.Treeview(
            self.table_frame,
            columns=columns,
            show="headings",
            style="History.Treeview",
        )
        headings = {
            "timestamp": "Date / Time",
            "device": "Device",
            "host": "Host / IP",
            "port": "Port",
            "event": "Event",
            "details": "Ping / Maintenance Details",
            "downtime": "Downtime",
        }
        widths = {
            "timestamp": 155,
            "device": 145,
            "host": 170,
            "port": 65,
            "event": 175,
            "details": 210,
            "downtime": 95,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                anchor="center" if column in ("port", "event", "downtime") else "w",
            )
        self.scroll_y = ttk.Scrollbar(
            self.table_frame, orient="vertical", command=self.tree.yview
        )
        self.scroll_x = ttk.Scrollbar(
            self.table_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        self.scroll_x.grid(row=1, column=0, sticky="ew")
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            self.window, textvariable=self.status_var, anchor="w"
        )
        self.status_label.pack(fill="x", padx=10)

        self.button_frame = tk.Frame(self.window)
        self.button_frame.pack(pady=(5, 10))
        self.export_button = tk.Button(
            self.button_frame, text="Export CSV", width=14, command=self.export_csv
        )
        self.export_button.grid(row=0, column=0, padx=5)
        self.clear_button = tk.Button(
            self.button_frame, text="Clear History", width=14, command=self.clear_history
        )
        self.clear_button.grid(row=0, column=1, padx=5)
        self.close_button = tk.Button(
            self.button_frame, text="Close", width=14, command=self.close
        )
        self.close_button.grid(row=0, column=2, padx=5)

        event_history_windows.add(self)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_theme(current_theme)
        self.refresh()

    def current_events(self):
        events = get_event_history_store().list_events(
            self.search_var.get(), self.type_var.get()
        )
        selected = self.group_var.get()
        if selected == "All Groups":
            return events
        groups_by_key = configured_groups_by_key()
        return [
            event for event in events
            if group_matches(
                groups_by_key.get(normalize_target_key(event.host, event.port), ()),
                selected,
            )
        ]

    def refresh(self):
        if self._closed:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        store = get_event_history_store()
        events = self.current_events()
        for event in events:
            identifier = event.device_name or event.host
            downtime = (
                "-"
                if event.downtime_seconds is None
                else format_duration(event.downtime_seconds)
            )
            self.tree.insert(
                "",
                "end",
                values=(
                    format_event_timestamp(event.timestamp),
                    identifier,
                    event.host,
                    event.port,
                    event.event_type,
                    event.ping or " | ".join(
                        part for part in (event.maintenance_reason, event.maintenance_end_reason)
                        if part
                    ),
                    downtime,
                ),
                tags=(event.event_type.lower(),),
            )
        if store.available:
            self.status_var.set(f"Showing {len(events)} event(s), newest first")
        else:
            self.status_var.set("Event History is unavailable")

    def reset_filters(self):
        self.search_var.set("")
        self.type_var.set("All")
        self.group_var.set("All Groups")
        self.refresh()

    def export_csv(self):
        events = self.current_events()
        path = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export Event History",
        )
        if not path:
            return
        try:
            count = export_events_csv(path, events)
        except (OSError, UnicodeError) as exc:
            messagebox.showerror(
                "Export CSV", f"Unable to export Event History:\n{exc}", parent=self.window
            )
            return
        messagebox.showinfo(
            "Export CSV", f"Exported {count} event(s).", parent=self.window
        )

    def clear_history(self):
        if not messagebox.askyesno(
            "Clear History",
            "Delete all Event History records?\n\nMonitored targets and settings are not affected.",
            parent=self.window,
        ):
            return
        if get_event_history_store().clear():
            refresh_event_history_windows()
            refresh_availability_report_windows()
            messagebox.showinfo(
                "Clear History", "Event History was cleared.", parent=self.window
            )
        else:
            messagebox.showerror(
                "Clear History", "Unable to clear Event History.", parent=self.window
            )

    def apply_theme(self, theme: str):
        if self._closed:
            return
        palette = get_theme_palette(theme)
        self.window.configure(bg=palette["bg"])
        for frame in (self.filter_frame, self.table_frame, self.button_frame):
            frame.configure(bg=palette["bg"])
        for label in (self.search_label, self.type_label, self.group_label, self.status_label):
            label.configure(bg=palette["bg"], fg=palette["fg"])
        self.search_entry.configure(
            bg=palette["entry_bg"],
            fg=palette["entry_fg"],
            insertbackground=palette["entry_fg"],
        )
        for button in (
            self.filter_button,
            self.reset_button,
            self.export_button,
            self.clear_button,
            self.close_button,
        ):
            button.configure(
                bg=palette["button_bg"],
                fg=palette["fg"],
                activebackground=palette["button_bg"],
                activeforeground=palette["fg"],
            )
        style = ttk.Style()
        style.configure(
            "History.Treeview",
            background=palette["tree_bg"],
            foreground=palette["tree_fg"],
            fieldbackground=palette["tree_bg"],
        )
        style.configure(
            "History.Treeview.Heading",
            background=palette["button_bg"],
            foreground=palette["fg"],
        )
        style.configure(
            "History.TCombobox",
            fieldbackground=palette["entry_bg"],
            background=palette["button_bg"],
            foreground=palette["entry_fg"],
            arrowcolor=palette["fg"],
        )
        style.map(
            "History.TCombobox",
            fieldbackground=[("readonly", palette["entry_bg"])],
            foreground=[("readonly", palette["entry_fg"])],
        )
        self.tree.tag_configure("down", foreground="#c62828")
        self.tree.tag_configure("recovered", foreground="#2e7d32")
        self.tree.tag_configure("maintenance_started", foreground="#b26a00")
        self.tree.tag_configure("maintenance_ended", foreground="#6a4c00")

    def close(self):
        if self._closed:
            return
        self._closed = True
        event_history_windows.discard(self)
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def refresh_event_history_windows():
    for history_window in tuple(event_history_windows):
        history_window.refresh()


def open_event_history():
    for history_window in tuple(event_history_windows):
        if history_window._closed:
            event_history_windows.discard(history_window)
            continue
        try:
            history_window.window.deiconify()
            history_window.window.lift()
            history_window.window.focus_force()
            history_window.refresh()
            return history_window
        except tk.TclError:
            event_history_windows.discard(history_window)
    return EventHistoryWindow(root)


# ===================== Availability Report =====================

def configured_report_targets():
    """Snapshot persistent targets on Tk's main thread for report workers."""
    targets = []
    for item_id in all_persistent_items():
        values = tree.item(item_id, "values")
        try:
            targets.append(ConfiguredTarget(
                str(values[COL_NAME]), str(values[COL_HOST]), int(values[COL_PORT]),
                tuple(target_metadata[item_id]["groups"]),
            ))
        except (IndexError, TypeError, ValueError):
            continue
    return tuple(targets)


class OutageDetailWindow:
    def __init__(self, report_window):
        self.report_window = report_window
        self.window = tk.Toplevel(report_window.window)
        apply_window_icon(self.window)
        self.window.title("Outage Details")
        self.window.geometry("1120x520")
        self.window.minsize(820, 380)
        self._closed = False
        self.frame = tk.Frame(self.window)
        self.frame.pack(fill="both", expand=True, padx=10, pady=10)
        columns = ("device", "host", "port", "down", "recovered", "duration", "period", "planned", "unplanned", "class", "status")
        self.tree = ttk.Treeview(self.frame, columns=columns, show="headings", style="Availability.Treeview")
        headings = ("Device", "Host / IP", "Port", "Down Time", "Recovered Time", "Actual Duration", "Total Downtime", "Maintenance Overlap", "Unplanned Downtime", "Classification", "Status")
        widths = (130, 145, 55, 150, 150, 95, 95, 125, 115, 90, 80)
        for column, heading, width in zip(columns, headings, widths):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, anchor="center" if column in ("port", "duration", "period", "status") else "w")
        scroll_y = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(self.frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        self.button_frame = tk.Frame(self.window)
        self.button_frame.pack(pady=(0, 10))
        self.export_button = tk.Button(self.button_frame, text="Export Outages CSV", width=20, command=self.export_csv)
        self.export_button.grid(row=0, column=0, padx=5)
        self.close_button = tk.Button(self.button_frame, text="Close", width=14, command=self.close)
        self.close_button.grid(row=0, column=1, padx=5)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_theme(current_theme)
        self.refresh()

    def current_outages(self):
        report = self.report_window.report
        return [] if report is None else filter_outages(report.outages, self.report_window.search_var.get())

    def refresh(self):
        if self._closed:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        for outage in self.current_outages():
            self.tree.insert("", "end", values=(
                outage.device_name or outage.host, outage.host, outage.port,
                outage.down_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                "-" if outage.recovered_at is None else outage.recovered_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                "-" if outage.actual_duration_seconds is None else format_duration(outage.actual_duration_seconds),
                format_duration(outage.period_overlap_seconds),
                format_duration(outage.maintenance_overlap_seconds),
                format_duration(outage.unplanned_downtime_seconds),
                outage.classification, outage.status,
            ), tags=(outage.status.lower(),))

    def export_csv(self):
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Export Outage Details")
        if not path:
            return
        try:
            count = export_outages_csv(path, self.current_outages())
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Export CSV", f"Unable to export Outage Details:\n{exc}", parent=self.window)
            return
        messagebox.showinfo("Export CSV", f"Exported {count} outage(s).", parent=self.window)

    def apply_theme(self, theme):
        palette = get_theme_palette(theme)
        self.window.configure(bg=palette["bg"])
        self.frame.configure(bg=palette["bg"])
        self.button_frame.configure(bg=palette["bg"])
        for button in (self.export_button, self.close_button):
            button.configure(bg=palette["button_bg"], fg=palette["fg"], activebackground=palette["button_bg"], activeforeground=palette["fg"])
        style = ttk.Style()
        style.configure("Availability.Treeview", background=palette["tree_bg"], foreground=palette["tree_fg"], fieldbackground=palette["tree_bg"])
        style.configure("Availability.Treeview.Heading", background=palette["button_bg"], foreground=palette["fg"])
        self.tree.tag_configure("ongoing", foreground="#c62828")
        self.tree.tag_configure("recovered", foreground="#2e7d32")

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.report_window.detail_window = None
        try:
            self.window.destroy()
        except tk.TclError:
            pass


class AvailabilityReportWindow:
    """Themed, reusable, non-blocking view over retained TCP Event History."""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        apply_window_icon(self.window)
        self.window.title("Availability Report")
        self.window.geometry("1180x590")
        self.window.minsize(920, 430)
        self._closed = False
        self._generation = 0
        self._result_queue = queue.Queue()
        self._poll_after_id = None
        self.report = None
        self.display_rows = []
        self.detail_window = None
        self.sort_column = "device"
        self.sort_reverse = False

        today = datetime.now().astimezone().date().isoformat()
        self.period_var = tk.StringVar(value=PERIODS[0])
        self.start_var = tk.StringVar(value=today)
        self.end_var = tk.StringVar(value=today)
        self.search_var = tk.StringVar()
        self.group_var = tk.StringVar(value="All Groups")
        self.controls = tk.Frame(self.window)
        self.controls.pack(fill="x", padx=10, pady=10)
        self.period_label = tk.Label(self.controls, text="Period:")
        self.period_label.grid(row=0, column=0, padx=(0, 4))
        self.period_combo = ttk.Combobox(self.controls, textvariable=self.period_var, values=PERIODS, state="readonly", width=12, style="Availability.TCombobox")
        self.period_combo.grid(row=0, column=1, padx=(0, 10))
        self.period_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_custom_state())
        self.start_label = tk.Label(self.controls, text="Start Date:")
        self.start_label.grid(row=0, column=2, padx=(0, 4))
        self.start_entry = tk.Entry(self.controls, textvariable=self.start_var, width=12)
        self.start_entry.grid(row=0, column=3, padx=(0, 10))
        self.end_label = tk.Label(self.controls, text="End Date:")
        self.end_label.grid(row=0, column=4, padx=(0, 4))
        self.end_entry = tk.Entry(self.controls, textvariable=self.end_var, width=12)
        self.end_entry.grid(row=0, column=5, padx=(0, 10))
        self.search_label = tk.Label(self.controls, text="Search:")
        self.search_label.grid(row=0, column=6, padx=(0, 4))
        self.search_entry = tk.Entry(self.controls, textvariable=self.search_var, width=22)
        self.search_entry.grid(row=0, column=7, padx=(0, 8))
        self.refresh_button = tk.Button(self.controls, text="Refresh", width=10, command=self.refresh)
        self.refresh_button.grid(row=0, column=8)
        self.group_label = tk.Label(self.controls, text="Group:")
        self.group_label.grid(row=1, column=0, padx=(0, 4), pady=(8, 0))
        self.group_combo = ttk.Combobox(
            self.controls, textvariable=self.group_var,
            values=("All Groups", *current_group_list(configured_target_records())),
            state="readonly", width=18, style="Availability.TCombobox",
        )
        self.group_combo.grid(row=1, column=1, padx=(0, 10), pady=(8, 0))
        self.group_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_filter())
        self.search_entry.bind("<Return>", lambda _event: self.apply_filter())

        self.kpi_var = tk.StringVar(value="")
        self.kpi_label = tk.Label(self.window, textvariable=self.kpi_var, anchor="w")
        self.kpi_label.pack(fill="x", padx=10, pady=(0, 5))
        self.table_frame = tk.Frame(self.window)
        self.table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        columns = ("device", "host", "port", "raw", "operational", "coverage", "maintenance", "planned", "unplanned", "outages")
        headings = {"device":"Device", "host":"Host / IP", "port":"Port", "raw":"Raw Availability", "operational":"Operational Availability", "coverage":"Coverage", "maintenance":"Planned Maintenance", "planned":"Planned Downtime", "unplanned":"Unplanned Downtime", "outages":"Outages"}
        widths = {"device":130, "host":145, "port":55, "raw":105, "operational":125, "coverage":75, "maintenance":115, "planned":105, "unplanned":115, "outages":65}
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings", style="Availability.Treeview")
        for column in columns:
            command = (lambda col=column: self.sort_by(col)) if column in ("device", "raw", "operational", "unplanned", "outages") else None
            if command is None:
                self.tree.heading(column, text=headings[column])
            else:
                self.tree.heading(column, text=headings[column], command=command)
            self.tree.column(column, width=widths[column], anchor="center" if column not in ("device", "host") else "w")
        scroll_y = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(self.table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(self.window, textvariable=self.status_var, anchor="w")
        self.status_label.pack(fill="x", padx=10)
        self.buttons = tk.Frame(self.window)
        self.buttons.pack(pady=(5, 10))
        self.export_button = tk.Button(self.buttons, text="Export Summary CSV", width=20, command=self.export_csv)
        self.export_button.grid(row=0, column=0, padx=5)
        self.details_button = tk.Button(self.buttons, text="Outage Details", width=16, command=self.open_details)
        self.details_button.grid(row=0, column=1, padx=5)
        self.close_button = tk.Button(self.buttons, text="Close", width=14, command=self.close)
        self.close_button.grid(row=0, column=2, padx=5)
        availability_report_windows.add(self)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._update_custom_state()
        self.apply_theme(current_theme)
        self._poll_after_id = self.window.after(50, self._poll_results)
        self.refresh()

    def _update_custom_state(self):
        state = "normal" if self.period_var.get() == PERIOD_CUSTOM else "disabled"
        self.start_entry.configure(state=state)
        self.end_entry.configure(state=state)

    def refresh(self):
        if self._closed:
            return
        try:
            start, end = report_period(self.period_var.get(), start_date=self.start_var.get(), end_date=self.end_var.get())
        except ValueError as exc:
            messagebox.showwarning("Availability Report", str(exc), parent=self.window)
            return
        self._generation += 1
        generation = self._generation
        targets = configured_report_targets()
        self.refresh_button.configure(state="disabled")
        self.status_var.set("Calculating from retained Event History...")
        future = availability_executor.submit(build_availability_report, get_event_history_store(), start, end, targets)
        future.add_done_callback(lambda completed, token=generation: self._result_queue.put((token, completed)))

    def _poll_results(self):
        self._poll_after_id = None
        if self._closed:
            return
        try:
            while True:
                generation, future = self._result_queue.get_nowait()
                if generation != self._generation:
                    continue
                try:
                    self.report = future.result()
                except Exception as exc:
                    self.status_var.set("Availability Report is unavailable")
                    messagebox.showerror("Availability Report", f"Unable to calculate report:\n{exc}", parent=self.window)
                else:
                    self.apply_filter()
                self.refresh_button.configure(state="normal")
        except queue.Empty:
            pass
        self._poll_after_id = self.window.after(50, self._poll_results)

    def apply_filter(self):
        if self.report is None:
            return
        self.display_rows = filter_report_rows(self.report.rows, self.search_var.get(), self.group_var.get())
        self.display_rows = sort_report_rows(self.display_rows, self.sort_column, self.sort_reverse)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.display_rows:
            self.tree.insert("", "end", values=(
                row.display_name, row.host, row.port,
                "-" if row.availability_percent is None else f"{row.availability_percent:.2f}%",
                "-" if row.operational_availability_percent is None else f"{row.operational_availability_percent:.2f}%",
                f"{row.coverage_percent:.2f}%",
                format_duration(row.planned_maintenance_seconds),
                format_duration(row.planned_downtime_seconds),
                format_duration(row.unplanned_downtime_seconds), row.outage_count,
            ))
        known_rows = [row for row in self.display_rows if row.availability_percent is not None]
        average = "-" if not known_rows else f"{sum(row.availability_percent for row in known_rows) / len(known_rows):.2f}%"
        operational_rows = [row for row in self.display_rows if row.operational_availability_percent is not None]
        operational_average = "-" if not operational_rows else f"{sum(row.operational_availability_percent for row in operational_rows) / len(operational_rows):.2f}%"
        self.kpi_var.set(f"Targets: {len(self.display_rows)}    Raw Avg: {average}    Operational Avg: {operational_average}    Total Downtime: {format_duration(sum(row.downtime_seconds for row in self.display_rows))}")
        self.status_var.set(f"Showing {len(self.display_rows)} target(s) | {self.report.period_start.astimezone():%Y-%m-%d %H:%M:%S} to {self.report.period_end.astimezone():%Y-%m-%d %H:%M:%S}")
        if self.detail_window is not None:
            self.detail_window.refresh()

    def sort_by(self, column):
        mapped = {"raw": "availability"}.get(column, column)
        self.sort_reverse = not self.sort_reverse if self.sort_column == mapped else False
        self.sort_column = mapped
        self.apply_filter()

    def export_csv(self):
        if self.report is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Export Availability Summary")
        if not path:
            return
        try:
            count = export_summary_csv(path, self.display_rows)
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Export CSV", f"Unable to export Availability Summary:\n{exc}", parent=self.window)
            return
        messagebox.showinfo("Export CSV", f"Exported {count} target(s).", parent=self.window)

    def open_details(self):
        if self.report is None:
            return
        if self.detail_window is not None and not self.detail_window._closed:
            self.detail_window.window.deiconify()
            self.detail_window.window.lift()
            self.detail_window.window.focus_force()
            self.detail_window.refresh()
            return
        self.detail_window = OutageDetailWindow(self)

    def apply_theme(self, theme):
        palette = get_theme_palette(theme)
        self.window.configure(bg=palette["bg"])
        for frame in (self.controls, self.table_frame, self.buttons):
            frame.configure(bg=palette["bg"])
        for label in (self.period_label, self.start_label, self.end_label, self.search_label, self.group_label, self.kpi_label, self.status_label):
            label.configure(bg=palette["bg"], fg=palette["fg"])
        for entry in (self.start_entry, self.end_entry, self.search_entry):
            entry.configure(bg=palette["entry_bg"], fg=palette["entry_fg"], insertbackground=palette["entry_fg"])
        for button in (self.refresh_button, self.export_button, self.details_button, self.close_button):
            button.configure(bg=palette["button_bg"], fg=palette["fg"], activebackground=palette["button_bg"], activeforeground=palette["fg"])
        style = ttk.Style()
        style.configure("Availability.Treeview", background=palette["tree_bg"], foreground=palette["tree_fg"], fieldbackground=palette["tree_bg"])
        style.configure("Availability.Treeview.Heading", background=palette["button_bg"], foreground=palette["fg"])
        style.configure("Availability.TCombobox", fieldbackground=palette["entry_bg"], background=palette["button_bg"], foreground=palette["entry_fg"], arrowcolor=palette["fg"])
        style.map("Availability.TCombobox", fieldbackground=[("readonly", palette["entry_bg"])], foreground=[("readonly", palette["entry_fg"])])
        if self.detail_window is not None:
            self.detail_window.apply_theme(theme)

    def close(self):
        if self._closed:
            return
        self._closed = True
        availability_report_windows.discard(self)
        if self.detail_window is not None:
            self.detail_window.close()
        if self._poll_after_id is not None:
            try:
                self.window.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def refresh_availability_report_windows():
    for report_window in tuple(availability_report_windows):
        report_window.refresh()


def open_availability_report():
    for report_window in tuple(availability_report_windows):
        if report_window._closed:
            availability_report_windows.discard(report_window)
            continue
        try:
            report_window.window.deiconify()
            report_window.window.lift()
            report_window.window.focus_force()
            report_window.refresh()
            return report_window
        except tk.TclError:
            availability_report_windows.discard(report_window)
    return AvailabilityReportWindow(root)


# ===================== Notification Delivery History =====================

PROVIDER_LABELS = {
    PROVIDER_WINDOWS: "Windows",
    PROVIDER_GENERIC: "Generic Webhook",
    PROVIDER_TEAMS: "Teams",
}


class NotificationHistoryWindow:
    """Filter and operate on endpoint-free provider delivery records."""

    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        apply_window_icon(self.window)
        self.window.title("Notification Delivery History")
        self.window.geometry("1180x570")
        self.window.minsize(900, 420)
        self._closed = False
        self.search_var = tk.StringVar()
        self.provider_var = tk.StringVar(value="All")
        self.status_filter_var = tk.StringVar(value="All")

        self.filter_frame = tk.Frame(self.window)
        self.filter_frame.pack(fill="x", padx=10, pady=10)
        self.search_label = tk.Label(self.filter_frame, text="Device / Host:")
        self.search_label.grid(row=0, column=0, padx=(0, 4))
        self.search_entry = tk.Entry(self.filter_frame, textvariable=self.search_var, width=24)
        self.search_entry.grid(row=0, column=1, padx=(0, 10))
        self.provider_label = tk.Label(self.filter_frame, text="Provider:")
        self.provider_label.grid(row=0, column=2, padx=(0, 4))
        self.provider_combo = ttk.Combobox(
            self.filter_frame, textvariable=self.provider_var, state="readonly", width=18,
            values=("All", "Windows", "Generic Webhook", "Teams"), style="Delivery.TCombobox"
        )
        self.provider_combo.grid(row=0, column=3, padx=(0, 10))
        self.status_filter_label = tk.Label(self.filter_frame, text="Status:")
        self.status_filter_label.grid(row=0, column=4, padx=(0, 4))
        self.status_combo = ttk.Combobox(
            self.filter_frame, textvariable=self.status_filter_var, state="readonly", width=12,
            values=("All", "QUEUED", "RETRYING", "DELIVERED", "FAILED"),
            style="Delivery.TCombobox",
        )
        self.status_combo.grid(row=0, column=5, padx=(0, 10))
        self.filter_button = tk.Button(self.filter_frame, text="Apply", command=self.refresh)
        self.filter_button.grid(row=0, column=6, padx=4)
        self.reset_button = tk.Button(self.filter_frame, text="Reset", command=self.reset_filters)
        self.reset_button.grid(row=0, column=7, padx=4)
        self.search_entry.bind("<Return>", lambda _event: self.refresh())

        columns = ("time", "device", "event", "provider", "status", "attempts",
                   "last", "next", "error")
        self.table_frame = tk.Frame(self.window)
        self.table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 5))
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings",
                                 style="Delivery.Treeview", selectmode="extended")
        headings = dict(zip(columns, ("Date / Time", "Device", "Event", "Provider", "Status",
                                      "Attempts", "Last Attempt", "Next Retry", "Error")))
        widths = {"time":150, "device":150, "event":85, "provider":130, "status":90,
                  "attempts":65, "last":150, "next":150, "error":180}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="center" if column in
                             ("event", "status", "attempts") else "w")
        scroll_y = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(self.table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)

        self.status_var = tk.StringVar()
        self.status_label = tk.Label(self.window, textvariable=self.status_var, anchor="w")
        self.status_label.pack(fill="x", padx=10)
        self.button_frame = tk.Frame(self.window)
        self.button_frame.pack(pady=(5, 10))
        self.refresh_button = tk.Button(self.button_frame, text="Refresh", width=14, command=self.refresh)
        self.retry_button = tk.Button(self.button_frame, text="Retry Selected", width=14, command=self.retry_selected)
        self.retry_all_button = tk.Button(self.button_frame, text="Retry All Failed", width=14, command=self.retry_all)
        self.clear_button = tk.Button(self.button_frame, text="Clear History", width=14, command=self.clear_history)
        self.close_button = tk.Button(self.button_frame, text="Close", width=14, command=self.close)
        for index, button in enumerate((self.refresh_button, self.retry_button,
                                        self.retry_all_button, self.clear_button, self.close_button)):
            button.grid(row=0, column=index, padx=4)
        notification_history_windows.add(self)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_theme(current_theme)
        self.refresh()

    def _provider_key(self):
        return {"Windows": PROVIDER_WINDOWS, "Generic Webhook": PROVIDER_GENERIC,
                "Teams": PROVIDER_TEAMS}.get(self.provider_var.get(), "All")

    def refresh(self):
        if self._closed:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = get_notification_history_store().list_deliveries(
            self.search_var.get(), self._provider_key(), self.status_filter_var.get()
        )
        for row in rows:
            error = row.last_error_summary or "-"
            self.tree.insert("", "end", iid=str(row.id), values=(
                format_event_timestamp(row.created_at), row.device_name or row.host,
                row.event_type, PROVIDER_LABELS.get(row.provider, row.provider), row.status,
                row.attempt_count, format_event_timestamp(row.last_attempt_at) if row.last_attempt_at else "-",
                format_event_timestamp(row.next_retry_at) if row.next_retry_at else "-", error,
            ), tags=(row.status.lower(),))
        self.status_var.set(f"{len(rows)} delivery record(s). Endpoints are never stored here.")

    def reset_filters(self):
        self.search_var.set("")
        self.provider_var.set("All")
        self.status_filter_var.set("All")
        self.refresh()

    def retry_selected(self):
        if notification_manager is None:
            self.status_var.set("Notification service is unavailable.")
            return
        selected = self.tree.selection()
        queued = sum(notification_manager.retry_selected(int(item)) for item in selected)
        self.status_var.set(f"Queued {queued} failed delivery retry/retries.")
        self.window.after(100, self.refresh)

    def retry_all(self):
        queued = notification_manager.retry_all_failed() if notification_manager else 0
        self.status_var.set(f"Queued {queued} failed delivery retry/retries.")
        self.window.after(100, self.refresh)

    def clear_history(self):
        if not messagebox.askyesno(
            "Clear Delivery History",
            "Delete terminal DELIVERED and FAILED rows?\n\nEvent History and active retries are not affected.",
            parent=self.window,
        ):
            return
        if get_notification_history_store().clear_terminal():
            self.refresh()

    def apply_theme(self, theme):
        if self._closed:
            return
        palette = get_theme_palette(theme)
        self.window.configure(bg=palette["bg"])
        for frame in (self.filter_frame, self.table_frame, self.button_frame):
            frame.configure(bg=palette["bg"])
        for label in (self.search_label, self.provider_label, self.status_filter_label,
                      self.status_label):
            label.configure(bg=palette["bg"], fg=palette["fg"])
        self.search_entry.configure(bg=palette["entry_bg"], fg=palette["entry_fg"],
                                    insertbackground=palette["entry_fg"])
        for button in (self.filter_button, self.reset_button, self.refresh_button,
                       self.retry_button, self.retry_all_button, self.clear_button,
                       self.close_button):
            button.configure(bg=palette["button_bg"], fg=palette["fg"])
        style = ttk.Style()
        style.configure("Delivery.Treeview", background=palette["tree_bg"],
                        foreground=palette["tree_fg"], fieldbackground=palette["tree_bg"])
        style.configure("Delivery.TCombobox", fieldbackground=palette["entry_bg"],
                        foreground=palette["entry_fg"])
        self.tree.tag_configure("failed", foreground="#c62828")
        self.tree.tag_configure("delivered", foreground="#2e7d32")

    def close(self):
        if self._closed:
            return
        self._closed = True
        notification_history_windows.discard(self)
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def refresh_notification_history_windows():
    for history_window in tuple(notification_history_windows):
        history_window.refresh()


def open_notification_history():
    for history_window in tuple(notification_history_windows):
        if not history_window._closed:
            try:
                history_window.window.deiconify()
                history_window.window.lift()
                history_window.window.focus_force()
                history_window.refresh()
                return history_window
            except tk.TclError:
                pass
        notification_history_windows.discard(history_window)
    return NotificationHistoryWindow(root)


# ===================== Notification providers/settings =====================

def _native_notification_callback(title: str, message: str, warning: bool) -> bool:
    if tray_icon is None:
        return False
    return tray_icon.show_notification(title, message, warning)


def build_notification_providers(settings: NotificationSettings) -> dict:
    return {
        PROVIDER_WINDOWS: WindowsNotificationProvider(
            _native_notification_callback
        ),
        PROVIDER_GENERIC: GenericWebhookProvider(settings.generic_webhook_url),
        PROVIDER_TEAMS: TeamsWebhookProvider(settings.teams_webhook_url),
    }


def apply_notification_settings(settings: NotificationSettings, *, persist=False):
    global notification_settings
    notification_settings = settings
    if notification_manager is not None:
        notification_manager.configure(
            notification_settings,
            build_notification_providers(notification_settings),
        )
    if persist:
        save_config()


def start_notification_support() -> None:
    global notification_manager, notification_poll_after_id
    notification_manager = NotificationManager(
        notification_result_queue.put,
        history_store=get_notification_history_store(),
    )
    apply_notification_settings(notification_settings)
    notification_poll_after_id = root.after(100, poll_notification_results)


def poll_notification_results() -> None:
    global notification_poll_after_id
    notification_poll_after_id = None
    if shutdown_guard.started:
        return
    try:
        while True:
            result = notification_result_queue.get_nowait()
            notification_last_results[result.provider] = result
            for settings_window in tuple(notification_settings_windows):
                settings_window.handle_delivery_result(result)
            refresh_notification_history_windows()
    except queue.Empty:
        pass
    notification_poll_after_id = root.after(100, poll_notification_results)


class NotificationSettingsWindow:
    """Configure providers without exposing endpoints outside a masked entry."""

    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        apply_window_icon(self.window)
        self.window.title("Notification Settings")
        self.window.geometry("720x555")
        self.window.resizable(False, False)
        self._closed = False

        self.windows_enabled = tk.BooleanVar(
            value=notification_settings.windows_notifications_enabled
        )
        self.generic_enabled = tk.BooleanVar(
            value=notification_settings.generic_webhook_enabled
        )
        self.generic_url = tk.StringVar(
            value=notification_settings.generic_webhook_url
        )
        self.teams_enabled = tk.BooleanVar(
            value=notification_settings.teams_webhook_enabled
        )
        self.teams_url = tk.StringVar(value=notification_settings.teams_webhook_url)
        self.timeout_var = tk.StringVar(value=str(notification_settings.timeout_seconds))
        self.retries_var = tk.StringVar(value=str(notification_settings.retry_count))
        self.retry_later_enabled = tk.BooleanVar(
            value=notification_settings.retry_later_enabled
        )
        self.show_urls = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

        self.intro_label = tk.Label(
            self.window,
            text=(
                "Notifications use TCP DOWN / RECOVERED transitions. "
                "Webhook endpoints are sensitive local settings."
            ),
            anchor="w",
        )
        self.intro_label.pack(fill="x", padx=12, pady=(12, 6))

        self.windows_frame = tk.LabelFrame(self.window, text="Windows Notification")
        self.windows_frame.pack(fill="x", padx=12, pady=5)
        self.windows_check = tk.Checkbutton(
            self.windows_frame, text="Enabled", variable=self.windows_enabled
        )
        self.windows_check.grid(row=0, column=0, padx=8, pady=8, sticky="w")
        self.windows_test = tk.Button(
            self.windows_frame,
            text="Test",
            width=10,
            command=lambda: self.test_provider(PROVIDER_WINDOWS),
        )
        self.windows_test.grid(row=0, column=2, padx=8, pady=8, sticky="e")
        self.windows_frame.grid_columnconfigure(1, weight=1)

        self.generic_frame = tk.LabelFrame(self.window, text="Generic Webhook")
        self.generic_frame.pack(fill="x", padx=12, pady=5)
        self.generic_check = tk.Checkbutton(
            self.generic_frame, text="Enabled", variable=self.generic_enabled
        )
        self.generic_check.grid(row=0, column=0, padx=8, pady=8, sticky="w")
        self.generic_label = tk.Label(self.generic_frame, text="Webhook URL:")
        self.generic_label.grid(row=0, column=1, padx=(4, 4), pady=8)
        self.generic_entry = tk.Entry(
            self.generic_frame,
            textvariable=self.generic_url,
            width=48,
            show="•",
        )
        self.generic_entry.grid(row=0, column=2, padx=4, pady=8, sticky="ew")
        self.generic_test = tk.Button(
            self.generic_frame,
            text="Test",
            width=10,
            command=lambda: self.test_provider(PROVIDER_GENERIC),
        )
        self.generic_test.grid(row=0, column=3, padx=8, pady=8)
        self.generic_frame.grid_columnconfigure(2, weight=1)

        self.teams_frame = tk.LabelFrame(self.window, text="Microsoft Teams")
        self.teams_frame.pack(fill="x", padx=12, pady=5)
        self.teams_check = tk.Checkbutton(
            self.teams_frame, text="Enabled", variable=self.teams_enabled
        )
        self.teams_check.grid(row=0, column=0, padx=8, pady=8, sticky="w")
        self.teams_label = tk.Label(self.teams_frame, text="Workflow URL:")
        self.teams_label.grid(row=0, column=1, padx=(4, 4), pady=8)
        self.teams_entry = tk.Entry(
            self.teams_frame,
            textvariable=self.teams_url,
            width=48,
            show="•",
        )
        self.teams_entry.grid(row=0, column=2, padx=4, pady=8, sticky="ew")
        self.teams_test = tk.Button(
            self.teams_frame,
            text="Test",
            width=10,
            command=lambda: self.test_provider(PROVIDER_TEAMS),
        )
        self.teams_test.grid(row=0, column=3, padx=8, pady=8)
        self.teams_frame.grid_columnconfigure(2, weight=1)

        self.delivery_frame = tk.LabelFrame(self.window, text="Delivery")
        self.delivery_frame.pack(fill="x", padx=12, pady=5)
        self.timeout_label = tk.Label(self.delivery_frame, text="Timeout (1–30 sec):")
        self.timeout_label.grid(row=0, column=0, padx=(8, 4), pady=8)
        self.timeout_entry = tk.Entry(
            self.delivery_frame, textvariable=self.timeout_var, width=6
        )
        self.timeout_entry.grid(row=0, column=1, padx=(0, 16), pady=8)
        self.retries_label = tk.Label(self.delivery_frame, text="Retries (0–5):")
        self.retries_label.grid(row=0, column=2, padx=(0, 4), pady=8)
        self.retries_entry = tk.Entry(
            self.delivery_frame, textvariable=self.retries_var, width=6
        )
        self.retries_entry.grid(row=0, column=3, padx=(0, 16), pady=8)
        self.show_check = tk.Checkbutton(
            self.delivery_frame,
            text="Show webhook URLs",
            variable=self.show_urls,
            command=self.toggle_url_visibility,
        )
        self.show_check.grid(row=0, column=4, padx=8, pady=8)
        self.retry_later_check = tk.Checkbutton(
            self.delivery_frame,
            text="Retry failed webhook deliveries later (5m, 15m, 60m)",
            variable=self.retry_later_enabled,
        )
        self.retry_later_check.grid(
            row=1, column=0, columnspan=5, padx=8, pady=(0, 8), sticky="w"
        )

        self.status_label = tk.Label(
            self.window, textvariable=self.status_var, anchor="w", wraplength=690
        )
        self.status_label.pack(fill="x", padx=12, pady=(6, 4))
        self.button_frame = tk.Frame(self.window)
        self.button_frame.pack(pady=8)
        self.save_button = tk.Button(
            self.button_frame, text="Save", width=12, command=self.save
        )
        self.save_button.grid(row=0, column=0, padx=5)
        self.cancel_button = tk.Button(
            self.button_frame, text="Cancel", width=12, command=self.close
        )
        self.cancel_button.grid(row=0, column=1, padx=5)
        self.history_button = tk.Button(
            self.button_frame, text="Delivery History", width=14,
            command=open_notification_history,
        )
        self.history_button.grid(row=0, column=2, padx=5)

        notification_settings_windows.add(self)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_theme(current_theme)
        self.show_last_result()

    def toggle_url_visibility(self):
        mask = "" if self.show_urls.get() else "•"
        self.generic_entry.configure(show=mask)
        self.teams_entry.configure(show=mask)

    def parsed_delivery_policy(self):
        try:
            timeout = int(self.timeout_var.get())
            retries = int(self.retries_var.get())
        except ValueError:
            raise ValueError("Timeout and Retries must be whole numbers.")
        if not 1 <= timeout <= 30:
            raise ValueError("Timeout must be between 1 and 30 seconds.")
        if not 0 <= retries <= 5:
            raise ValueError("Retries must be between 0 and 5.")
        return timeout, retries

    def settings_from_form(self) -> NotificationSettings:
        timeout, retries = self.parsed_delivery_policy()
        generic_url = self.generic_url.get().strip()
        teams_url = self.teams_url.get().strip()
        if self.generic_enabled.get() and not endpoint_is_valid(generic_url):
            raise ValueError("Generic Webhook requires a valid HTTP(S) URL.")
        if self.teams_enabled.get() and not endpoint_is_valid(teams_url):
            raise ValueError("Microsoft Teams requires a valid HTTP(S) URL.")
        return NotificationSettings(
            windows_notifications_enabled=bool(self.windows_enabled.get()),
            generic_webhook_enabled=bool(self.generic_enabled.get()),
            generic_webhook_url=generic_url,
            teams_webhook_enabled=bool(self.teams_enabled.get()),
            teams_webhook_url=teams_url,
            timeout_seconds=timeout,
            retry_count=retries,
            retry_later_enabled=bool(self.retry_later_enabled.get()),
        )

    def save(self):
        try:
            settings = self.settings_from_form()
        except ValueError as exc:
            messagebox.showerror("Notification Settings", str(exc), parent=self.window)
            return
        apply_notification_settings(settings, persist=True)
        self.status_var.set("Notification settings saved.")
        self.close()

    def test_provider(self, provider_key: str):
        if notification_manager is None:
            self.status_var.set("Notification service is unavailable.")
            return
        try:
            timeout, retries = self.parsed_delivery_policy()
        except ValueError as exc:
            messagebox.showerror("Test Notification", str(exc), parent=self.window)
            return
        if provider_key == PROVIDER_WINDOWS:
            provider = WindowsNotificationProvider(_native_notification_callback)
        elif provider_key == PROVIDER_GENERIC:
            endpoint = self.generic_url.get().strip()
            if not endpoint_is_valid(endpoint):
                messagebox.showerror(
                    "Test Notification",
                    "Generic Webhook requires a valid HTTP(S) URL.",
                    parent=self.window,
                )
                return
            provider = GenericWebhookProvider(endpoint)
        else:
            endpoint = self.teams_url.get().strip()
            if not endpoint_is_valid(endpoint):
                messagebox.showerror(
                    "Test Notification",
                    "Microsoft Teams requires a valid HTTP(S) URL.",
                    parent=self.window,
                )
                return
            provider = TeamsWebhookProvider(endpoint)
        if notification_manager.enqueue_test(
            provider, timeout=timeout, retries=retries
        ):
            self.status_var.set(f"Testing {provider.display_name}…")
        else:
            self.status_var.set("Unable to queue the test notification.")

    def show_last_result(self):
        if not notification_last_results:
            return
        result = next(reversed(notification_last_results.values()))
        self.status_var.set(result.message)

    def handle_delivery_result(self, result: DeliveryResult):
        if self._closed:
            return
        self.status_var.set(result.message)
        if result.test_only:
            dialog = messagebox.showinfo if result.success else messagebox.showerror
            dialog("Test Notification", result.message, parent=self.window)

    def apply_theme(self, theme: str):
        if self._closed:
            return
        palette = get_theme_palette(theme)
        self.window.configure(bg=palette["bg"])
        for frame in (
            self.windows_frame,
            self.generic_frame,
            self.teams_frame,
            self.delivery_frame,
        ):
            frame.configure(bg=palette["bg"], fg=palette["fg"])
        self.button_frame.configure(bg=palette["bg"])
        for label in (
            self.intro_label,
            self.generic_label,
            self.teams_label,
            self.timeout_label,
            self.retries_label,
            self.status_label,
        ):
            label.configure(bg=palette["bg"], fg=palette["fg"])
        for check in (
            self.windows_check,
            self.generic_check,
            self.teams_check,
            self.show_check,
            self.retry_later_check,
        ):
            check.configure(
                bg=palette["bg"],
                fg=palette["fg"],
                selectcolor=palette["entry_bg"],
                activebackground=palette["bg"],
                activeforeground=palette["fg"],
            )
        for entry in (
            self.generic_entry,
            self.teams_entry,
            self.timeout_entry,
            self.retries_entry,
        ):
            entry.configure(
                bg=palette["entry_bg"],
                fg=palette["entry_fg"],
                insertbackground=palette["entry_fg"],
            )
        for button in (
            self.windows_test,
            self.generic_test,
            self.teams_test,
            self.save_button,
            self.cancel_button,
            self.history_button,
        ):
            button.configure(
                bg=palette["button_bg"],
                fg=palette["fg"],
                activebackground=palette["button_bg"],
                activeforeground=palette["fg"],
            )

    def close(self):
        if self._closed:
            return
        self._closed = True
        notification_settings_windows.discard(self)
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def open_notification_settings():
    for settings_window in tuple(notification_settings_windows):
        if settings_window._closed:
            notification_settings_windows.discard(settings_window)
            continue
        try:
            settings_window.window.deiconify()
            settings_window.window.lift()
            settings_window.window.focus_force()
            return settings_window
        except tk.TclError:
            notification_settings_windows.discard(settings_window)
    return NotificationSettingsWindow(root)


# ===================== IPv4 Range Scan =====================

def set_scan_controls(running: bool):
    btn_scan.config(state="disabled" if running else "normal")
    btn_cancel_scan.config(state="normal" if running else "disabled")
    btn_check_sel.config(state="disabled" if running else "normal")
    btn_check_all.config(state="disabled" if running else "normal")
    btn_start_auto.config(state="disabled" if running else "normal")
    btn_add.config(state="disabled" if running else "normal")
    btn_edit.config(state="disabled" if running else "normal")
    btn_remove.config(state="disabled" if running else "normal")
    btn_start_maintenance.config(state="disabled" if running else "normal")
    btn_end_maintenance.config(state="disabled" if running else "normal")
    btn_load.config(state="disabled" if running else "normal")


def update_scan_progress(prefix: str = "Scanning"):
    lbl_scan_progress.config(text=f"{prefix} {scan_completed} / {scan_plan.total}")


def apply_scan_result(host: str, port: int, ping_text: str, port_online: bool):
    """Update a duplicate row or add a transient discovery result."""
    if not scan_show_all and ping_text == "Timeout" and not port_online:
        return

    item_id = find_existing_target(host, port)
    if item_id is None:
        item_id = tree.insert(
            "",
            "end",
            values=("", host, port, "", ping_text, "Not checked", "N/A"),
            tags=("unknown",),
        )
        transient_scan_items.add(item_id)
        if group_filter_var.get() != "All Groups":
            tree.detach(item_id)
    update_row_status(
        item_id, host, port, ping_text, port_online, track_state=False
    )


def submit_scan_work():
    """Keep only one bounded worker-window scheduled at a time."""
    available_slots = CHECK_WORKERS - len(scan_pending)
    for host in scan_plan.take(available_slots):
        future = network_executor.submit(check_target, host, scan_port)
        scan_pending[future] = host


def poll_range_scan():
    global scan_completed
    completed_futures = [future for future in tuple(scan_pending) if future.done()]
    for future in completed_futures:
        host = scan_pending.pop(future)
        if future.cancelled():
            continue

        scan_completed += 1
        try:
            ping_text, port_online = future.result()
        except Exception:
            ping_text, port_online = "Timeout", False

        if not scan_plan.cancelled:
            apply_scan_result(host, scan_port, ping_text, port_online)

    if not scan_plan.cancelled:
        submit_scan_work()
        update_scan_progress()

    if scan_pending:
        root.after(50, poll_range_scan)
        return

    if scan_plan.cancelled:
        finish_range_scan(cancelled=True)
    elif scan_plan.exhausted:
        finish_range_scan(cancelled=False)
    else:
        root.after(50, poll_range_scan)


def start_range_scan():
    global scan_running, scan_plan, scan_port, scan_pending
    global scan_completed, scan_show_all

    if scan_running:
        return
    if check_in_progress or auto_running:
        messagebox.showwarning(
            "IP Range Scan",
            "Stop Auto Refresh and wait for the current check to finish before scanning.",
        )
        return

    port_text = entry_scan_port.get().strip()
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        messagebox.showwarning("IP Range Scan", "Port must be between 1 and 65535.")
        return

    try:
        new_plan = IPv4ScanPlan.from_range(
            entry_start_ip.get().strip(),
            entry_end_ip.get().strip(),
        )
    except ValueError as exc:
        messagebox.showwarning("IP Range Scan", str(exc))
        return

    scan_running = True
    scan_plan = new_plan
    scan_port = int(port_text)
    scan_pending = {}
    scan_completed = 0
    scan_show_all = bool(show_all_scanned_var.get())
    set_scan_controls(True)
    update_scan_progress()
    submit_scan_work()
    root.after(50, poll_range_scan)


def cancel_range_scan():
    if not scan_running or scan_plan is None:
        return
    scan_plan.cancel()
    btn_cancel_scan.config(state="disabled")
    lbl_scan_progress.config(text=f"Cancelling {scan_completed} / {scan_plan.total}")
    for future in tuple(scan_pending):
        future.cancel()


def finish_range_scan(cancelled: bool):
    global scan_running, scan_pending
    scan_running = False
    scan_pending = {}
    set_scan_controls(False)
    prefix = "Cancelled" if cancelled else "Completed"
    update_scan_progress(prefix)


# ===================== Save / Load Host List (ปุ่ม) =====================

def save_host_list():
    items = tree.get_children()
    if not items:
        messagebox.showinfo("Save List", "ยังไม่มีรายการให้บันทึก")
        return

    data = []
    for item in items:
        values = tree.item(item, "values")
        name, host, port = values[COL_NAME], values[COL_HOST], values[COL_PORT]
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            port_int = port
        metadata = target_metadata.get(item, {
            "groups": [], "maintenance": MaintenanceState().to_config()
        })
        data.append(make_target_record(name, host, port_int, metadata["groups"], metadata["maintenance"]))

    path = filedialog.asksaveasfilename(
        defaultextension=".json",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        title="Save host list",
    )
    if not path:
        return

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("Save List", "บันทึกรายการเรียบร้อยแล้ว")
    except Exception as e:
        messagebox.showerror("Save List", f"เกิดข้อผิดพลาดในการบันทึกไฟล์:\n{e}")


def load_host_list():
    path = filedialog.askopenfilename(
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        title="Load host list",
    )
    if not path:
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        messagebox.showerror("Load List", f"ไม่สามารถอ่านไฟล์ได้:\n{e}")
        return

    if not isinstance(data, list):
        messagebox.showerror("Load List", "Host list must contain a JSON array.")
        return

    # ล้างของเดิม
    for item in all_persistent_items():
        if maintenance_state_for(item).enabled:
            end_maintenance_for_item(item, end_reason="host list replaced")
    transient_scan_items.clear()
    tcp_state_tracker.clear()
    finish_editing(clear_entries=False)
    for item in all_known_items():
        tree.delete(item)
    target_metadata.clear()
    target_order.clear()

    # เพิ่มใหม่
    for entry in data:
        if not isinstance(entry, dict):
            continue
        record = normalize_target_record(entry)
        name, host, port = record["name"], record["host"], record["port"]
        if not host:
            continue
        insert_persistent_target(record)
    refresh_group_choices()
    apply_group_filter()
    resolve_expired_maintenance_on_startup()


# ===================== Config: auto-save theme + hosts =====================

def save_config():
    """บันทึก theme + host list ลงไฟล์ config"""
    hosts = configured_target_records()

    config = {
        "theme": current_theme,
        "state_change_alerts": bool(state_change_alerts_var.get()),
        "minimize_to_tray": bool(minimize_to_tray_var.get()),
        "close_to_tray": bool(close_to_tray_var.get()),
        "hosts": hosts,
    }
    config.update(notification_settings.to_config())

    try:
        with open(get_config_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        # ไม่ต้องขึ้น popup เพราะเป็นตอนปิดโปรแกรม
        print("Save config error:", e)


def load_config():
    """อ่าน config ถ้ามี แล้ว set theme + เติม host list ให้"""
    global current_theme, notification_settings
    path = get_config_path()
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print("Load config error:", e)
        return

    if not isinstance(config, dict):
        print("Load config error: config root must be a JSON object")
        return

    # theme
    theme = config.get("theme")
    if theme in ("light", "dark"):
        current_theme = theme

    state_change_alerts_var.set(alert_enabled_from_config(config))
    tray_preferences = tray_preferences_from_config(config)
    minimize_to_tray_var.set(tray_preferences.minimize_to_tray)
    close_to_tray_var.set(tray_preferences.close_to_tray)
    notification_settings = notification_settings_from_config(config)

    # hosts
    hosts = config.get("hosts", [])
    if not isinstance(hosts, list):
        return
    for entry in hosts:
        if not isinstance(entry, dict):
            continue
        record = normalize_target_record(entry)
        name, host, port = record["name"], record["host"], record["port"]
        if not host:
            continue
        insert_persistent_target(record)
    refresh_group_choices()
    apply_group_filter()
    resolve_expired_maintenance_on_startup()


def resolve_expired_maintenance_on_startup():
    now = datetime.now().astimezone()
    changed = False
    for item in all_persistent_items():
        state = maintenance_state_for(item)
        if maintenance_has_expired(state, now):
            end_maintenance_for_item(
                item, end_reason="expired", occurred_at=state.until or now
            )
            changed = True
    if changed:
        save_config()


# ===================== Windows System Tray / shutdown =====================

def enqueue_tray_action(action: str) -> None:
    """Receive a native tray callback without touching Tkinter from its thread."""
    tray_action_queue.put(action)


def refresh_tray_menu_state() -> None:
    if tray_icon is not None:
        tray_icon.update_state(auto_running=auto_running)


def start_tray_support() -> bool:
    global tray_icon, tray_available, tray_poll_after_id
    tray_icon = WindowsTrayIcon(
        resource_path(tray_icon_relative_path()), enqueue_tray_action
    )
    tray_icon.update_state(auto_running=auto_running)
    tray_available = tray_icon.start()
    if not tray_available:
        btn_hide_tray.configure(state="disabled")
        if tray_icon.startup_error:
            print("System tray unavailable:", tray_icon.startup_error)
        return False
    tray_poll_after_id = root.after(50, poll_tray_actions)
    return True


def hide_main_window() -> bool:
    global main_window_hidden
    if shutdown_guard.started:
        return False
    if not tray_available:
        messagebox.showwarning(
            "System Tray",
            "The Windows notification-area icon is unavailable.",
            parent=root,
        )
        return False
    main_window_hidden = True
    root.withdraw()
    return True


def restore_main_window() -> None:
    global main_window_hidden
    if shutdown_guard.started:
        return
    main_window_hidden = False
    root.deiconify()
    try:
        root.state("normal")
    except tk.TclError:
        pass
    root.lift()
    root.focus_force()
    if pending_hidden_alerts:
        alerts = list(pending_hidden_alerts)
        pending_hidden_alerts.clear()
        root.after_idle(
            lambda queued_alerts=alerts: show_state_change_alerts(
                queued_alerts, allow_defer=False
            )
        )


def handle_root_unmap(event=None) -> None:
    """Convert an ordinary minimize into Hide to Tray only when requested."""
    if event is not None and event.widget is not root:
        return
    if not minimize_to_tray_var.get() or not tray_available:
        return

    def hide_if_iconic():
        if not shutdown_guard.started and root.state() == "iconic":
            hide_main_window()

    root.after_idle(hide_if_iconic)


def handle_tray_action(action: str) -> None:
    """Run one queued tray action on Tk's main thread."""
    if action == TRAY_ACTION_OPEN:
        restore_main_window()
    elif action == TRAY_ACTION_CHECK_ALL:
        if not all_persistent_items():
            restore_main_window()
        check_all()
    elif action == TRAY_ACTION_START_AUTO:
        interval_text = entry_interval.get().strip()
        if not interval_text.isdigit() or int(interval_text) <= 0:
            restore_main_window()
        start_auto()
    elif action == TRAY_ACTION_STOP_AUTO:
        stop_auto()
    elif action == TRAY_ACTION_EVENT_HISTORY:
        restore_main_window()
        open_event_history()
    elif action == TRAY_ACTION_AVAILABILITY_REPORT:
        restore_main_window()
        open_availability_report()
    elif action == TRAY_ACTION_NOTIFICATION_SETTINGS:
        restore_main_window()
        open_notification_settings()
    elif action == TRAY_ACTION_NOTIFICATION_HISTORY:
        restore_main_window()
        open_notification_history()
    elif action == TRAY_ACTION_EXIT:
        shutdown_application()


def poll_tray_actions() -> None:
    global tray_poll_after_id
    tray_poll_after_id = None
    if shutdown_guard.started:
        return
    try:
        while True:
            handle_tray_action(tray_action_queue.get_nowait())
            if shutdown_guard.started:
                return
    except queue.Empty:
        pass
    tray_poll_after_id = root.after(50, poll_tray_actions)


def on_close() -> None:
    """Handle the main-window X according to the persisted tray preference."""
    if should_close_to_tray(close_to_tray_var.get(), tray_available):
        hide_main_window()
        return
    shutdown_application()


def shutdown_application() -> bool:
    """Idempotent canonical cleanup used by every real Exit action."""
    global auto_running, tray_poll_after_id, notification_poll_after_id
    global tray_available, main_window_hidden, maintenance_after_id
    if not shutdown_guard.begin():
        return False

    auto_running = False
    main_window_hidden = False
    if auto_after_id is not None:
        try:
            root.after_cancel(auto_after_id)
        except tk.TclError:
            pass
    if tray_poll_after_id is not None:
        try:
            root.after_cancel(tray_poll_after_id)
        except tk.TclError:
            pass
        tray_poll_after_id = None
    if notification_poll_after_id is not None:
        try:
            root.after_cancel(notification_poll_after_id)
        except tk.TclError:
            pass
        notification_poll_after_id = None
    if maintenance_after_id is not None:
        try:
            root.after_cancel(maintenance_after_id)
        except tk.TclError:
            pass
        maintenance_after_id = None
    if notification_manager is not None:
        notification_manager.shutdown(timeout=1.0)
    if scan_running and scan_plan is not None:
        scan_plan.cancel()
        for future in tuple(scan_pending):
            future.cancel()
    for trace_window in tuple(trace_windows):
        trace_window.close()
    for history_window in tuple(event_history_windows):
        history_window.close()
    for report_window in tuple(availability_report_windows):
        report_window.close()
    for settings_window in tuple(notification_settings_windows):
        settings_window.close()
    for history_window in tuple(notification_history_windows):
        history_window.close()
    save_config()
    if tray_icon is not None:
        tray_icon.stop()
    tray_available = False
    network_executor.shutdown(wait=False, cancel_futures=True)
    trace_executor.shutdown(wait=False, cancel_futures=True)
    availability_executor.shutdown(wait=False, cancel_futures=True)
    try:
        root.destroy()
    except tk.TclError:
        pass
    return True


# ===================== Auto Refresh =====================

def start_auto():
    global auto_running, auto_after_id
    if scan_running:
        return
    interval_text = entry_interval.get().strip()
    if not interval_text.isdigit() or int(interval_text) <= 0:
        messagebox.showwarning("Interval Error", "Interval must be a number greater than 0 seconds")
        return

    auto_running = True
    if auto_after_id is not None:
        root.after_cancel(auto_after_id)
        auto_after_id = None
    btn_start_auto.config(state="disabled")
    btn_stop_auto.config(state="normal")
    refresh_tray_menu_state()
    auto_loop()


def stop_auto():
    global auto_running, auto_after_id
    auto_running = False
    if auto_after_id is not None:
        root.after_cancel(auto_after_id)
        auto_after_id = None
    btn_start_auto.config(state="normal")
    btn_stop_auto.config(state="disabled")
    refresh_tray_menu_state()


def auto_loop():
    global auto_after_id
    auto_after_id = None
    if not auto_running:
        return
    if check_in_progress:
        auto_after_id = root.after(100, auto_loop)
        return

    items = all_persistent_items()
    if items and start_check_cycle(items):
        return
    schedule_next_auto()


def schedule_next_auto():
    global auto_after_id
    if not auto_running:
        return
    try:
        interval_sec = int(entry_interval.get().strip())
    except ValueError:
        interval_sec = 5
    auto_after_id = root.after(max(1, interval_sec) * 1000, auto_loop)


# ===================== Theme =====================

def get_theme_palette(theme: str):
    """Return shared colors for the main window and Trace Route windows."""
    if theme == "dark":
        return {
            "bg": "#2b2b2b",
            "fg": "#f0f0f0",
            "button_bg": "#4c5052",
            "entry_bg": "#3c3f41",
            "entry_fg": "#ffffff",
            "tree_bg": "#3c3f41",
            "tree_fg": "#f0f0f0",
        }
    return {
        "bg": "#f0f0f0",
        "fg": "black",
        "button_bg": "#e0e0e0",
        "entry_bg": "white",
        "entry_fg": "black",
        "tree_bg": "white",
        "tree_fg": "black",
    }

def toggle_theme():
    global current_theme
    current_theme = "dark" if current_theme == "light" else "light"
    btn_theme.config(text="Light Mode" if current_theme == "dark" else "Dark Mode")
    apply_theme(current_theme)


def apply_theme(theme: str):
    """
    เปลี่ยนสีทั้งหมดของหน้า UI ตาม theme: light/dark
    """
    if theme == "dark":
        bg = "#2b2b2b"
        fg = "#f0f0f0"
        widget_bg = "#3c3f41"
        button_bg = "#4c5052"
        entry_bg = "#3c3f41"
        entry_fg = "#ffffff"
        tree_bg = "#3c3f41"
        tree_fg = "#f0f0f0"
        online_bg = "#2e7d32"
        offline_bg = "#c62828"
        unknown_bg = "#616161"
    else:
        bg = "#f0f0f0"
        fg = "black"
        widget_bg = "#f0f0f0"
        button_bg = "#e0e0e0"
        entry_bg = "white"
        entry_fg = "black"
        tree_bg = "white"
        tree_fg = "black"
        online_bg = "green"
        offline_bg = "red"
        unknown_bg = "lightgray"

    # พื้นหลังหลัก
    root.configure(bg=bg)
    frame_top.configure(bg=bg)
    frame_table.configure(bg=bg)
    frame_scan.configure(bg=bg)
    frame_bottom.configure(bg=bg)

    # label
    for lbl in (
        lbl_name,
        lbl_groups,
        lbl_group_filter,
        lbl_host,
        lbl_port,
        lbl_interval,
        lbl_start_ip,
        lbl_end_ip,
        lbl_scan_port,
        lbl_scan_progress,
    ):
        lbl.configure(bg=bg, fg=fg)

    # entry
    for ent in (
        entry_name,
        entry_groups,
        entry_host,
        entry_port,
        entry_interval,
        entry_start_ip,
        entry_end_ip,
        entry_scan_port,
    ):
        ent.configure(bg=entry_bg, fg=entry_fg, insertbackground=entry_fg)

    for checkbox in (
        chk_show_all,
        chk_state_alerts,
        chk_minimize_tray,
        chk_close_tray,
    ):
        checkbox.configure(
            bg=bg,
            fg=fg,
            selectcolor=entry_bg,
            activebackground=bg,
            activeforeground=fg,
        )

    # button
    for btn in (
        btn_add,
        btn_edit,
        btn_remove,
        btn_start_maintenance,
        btn_end_maintenance,
        btn_check_sel,
        btn_check_all,
        btn_trace,
        btn_history,
        btn_availability,
        btn_start_auto,
        btn_stop_auto,
        btn_save,
        btn_load,
        btn_theme,
        btn_scan,
        btn_cancel_scan,
        btn_hide_tray,
        btn_notifications,
        btn_notification_history,
    ):
        btn.configure(bg=button_bg, fg=fg, activebackground=button_bg, activeforeground=fg)

    # Treeview style
    style = ttk.Style()
    style.configure(
        "Custom.Treeview",
        background=tree_bg,
        foreground=tree_fg,
        fieldbackground=tree_bg,
        bordercolor=widget_bg,
        borderwidth=0,
    )
    style.configure(
        "Custom.Treeview.Heading",
        background=widget_bg,
        foreground=fg,
    )
    tree.configure(style="Custom.Treeview")

    # tag สีแถว
    tree.tag_configure("online", background=online_bg, foreground="white")
    tree.tag_configure("offline", background=offline_bg, foreground="white")
    tree.tag_configure("unknown", background=unknown_bg, foreground=fg)
    style.configure(
        "Main.TCombobox", fieldbackground=entry_bg, background=button_bg,
        foreground=entry_fg, arrowcolor=fg,
    )
    style.map("Main.TCombobox", fieldbackground=[("readonly", entry_bg)], foreground=[("readonly", entry_fg)])

    for trace_window in tuple(trace_windows):
        trace_window.apply_theme(theme)
    for history_window in tuple(event_history_windows):
        history_window.apply_theme(theme)
    for report_window in tuple(availability_report_windows):
        report_window.apply_theme(theme)
    for settings_window in tuple(notification_settings_windows):
        settings_window.apply_theme(theme)
    for history_window in tuple(notification_history_windows):
        history_window.apply_theme(theme)


# ===================== GUI =====================

root = tk.Tk()
root.title("Multi Host Port Checker (with Ping)")
root.geometry("1220x780")
root.resizable(False, False)
apply_window_icon(root)

# ---- ส่วนบน: กรอก Host / Port ----
frame_top = tk.Frame(root)
frame_top.pack(pady=10, padx=10, fill="x")

lbl_name = tk.Label(frame_top, text="Device Name:")
lbl_name.grid(row=0, column=0, padx=(0, 5))

entry_name = tk.Entry(frame_top, width=20)
entry_name.grid(row=0, column=1, padx=(0, 10))

lbl_host = tk.Label(frame_top, text="Host / IP:")
lbl_host.grid(row=0, column=2, padx=(0, 5))

entry_host = tk.Entry(frame_top, width=25)
entry_host.grid(row=0, column=3, padx=(0, 10))
entry_host.insert(0, "example.com")

lbl_port = tk.Label(frame_top, text="Port:")
lbl_port.grid(row=0, column=4, padx=(0, 5))

entry_port = tk.Entry(frame_top, width=8)
entry_port.grid(row=0, column=5, padx=(0, 10))
entry_port.insert(0, "443")

btn_add = tk.Button(frame_top, text="Add", width=10, command=add_target)
btn_add.grid(row=0, column=6, padx=(0, 5))

btn_edit = tk.Button(frame_top, text="Edit Selected", width=13, command=edit_selected)
btn_edit.grid(row=0, column=7, padx=(0, 5))

btn_remove = tk.Button(frame_top, text="Remove Selected", width=15, command=remove_selected)
btn_remove.grid(row=0, column=8)

lbl_groups = tk.Label(frame_top, text="Groups / Tags:")
lbl_groups.grid(row=1, column=0, padx=(0, 5), pady=(8, 0))
entry_groups = tk.Entry(frame_top, width=32)
entry_groups.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=(8, 0))

lbl_group_filter = tk.Label(frame_top, text="Group:")
lbl_group_filter.grid(row=1, column=3, padx=(0, 5), pady=(8, 0), sticky="e")
group_filter_var = tk.StringVar(value="All Groups")
group_filter_combo = ttk.Combobox(
    frame_top, textvariable=group_filter_var, values=("All Groups",),
    state="readonly", width=20, style="Main.TCombobox",
)
group_filter_combo.grid(row=1, column=4, columnspan=2, sticky="w", pady=(8, 0))
group_filter_combo.bind("<<ComboboxSelected>>", apply_group_filter)

# ---- ตาราง ----
frame_table = tk.Frame(root)
frame_table.pack(pady=5, padx=10, fill="both", expand=True)

columns = ("name", "host", "port", "groups", "ping", "status", "maintenance")
tree = ttk.Treeview(frame_table, columns=columns, show="headings", height=14)

tree.heading("name", text="Device Name")
tree.heading("host", text="Host / IP")
tree.heading("port", text="Port")
tree.heading("groups", text="Groups")
tree.heading("ping", text="Ping (ms)")
tree.heading("status", text="Status")
tree.heading("maintenance", text="Maintenance")

tree.column("name", width=145)
tree.column("host", width=190)
tree.column("port", width=70, anchor="center")
tree.column("groups", width=190)
tree.column("ping", width=85, anchor="center")
tree.column("status", width=130)
tree.column("maintenance", width=210)

scrollbar_y = ttk.Scrollbar(frame_table, orient="vertical", command=tree.yview)
tree.configure(yscrollcommand=scrollbar_y.set)

tree.pack(side="left", fill="both", expand=True)
scrollbar_y.pack(side="right", fill="y")

tree.tag_configure("online", background="green", foreground="white")
tree.tag_configure("offline", background="red", foreground="white")
tree.tag_configure("unknown", background="lightgray", foreground="black")

# ---- IPv4 range scan ----
frame_scan = tk.Frame(root)
frame_scan.pack(pady=5, padx=10, fill="x")

lbl_start_ip = tk.Label(frame_scan, text="Start IP:")
lbl_start_ip.grid(row=0, column=0, padx=(0, 5))

entry_start_ip = tk.Entry(frame_scan, width=16)
entry_start_ip.grid(row=0, column=1, padx=(0, 10))
entry_start_ip.insert(0, "192.168.1.1")

lbl_end_ip = tk.Label(frame_scan, text="End IP:")
lbl_end_ip.grid(row=0, column=2, padx=(0, 5))

entry_end_ip = tk.Entry(frame_scan, width=16)
entry_end_ip.grid(row=0, column=3, padx=(0, 10))
entry_end_ip.insert(0, "192.168.1.254")

lbl_scan_port = tk.Label(frame_scan, text="Port:")
lbl_scan_port.grid(row=0, column=4, padx=(0, 5))

entry_scan_port = tk.Entry(frame_scan, width=7)
entry_scan_port.grid(row=0, column=5, padx=(0, 10))
entry_scan_port.insert(0, "443")

btn_scan = tk.Button(frame_scan, text="Scan", width=10, command=start_range_scan)
btn_scan.grid(row=0, column=6, padx=(0, 5))

btn_cancel_scan = tk.Button(
    frame_scan,
    text="Cancel Scan",
    width=12,
    command=cancel_range_scan,
    state="disabled",
)
btn_cancel_scan.grid(row=0, column=7)

show_all_scanned_var = tk.BooleanVar(value=False)
chk_show_all = tk.Checkbutton(
    frame_scan,
    text="Show all scanned IPs",
    variable=show_all_scanned_var,
)
chk_show_all.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

lbl_scan_progress = tk.Label(frame_scan, text="Ready to scan")
lbl_scan_progress.grid(row=1, column=3, columnspan=5, sticky="e", pady=(6, 0))
frame_scan.grid_columnconfigure(7, weight=1)

# ---- ด้านล่าง ----
frame_bottom = tk.Frame(root)
frame_bottom.pack(pady=10)

btn_check_sel = tk.Button(frame_bottom, text="Check Selected", width=15, command=check_selected)
btn_check_sel.grid(row=0, column=0, padx=5)

btn_check_all = tk.Button(frame_bottom, text="Check All", width=15, command=check_all)
btn_check_all.grid(row=0, column=1, padx=5)

btn_trace = tk.Button(frame_bottom, text="Trace Route", width=15, command=open_trace_route)
btn_trace.grid(row=0, column=2, padx=5)

btn_history = tk.Button(
    frame_bottom, text="Event History", width=15, command=open_event_history
)
btn_history.grid(row=0, column=3, padx=5)

btn_start_maintenance = tk.Button(
    frame_bottom, text="Start Maintenance", width=17, command=start_selected_maintenance
)
btn_start_maintenance.grid(row=0, column=4, padx=5)

btn_end_maintenance = tk.Button(
    frame_bottom, text="End Maintenance", width=17, command=end_selected_maintenance
)
btn_end_maintenance.grid(row=0, column=5, padx=5)

lbl_interval = tk.Label(frame_bottom, text="Interval (sec):")
lbl_interval.grid(row=1, column=0, pady=(10, 0))

entry_interval = tk.Entry(frame_bottom, width=8)
entry_interval.grid(row=1, column=1, sticky="w", pady=(10, 0))
entry_interval.insert(0, "5")

btn_start_auto = tk.Button(frame_bottom, text="Start Auto", width=15, command=start_auto)
btn_start_auto.grid(row=1, column=2, padx=5, pady=(10, 0))

btn_stop_auto = tk.Button(frame_bottom, text="Stop Auto", width=15, command=stop_auto, state="disabled")
btn_stop_auto.grid(row=1, column=3, padx=5, pady=(10, 0))

btn_save = tk.Button(frame_bottom, text="Save List", width=15, command=save_host_list)
btn_save.grid(row=2, column=0, padx=5, pady=(10, 0))

btn_load = tk.Button(frame_bottom, text="Load List", width=15, command=load_host_list)
btn_load.grid(row=2, column=1, padx=5, pady=(10, 0))

btn_theme = tk.Button(frame_bottom, text="Dark Mode", width=15, command=toggle_theme)
btn_theme.grid(row=2, column=2, padx=5, pady=(10, 0))

state_change_alerts_var = tk.BooleanVar(value=True)
chk_state_alerts = tk.Checkbutton(
    frame_bottom,
    text="State Change Alerts",
    variable=state_change_alerts_var,
)
chk_state_alerts.grid(row=2, column=3, padx=5, pady=(10, 0), sticky="w")

btn_hide_tray = tk.Button(
    frame_bottom, text="Hide to Tray", width=15, command=hide_main_window
)
btn_hide_tray.grid(row=3, column=0, padx=5, pady=(10, 0))

minimize_to_tray_var = tk.BooleanVar(value=False)
chk_minimize_tray = tk.Checkbutton(
    frame_bottom,
    text="Minimize to tray",
    variable=minimize_to_tray_var,
)
chk_minimize_tray.grid(row=3, column=1, padx=5, pady=(10, 0), sticky="w")

close_to_tray_var = tk.BooleanVar(value=True)
chk_close_tray = tk.Checkbutton(
    frame_bottom,
    text="Close button minimizes to tray",
    variable=close_to_tray_var,
)
chk_close_tray.grid(
    row=3, column=2, columnspan=2, padx=5, pady=(10, 0), sticky="w"
)

btn_notifications = tk.Button(
    frame_bottom,
    text="Notification Settings",
    width=20,
    command=open_notification_settings,
)
btn_notifications.grid(row=4, column=0, columnspan=2, padx=5, pady=(10, 0))

btn_notification_history = tk.Button(
    frame_bottom,
    text="Notification History",
    width=20,
    command=open_notification_history,
)
btn_notification_history.grid(row=4, column=2, columnspan=2, padx=5, pady=(10, 0))

btn_availability = tk.Button(
    frame_bottom, text="Availability Report", width=20, command=open_availability_report
)
btn_availability.grid(row=5, column=0, columnspan=4, padx=5, pady=(10, 0))

# โหลด config (theme + hosts) ก่อน apply_theme
load_config()
apply_theme(current_theme)

# handle ตอนปิด
root.protocol("WM_DELETE_WINDOW", on_close)
root.bind("<Unmap>", handle_root_unmap, add="+")
start_tray_support()
start_notification_support()
maintenance_after_id = root.after(1_000, poll_maintenance_expiry)

root.mainloop()
