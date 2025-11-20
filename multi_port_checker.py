import os
import sys
import socket
import tkinter as tk
from tkinter import ttk, messagebox

# flag สำหรับ auto refresh
auto_running = False
def resource_path(relative_path: str) -> str:
    """ใช้หา path ไฟล์เวลา run จาก .py และจาก .exe (PyInstaller)"""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ฟังก์ชันตรวจสอบ host:port ทีละตัว
def check_single_host_port(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

# กดปุ่ม Add -> เพิ่มรายการเข้า Table
def add_target():
    host = entry_host.get().strip()
    port_text = entry_port.get().strip()

    if not host:
        messagebox.showwarning("Input Error", "กรุณาใส่ Host หรือ IP")
        return

    if not port_text.isdigit():
        messagebox.showwarning("Input Error", "Port ต้องเป็นตัวเลขเท่านั้น")
        return

    port = int(port_text)

    # เพิ่มเข้า Treeview
    tree.insert("", "end", values=(host, port, "Not checked"), tags=("unknown",))

# ลบรายการที่เลือก
def remove_selected():
    selected = tree.selection()
    if not selected:
        messagebox.showinfo("Remove", "กรุณาเลือกอย่างน้อย 1 รายการ")
        return

    for item in selected:
        tree.delete(item)

# เช็คทุก Host/Port ในลิสต์
def check_all():
    items = tree.get_children()
    if not items:
        messagebox.showinfo("Check All", "ยังไม่มีรายการให้เช็ค")
        return

    for item in items:
        host, port_text, _status = tree.item(item, "values")
        try:
            port = int(port_text)
        except ValueError:
            continue

        ok = check_single_host_port(host, port)
        if ok:
            new_status = "✅ ONLINE"
            tag = "online"
        else:
            new_status = "❌ OFFLINE"
            tag = "offline"

        tree.item(item, values=(host, port, new_status), tags=(tag,))

# เช็คเฉพาะรายการที่เลือก
def check_selected():
    selected = tree.selection()
    if not selected:
        messagebox.showinfo("Check Selected", "กรุณาเลือกรายการที่ต้องการเช็ค")
        return

    for item in selected:
        host, port_text, _status = tree.item(item, "values")
        try:
            port = int(port_text)
        except ValueError:
            continue

        ok = check_single_host_port(host, port)
        if ok:
            new_status = "✅ ONLINE"
            tag = "online"
        else:
            new_status = "❌ OFFLINE"
            tag = "offline"

        tree.item(item, values=(host, port, new_status), tags=(tag,))

# ===== ส่วน Auto Refresh =====
def start_auto():
    global auto_running
    # อ่านค่า interval
    interval_text = entry_interval.get().strip()
    if not interval_text.isdigit():
        messagebox.showwarning("Interval Error", "Interval ต้องเป็นตัวเลข (วินาที)")
        return

    if int(interval_text) <= 0:
        messagebox.showwarning("Interval Error", "Interval ต้องมากกว่า 0 วินาที")
        return

    auto_running = True
    btn_start_auto.config(state="disabled")
    btn_stop_auto.config(state="normal")
    auto_loop()  # เริ่ม loop

def stop_auto():
    global auto_running
    auto_running = False
    btn_start_auto.config(state="normal")
    btn_stop_auto.config(state="disabled")

def auto_loop():
    """ฟังก์ชันที่จะถูกเรียกซ้ำด้วย after()"""
    if not auto_running:
        return

    # เช็คทุก host
    check_all()

    # อ่าน interval อีกครั้ง เผื่อผู้ใช้เปลี่ยนค่า
    interval_text = entry_interval.get().strip()
    try:
        interval_sec = int(interval_text)
    except ValueError:
        interval_sec = 5  # fallback

    # แปลงวินาที -> มิลลิวินาที
    root.after(interval_sec * 1000, auto_loop)

# ===== สร้างหน้าต่างหลัก =====
root = tk.Tk()
root.title("Multi Host Port Checker")

try:
    icon_path = resource_path("icon_network_transparent.ico")
    root.iconbitmap(icon_path)
except Exception:
    pass


# ===== ส่วนบน: กรอก Host / Port + ปุ่ม Add / Remove =====
frame_top = tk.Frame(root)
frame_top.pack(pady=10, padx=10, fill="x")

lbl_host = tk.Label(frame_top, text="Host / IP:")
lbl_host.grid(row=0, column=0, padx=(0, 5))

entry_host = tk.Entry(frame_top, width=25)
entry_host.grid(row=0, column=1, padx=(0, 10))
entry_host.insert(0, "google.com")

lbl_port = tk.Label(frame_top, text="Port:")
lbl_port.grid(row=0, column=2, padx=(0, 5))

entry_port = tk.Entry(frame_top, width=8)
entry_port.grid(row=0, column=3, padx=(0, 10))
entry_port.insert(0, "80")

btn_add = tk.Button(frame_top, text="Add", command=add_target, width=10)
btn_add.grid(row=0, column=4, padx=(0, 5))

btn_remove = tk.Button(frame_top, text="Remove Selected", command=remove_selected, width=15)
btn_remove.grid(row=0, column=5)

# ===== ส่วนกลาง: ตารางแสดง Host / Port / Status =====
frame_table = tk.Frame(root)
frame_table.pack(pady=5, padx=10, fill="both", expand=True)

columns = ("host", "port", "status")

tree = ttk.Treeview(frame_table, columns=columns, show="headings", height=10)
tree.heading("host", text="Host / IP")
tree.heading("port", text="Port")
tree.heading("status", text="Status")

tree.column("host", width=260)
tree.column("port", width=70, anchor="center")
tree.column("status", width=220)

tree.tag_configure("online", background="green", foreground="white")
tree.tag_configure("offline", background="red", foreground="white")
tree.tag_configure("unknown", background="lightgray", foreground="black")

scrollbar_y = ttk.Scrollbar(frame_table, orient="vertical", command=tree.yview)
tree.configure(yscrollcommand=scrollbar_y.set)

tree.pack(side="left", fill="both", expand=True)
scrollbar_y.pack(side="right", fill="y")

# ===== ส่วนล่าง: ปุ่ม Check + Auto Refresh =====
frame_bottom = tk.Frame(root)
frame_bottom.pack(pady=10)

btn_check_sel = tk.Button(frame_bottom, text="Check Selected", width=15, command=check_selected)
btn_check_sel.grid(row=0, column=0, padx=5)

btn_check_all = tk.Button(frame_bottom, text="Check All", width=15, command=check_all)
btn_check_all.grid(row=0, column=1, padx=5)

# Interval + Auto buttons
lbl_interval = tk.Label(frame_bottom, text="Interval (sec):")
lbl_interval.grid(row=1, column=0, pady=(10, 0))

entry_interval = tk.Entry(frame_bottom, width=8)
entry_interval.grid(row=1, column=1, sticky="w", pady=(10, 0))
entry_interval.insert(0, "5")  # ค่าเริ่มต้น 5 วินาที

btn_start_auto = tk.Button(frame_bottom, text="Start Auto", width=15, command=start_auto)
btn_start_auto.grid(row=1, column=2, padx=5, pady=(10, 0))

btn_stop_auto = tk.Button(frame_bottom, text="Stop Auto", width=15, command=stop_auto, state="disabled")
btn_stop_auto.grid(row=1, column=3, padx=5, pady=(10, 0))

root.mainloop()
