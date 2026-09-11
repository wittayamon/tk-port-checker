"""Compact Tk dialogs; all callbacks and config snapshots run on Tk's thread."""

from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from settings_backup import (BackupError, atomic_write_json, build_backup,
                             plan_restore, read_backup)


class SettingsBackupWindow:
    def __init__(self, parent, *, snapshot, restore, on_close, palette, icon):
        self.snapshot, self.restore, self.on_close = snapshot, restore, on_close
        self.window = tk.Toplevel(parent)
        self.window.title("Backup / Restore Settings")
        self.window.geometry("540x240")
        self.window.resizable(False, False)
        icon(self.window)
        self.widgets = []
        note = tk.Label(self.window, text="Portable settings and targets only.\nNotification endpoints, runtime history and startup registration\nare excluded. Active maintenance is not imported.", justify="left")
        note.pack(padx=16, pady=18, anchor="w")
        self.widgets.append(note)
        for title, action in (("Export Settings", self.export), ("Import Settings / Preview", self.preview), ("Close", self.close)):
            button = tk.Button(self.window, text=title, width=28, command=action)
            button.pack(pady=4)
            self.widgets.append(button)
        self.palette = palette
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def apply_theme(self, theme):
        self.theme = theme
        colors = self.palette(theme)
        self.window.configure(bg=colors["bg"])
        for widget in self.widgets:
            widget.configure(bg=colors["bg"], fg=colors["fg"])

    def close(self):
        self.on_close(self)
        self.window.destroy()

    def export(self):
        try:
            payload = build_backup(self.snapshot())
            path = filedialog.asksaveasfilename(parent=self.window, title="Export Settings",
                initialfile=datetime.now().strftime("MultiPortChecker-Backup-%Y%m%d-%H%M%S.json"),
                defaultextension=".json", filetypes=[("Settings backup JSON", "*.json")])
            if not path:
                return
            atomic_write_json(path, payload)
        except (OSError, ValueError):
            messagebox.showerror("Settings Backup", "Backup could not be created. Check the targets and destination permissions.", parent=self.window)
            return
        messagebox.showinfo("Settings Backup", "Backup created successfully.", parent=self.window)

    def preview(self):
        path = filedialog.askopenfilename(parent=self.window, title="Import Settings",
            filetypes=[("Settings backup JSON", "*.json")])
        if not path:
            return
        try:
            backup = read_backup(path)
        except BackupError as error:
            messagebox.showerror("Import Settings", str(error), parent=self.window)
            return
        except OSError:
            messagebox.showerror("Import Settings", "Could not read the backup file.", parent=self.window)
            return
        dialog = tk.Toplevel(self.window)
        dialog.title("Import Preview")
        dialog.transient(self.window)
        dialog.grab_set()
        colors = self.palette(self.theme)
        dialog.configure(bg=colors["bg"])
        text_colors = dict(bg=colors["bg"], fg=colors["fg"])
        choice_colors = dict(**text_colors, selectcolor=colors["entry_bg"],
            activebackground=colors["bg"], activeforeground=colors["fg"])
        choices = {key: tk.BooleanVar(value=True) for key in ("targets", "preferences", "notifications")}
        mode = tk.StringVar(value="merge")
        summary = tk.StringVar()

        def selection():
            return {key: var.get() for key, var in choices.items()} | {"mode": mode.get()}

        def refresh():
            try:
                plan = plan_restore(self.snapshot(), backup, **selection())
            except (ValueError, TypeError):
                summary.set("Current configuration cannot be planned safely.")
                return
            payload = backup.payload
            groups = {g.casefold() for t in payload["targets"] for g in t["groups"]}
            counts = plan.counts
            summary.set(f"Source App Version: {payload['app_version']}\nBackup Format: {payload['backup_version']}\nCreated At: {payload['created_at']}\n"
                f"Targets: {len(payload['targets'])}   Groups: {len(groups)}\n"
                f"Theme: {payload['settings'].get('theme', 'not included')}\n"
                f"New: {counts['new']}   Matching: {counts['matching']}\n"
                f"Changed names: {counts['names']}   Changed groups: {counts['groups']}\n"
                f"Invalid: {backup.invalid}   Duplicates: {backup.duplicates}\n\n"
                "Secrets: not imported; local endpoints remain unchanged.\n"
                "Active maintenance: not restored (Merge preserves matching local state).\n"
                "Windows startup registration and runtime history remain local.\n" + "\n".join(plan.warnings))

        tk.Label(dialog, textvariable=summary, justify="left", wraplength=570, **text_colors).pack(padx=16, pady=12, anchor="w")
        for key, label in (("targets", "Monitored Targets / Device Names / Groups"), ("preferences", "Application Preferences"), ("notifications", "Notification Behavior Settings")):
            tk.Checkbutton(dialog, text=label, variable=choices[key], command=refresh, **choice_colors).pack(anchor="w", padx=16)
        for value in ("merge", "replace"):
            tk.Radiobutton(dialog, text=value.title(), variable=mode, value=value, command=refresh, **choice_colors).pack(anchor="w", padx=16)

        def apply():
            if not any(var.get() for var in choices.values()):
                messagebox.showinfo("Import Settings", "Select at least one category.", parent=dialog)
                return
            replace = choices["targets"].get() and mode.get() == "replace"
            question = ("Replace the entire configured target list? Local targets absent from this backup will be removed and maintenance reset.\n\n" if replace else "Apply the selected backup categories?\n\n")
            if not messagebox.askyesno("Confirm Replace" if replace else "Confirm Import", question + "A portable safety backup will be created first.", parent=dialog):
                return
            try:
                result = self.restore(backup, selection(), replace)
            except BackupError as error:
                messagebox.showerror("Import Settings", str(error), parent=dialog)
                return
            except (OSError, ValueError, tk.TclError):
                messagebox.showerror("Import Settings", "Import failed. Previous settings were retained; check destination permissions.", parent=dialog)
                return
            dialog.destroy()
            messagebox.showinfo("Import Settings", result, parent=self.window)

        ttk.Button(dialog, text="Import", command=apply).pack(side="left", padx=16, pady=14)
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).pack(side="right", padx=16, pady=14)
        refresh()
