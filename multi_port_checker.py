import os
import sys
import json
import locale
import queue
import subprocess
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk, messagebox, filedialog

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
    TcpStateTracker,
    alert_enabled_from_config,
    format_duration,
    make_host_record,
    normalize_host_record,
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

network_executor = ThreadPoolExecutor(max_workers=CHECK_WORKERS, thread_name_prefix="network-check")
trace_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="trace-route")
trace_windows = set()
tcp_state_tracker = TcpStateTracker()
current_theme = "light"   # "light" หรือ "dark"

# ไฟล์ config สำหรับจำ theme + host list
CONFIG_NAME = "mpc_config.json"
COL_NAME = 0
COL_HOST = 1
COL_PORT = 2
COL_PING = 3
COL_STATUS = 4


# ===================== Helper =====================

def get_app_dir() -> str:
    """ตำแหน่งโฟลเดอร์โปรแกรม (รองรับทั้ง .py และ .exe)"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path() -> str:
    return os.path.join(get_app_dir(), CONFIG_NAME)


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
        window.iconbitmap(resource_path("icon_network_transparent.ico"))
    except Exception:
        pass


# ===================== Logic: add / remove / update =====================

def add_target():
    global editing_item_id
    name = entry_name.get().strip()
    host = entry_host.get().strip()
    port_text = entry_port.get().strip()

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
        tree.item(
            editing_item_id,
            values=(name, host, port, ping_text, status_text),
        )
        if old_key != normalize_target_key(host, port):
            tcp_state_tracker.forget(editing_item_id)
        transient_scan_items.discard(editing_item_id)
        tree.selection_set(editing_item_id)
        finish_editing(clear_entries=False)
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
                values[COL_PING],
                values[COL_STATUS],
            ),
        )
        transient_scan_items.discard(existing_item)
        tree.selection_set(existing_item)
        tree.focus(existing_item)
        tree.see(existing_item)
        return

    tree.insert(
        "",
        "end",
        values=(name, host, port, "N/A", "Not checked"),
        tags=("unknown",),
    )


def finish_editing(clear_entries: bool = False):
    global editing_item_id
    editing_item_id = None
    btn_add.config(text="Add")
    if clear_entries:
        entry_name.delete(0, "end")


def edit_selected():
    global editing_item_id
    selected = tree.selection()
    if len(selected) != 1:
        messagebox.showinfo("Edit Selected", "Please select exactly one target to edit.")
        return
    values = tree.item(selected[0], "values")
    if len(values) < 5:
        return
    editing_item_id = selected[0]
    for entry_widget, value in (
        (entry_name, values[COL_NAME]),
        (entry_host, values[COL_HOST]),
        (entry_port, values[COL_PORT]),
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
        transient_scan_items.discard(item)
        tcp_state_tracker.forget(item)
        tree.delete(item)
    if editing_item_id in selected:
        finish_editing(clear_entries=False)


def find_existing_target(host: str, port: int, exclude_item=None):
    """Find an existing row by normalized Host/IP + Port."""
    wanted_key = normalize_target_key(host, port)
    for item_id in tree.get_children():
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
        len(values) < 5
        or values[COL_HOST] != host
        or str(values[COL_PORT]) != str(port)
    ):
        return None

    status_text = "✅ ONLINE" if ok else "❌ OFFLINE"
    tag = "online" if ok else "offline"
    tree.item(
        item_id,
        values=(values[COL_NAME], host, port, ping_text, status_text),
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
    }


def show_state_change_alerts(alerts):
    """Display state changes from Tk's main thread with simple flood protection."""
    if not alerts or not state_change_alerts_var.get():
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
    show_state_change_alerts(alerts)
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
    items = tree.get_children()
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
            values=("", host, port, ping_text, "Not checked"),
            tags=("unknown",),
        )
        transient_scan_items.add(item_id)
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
        name, host, port, _ping, _status = tree.item(item, "values")
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            port_int = port
        data.append(make_host_record(name, host, port_int))

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
    transient_scan_items.clear()
    tcp_state_tracker.clear()
    finish_editing(clear_entries=False)
    for item in tree.get_children():
        tree.delete(item)

    # เพิ่มใหม่
    for entry in data:
        if not isinstance(entry, dict):
            continue
        record = normalize_host_record(entry)
        name, host, port = record["name"], record["host"], record["port"]
        if not host:
            continue
        tree.insert(
            "",
            "end",
            values=(name, host, port, "N/A", "Not checked"),
            tags=("unknown",),
        )


# ===================== Config: auto-save theme + hosts =====================

def save_config():
    """บันทึก theme + host list ลงไฟล์ config"""
    items = tree.get_children()
    hosts = []
    for item in items:
        if item in transient_scan_items:
            continue
        name, host, port, _ping, _status = tree.item(item, "values")
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            port_int = port
        hosts.append(make_host_record(name, host, port_int))

    config = {
        "theme": current_theme,
        "state_change_alerts": bool(state_change_alerts_var.get()),
        "hosts": hosts,
    }

    try:
        with open(get_config_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        # ไม่ต้องขึ้น popup เพราะเป็นตอนปิดโปรแกรม
        print("Save config error:", e)


def load_config():
    """อ่าน config ถ้ามี แล้ว set theme + เติม host list ให้"""
    global current_theme
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

    # hosts
    hosts = config.get("hosts", [])
    if not isinstance(hosts, list):
        return
    for entry in hosts:
        if not isinstance(entry, dict):
            continue
        record = normalize_host_record(entry)
        name, host, port = record["name"], record["host"], record["port"]
        if not host:
            continue
        tree.insert(
            "",
            "end",
            values=(name, host, port, "N/A", "Not checked"),
            tags=("unknown",),
        )


def on_close():
    """เรียกตอนกดปิดหน้าต่าง"""
    global auto_running
    auto_running = False
    if scan_running and scan_plan is not None:
        scan_plan.cancel()
        for future in tuple(scan_pending):
            future.cancel()
    if auto_after_id is not None:
        try:
            root.after_cancel(auto_after_id)
        except tk.TclError:
            pass
    for trace_window in tuple(trace_windows):
        trace_window.close()
    save_config()
    network_executor.shutdown(wait=False, cancel_futures=True)
    trace_executor.shutdown(wait=False, cancel_futures=True)
    root.destroy()


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
    auto_loop()


def stop_auto():
    global auto_running, auto_after_id
    auto_running = False
    if auto_after_id is not None:
        root.after_cancel(auto_after_id)
        auto_after_id = None
    btn_start_auto.config(state="normal")
    btn_stop_auto.config(state="disabled")


def auto_loop():
    global auto_after_id
    auto_after_id = None
    if not auto_running:
        return
    if check_in_progress:
        auto_after_id = root.after(100, auto_loop)
        return

    items = tree.get_children()
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
        entry_host,
        entry_port,
        entry_interval,
        entry_start_ip,
        entry_end_ip,
        entry_scan_port,
    ):
        ent.configure(bg=entry_bg, fg=entry_fg, insertbackground=entry_fg)

    for checkbox in (chk_show_all, chk_state_alerts):
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
        btn_check_sel,
        btn_check_all,
        btn_trace,
        btn_start_auto,
        btn_stop_auto,
        btn_save,
        btn_load,
        btn_theme,
        btn_scan,
        btn_cancel_scan,
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

    for trace_window in tuple(trace_windows):
        trace_window.apply_theme(theme)


# ===================== GUI =====================

root = tk.Tk()
root.title("Multi Host Port Checker (with Ping)")
root.geometry("1050x650")
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
entry_host.insert(0, "google.com")

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

# ---- ตาราง ----
frame_table = tk.Frame(root)
frame_table.pack(pady=5, padx=10, fill="both", expand=True)

columns = ("name", "host", "port", "ping", "status")
tree = ttk.Treeview(frame_table, columns=columns, show="headings", height=14)

tree.heading("name", text="Device Name")
tree.heading("host", text="Host / IP")
tree.heading("port", text="Port")
tree.heading("ping", text="Ping (ms)")
tree.heading("status", text="Status")

tree.column("name", width=190)
tree.column("host", width=270)
tree.column("port", width=70, anchor="center")
tree.column("ping", width=100, anchor="center")
tree.column("status", width=190)

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

# โหลด config (theme + hosts) ก่อน apply_theme
load_config()
apply_theme(current_theme)

# handle ตอนปิด
root.protocol("WM_DELETE_WINDOW", on_close)

root.mainloop()
