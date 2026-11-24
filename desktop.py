"""Windows desktop entry point; packaged by PyInstaller, no Python setup at use."""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import sys
import threading
from datetime import datetime

from desktop_runtime import (application_home, HostService, load_settings, save_settings,
    normalize_host_url, open_workspace, read_health, local_addresses, import_workspace,
    keep_host_awake)
from version import APP_VERSION, PRODUCT, MUTEX_NAME

ROOT = Path(__file__).resolve().parent


def mutex():
    if os.name != "nt":
        return None, False
    from ctypes import wintypes
    create = ctypes.windll.kernel32.CreateMutexW
    create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    handle = create(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError()
    return handle, ctypes.windll.kernel32.GetLastError() == 183


def open_folder(path):
    path = Path(path)
    if os.name == "nt":
        os.startfile(str(path))


def configure_logging(home):
    folder = home / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "desktop.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


class Desktop:
    def __init__(self, home, settings, force_settings=False):
        import tkinter as tk
        from tkinter import ttk, messagebox, filedialog
        self.tk, self.ttk, self.messagebox, self.filedialog = tk, ttk, messagebox, filedialog
        self.home = home
        self.settings = settings or {"mode":"host", "port":8765, "host_url":"http://127.0.0.1:8765", "keep_awake":True}
        self.service = None
        self.busy = False
        self.results = queue.Queue()
        self.root = tk.Tk()
        self.root.title(PRODUCT)
        height = min(700, max(540, self.root.winfo_screenheight() - 110))
        self.root.geometry("760x" + str(height))
        self.root.minsize(680, 520)
        self.root.configure(bg="#f5f7fc")
        self.root.option_add("*Font", "{Arial} 11")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.root.iconbitmap(str(ROOT / "assets/ncsc.ico"))
        except tk.TclError:
            pass
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#f5f7fc")
        self.style.configure("TLabel", background="#f5f7fc", foreground="#26324b", font=("Arial",11))
        self.style.configure("TEntry", padding=9)
        self.style.configure("TCheckbutton", background="#f5f7fc", font=("Arial",10))
        self.style.configure("TButton", padding=(15,10), font=("Arial",11))
        self.style.configure("Primary.TButton", background="#243e96", foreground="white")
        self.style.map("Primary.TButton", background=[("active", "#1a317e")])
        self.style.configure("Danger.TButton", foreground="#ac2436")
        header = tk.Frame(self.root, bg="#14104f", padx=28, pady=20)
        header.pack(fill="x")
        try:
            from PIL import Image, ImageTk
            self.logo = ImageTk.PhotoImage(Image.open(ROOT / "assets/logo.jpg").resize((62,62)))
            tk.Label(header, image=self.logo, bg="#14104f").pack(side="left", padx=(0,15))
        except Exception:
            logging.exception("Desktop logo could not be loaded")
        tk.Label(header, text="NATIONAL COMMISSION\nOF SENIOR CITIZENS", font=("Arial",13,"bold"),
                 justify="left", fg="white", bg="#14104f").pack(side="left")
        tk.Label(header, text="REGIONAL OFFICE I", font=("Arial",10), fg="#ccd8ff", bg="#14104f").pack(side="right")
        tk.Frame(self.root, height=3, bg="#e51e2a").pack(fill="x")
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(container, bg="#f5f7fc", highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=(30,24))
        self.body_window = self.canvas.create_window((0,0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda event:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event:self.canvas.itemconfigure(self.body_window, width=event.width))
        self.canvas.bind_all("<MouseWheel>", lambda event:self.canvas.yview_scroll(-int(event.delta/120), "units"))
        self.status = tk.StringVar()
        self.root.after(100, self.check_results)
        if settings and not force_settings:
            self.show_settings()
            self.root.after(100, self.start_existing)
        else:
            self.show_settings()

    def label(self, parent, text, **kwargs):
        label = self.ttk.Label(parent, text=text, wraplength=600, justify="left", **kwargs)
        label.pack(anchor="w", pady=(0,12))
        return label

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.status.set("")
        self.canvas.yview_moveto(0)

    def status_label(self):
        self.ttk.Label(self.body, textvariable=self.status, foreground="#51627f", wraplength=640).pack(anchor="w", pady=(16,0))

    def show_settings(self):
        self.clear()
        self.label(self.body, "Workspace connection", font=("Arial",19,"bold"))
        self.label(self.body, "Choose this PC's role once. The app remembers your connection.")
        self.mode = self.tk.StringVar(value=self.settings["mode"])
        modes = self.ttk.Frame(self.body)
        modes.pack(fill="x", pady=(0,18))
        for text, value in [("Host workspace on this PC", "host"), ("Connect to office host", "client")]:
            self.tk.Radiobutton(modes, text=text, value=value, variable=self.mode, command=self.show_connection_fields,
                bg="#f5f7fc", activebackground="#f5f7fc", selectcolor="white", padx=8, pady=10).pack(side="left", padx=(0,16))
        self.fields = self.ttk.Frame(self.body)
        self.fields.pack(fill="x")
        self.url = self.tk.StringVar(value=self.settings["host_url"])
        self.port = self.tk.StringVar(value=str(self.settings["port"]))
        self.awake = self.tk.BooleanVar(value=self.settings["keep_awake"])
        self.show_connection_fields()
        actions = self.ttk.Frame(self.body)
        actions.pack(fill="x", pady=(24,0))
        self.start_button = self.ttk.Button(actions, text="Save & open workspace", command=self.save_and_start, style="Primary.TButton")
        self.start_button.pack(side="left")
        self.ttk.Button(actions, text="Open data folder", command=lambda:open_folder(self.home)).pack(side="left", padx=10)
        self.status_label()
        self.label(self.body, "Version " + APP_VERSION + " · Office test build", font=("Arial",9))

    def show_connection_fields(self):
        for child in self.fields.winfo_children():
            child.destroy()
        if self.mode.get() == "host":
            self.label(self.fields, "Keep this PC on and connected to the office LAN/Wi-Fi. Other departments use this PC's shared records.")
            line = self.ttk.Frame(self.fields)
            line.pack(anchor="w", pady=(0,12))
            self.ttk.Label(line, text="Host port").pack(side="left", padx=(0,16))
            self.ttk.Entry(line, textvariable=self.port, width=9).pack(side="left")
            self.ttk.Checkbutton(self.fields, text="Prevent idle sleep while hosting (the display may turn off)", variable=self.awake).pack(anchor="w", pady=(0,12))
            self.ttk.Button(self.fields, text="Import previous data folder…", command=self.import_data).pack(anchor="w")
        else:
            self.label(self.fields, "Enter the workspace address shown on the host PC. Internet hosting is not required.")
            self.ttk.Label(self.fields, text="Office host address").pack(anchor="w", pady=(0,6))
            self.ttk.Entry(self.fields, textvariable=self.url, width=52).pack(fill="x", pady=(0,12))
            self.ttk.Button(self.fields, text="Test connection", command=self.test_connection).pack(anchor="w")

    def work(self, function, done, label):
        if self.busy:
            return
        self.busy = True
        self.status.set(label)
        def run():
            try:
                self.results.put((done, function(), None))
            except Exception as error:
                logging.exception(label)
                self.results.put((done, None, error))
        threading.Thread(target=run, daemon=True).start()

    def check_results(self):
        try:
            done, result, error = self.results.get_nowait()
            self.busy = False
            if error:
                self.status.set(str(error))
                self.messagebox.showerror("NCSC RO1", str(error))
            else:
                done(result)
        except queue.Empty:
            pass
        try:
            self.root.after(100, self.check_results)
        except self.tk.TclError:
            pass

    def import_data(self):
        if self.busy:
            return
        if (self.home / "data/register.sqlite3").exists():
            self.messagebox.showinfo("Existing workspace", "This PC already has a workspace. It will not be overwritten. Back up the current data folder before requesting a migration.")
            return
        source = self.filedialog.askdirectory(title="Choose the old app's data folder")
        if not source:
            return
        if not self.messagebox.askokcancel("Import existing workspace", "Stop the old application first. Its accounts, records and files will be copied into this PC's new workspace. The original folder will be kept."):
            return
        self.work(lambda:import_workspace(source, self.home / "data"),
                  lambda _:self.status.set("Existing data imported. Choose Save & open workspace."), "Importing existing workspace…")

    def test_connection(self):
        try:
            url = normalize_host_url(self.url.get())
        except ValueError as error:
            self.messagebox.showerror("Host address", str(error))
            return
        def done(result):
            self.status.set("Connected to NCSC RO1 " + result["version"] + (". Ready to sign in." if result["configured"] else ". Ask ORD to complete first setup on the host PC."))
        self.work(lambda:read_health(url), done, "Checking the office host…")

    def save_and_start(self):
        if self.busy:
            return
        try:
            self.settings = save_settings(self.home, {"mode":self.mode.get(), "port":self.port.get(),
                "host_url":self.url.get(), "keep_awake":self.awake.get()})
            self.start_saved()
        except Exception as error:
            logging.exception("Workspace could not start")
            self.messagebox.showerror("NCSC RO1", str(error))

    def start_saved(self):
        if self.settings["mode"] == "client":
            def connected(result):
                if not result["configured"]:
                    self.status.set("Ask ORD to create the first administrator on the host PC, then retry.")
                    return
                try:
                    open_workspace(self.settings["host_url"])
                    self.root.destroy()
                except Exception as error:
                    self.messagebox.showerror("Open workspace", str(error))
            def probe():
                try:
                    return read_health(self.settings["host_url"])
                except Exception:
                    raise ValueError("The office host is unavailable. Check the saved address, office network and whether the host PC is on with NCSC RO1 running.") from None
            self.work(probe, connected, "Connecting to the office workspace…")
            return
        self.service = HostService(self.home / "data", self.settings["port"])
        try:
            self.service.start()
        except OSError as error:
            raise ValueError("The host port is unavailable. Close the old application or choose a different port.") from error
        if self.settings["keep_awake"]:
            keep_host_awake(True)
        self.show_host()
        try:
            open_workspace(self.service.local_url)
        except Exception as error:
            self.status.set(str(error))

    def start_existing(self):
        try:
            self.start_saved()
        except Exception as error:
            logging.exception("Saved workspace could not start")
            self.status.set(str(error))
            self.messagebox.showerror("NCSC RO1", str(error))

    def show_host(self):
        self.clear()
        self.label(self.body, "Workspace is running", font=("Arial",19,"bold"), foreground="#187847")
        self.label(self.body, "Staff can sign in from their own PCs. Minimize this control window to keep sharing. Closing it also minimizes it.")
        self.label(self.body, "On this PC: " + self.service.local_url)
        addresses = local_addresses(self.service.port)
        self.label(self.body, "Staff connection address", font=("Arial",11,"bold"))
        self.addresses = self.tk.StringVar(value="\n".join(addresses) if addresses else "Connect the host to the office LAN/Wi-Fi, then reopen the host window.")
        self.ttk.Label(self.body, textvariable=self.addresses, wraplength=640).pack(anchor="w", pady=(0,10))
        self.ttk.Button(self.body, text="Copy connection address", command=self.copy_address).pack(anchor="w", pady=(0,16))
        actions = self.ttk.Frame(self.body)
        actions.pack(fill="x", pady=(8,14))
        self.ttk.Button(actions, text="Open system", style="Primary.TButton", command=self.open_local).pack(side="left")
        self.ttk.Button(actions, text="Create backup…", command=self.backup).pack(side="left", padx=9)
        self.ttk.Button(actions, text="Minimize", command=self.root.iconify).pack(side="left")
        footer = self.ttk.Frame(self.body)
        footer.pack(fill="x", pady=(10,0))
        self.ttk.Button(footer, text="Open data folder", command=lambda:open_folder(self.home / "data")).pack(side="left")
        self.ttk.Button(footer, text="Stop & exit", style="Danger.TButton", command=self.stop).pack(side="right")
        self.status_label()
        self.label(self.body, "Keep the host PC on and its lid open. Idle sleep prevention does not override shutdown, forced sleep or a closed-lid policy.", font=("Arial",9))

    def copy_address(self):
        addresses = local_addresses(self.service.port)
        if addresses:
            self.addresses.set("\n".join(addresses))
            self.root.clipboard_clear()
            self.root.clipboard_append(addresses[0])
            self.status.set("Connection address copied. Use it on the staff PCs.")
        else:
            self.status.set("No office network address found. Check this PC's LAN/Wi-Fi connection.")

    def open_local(self):
        try:
            open_workspace(self.service.local_url)
        except Exception as error:
            self.messagebox.showerror("Open workspace", str(error))

    def backup(self):
        if self.busy:
            return
        destination = self.filedialog.asksaveasfilename(title="Save workspace backup", defaultextension=".zip",
            initialfile="NCSC-RO1-Backup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip", filetypes=[("ZIP backup", "*.zip")])
        if destination:
            self.work(lambda:self.service.backup(destination),
                lambda _:self.status.set("Backup saved. Keep it in a secure location; it includes accounts, records and attachments."),
                "Creating a consistent backup. Record changes will wait until the snapshot is copied…")

    def close(self):
        if self.busy:
            self.root.iconify()
        elif self.service and self.service.server:
            self.root.iconify()
        else:
            self.root.destroy()

    def stop(self):
        if self.busy:
            return
        if self.messagebox.askokcancel("Stop shared workspace?", "Other departments will lose access until this host is started again. Stop and exit?"):
            self.work(self.service.stop, lambda _:self.root.destroy(), "Finishing active requests and stopping the host…")

    def run(self):
        try:
            self.root.mainloop()
        finally:
            if self.service:
                self.service.stop()
            keep_host_awake(False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--ui-smoke-test", action="store_true")
    parser.add_argument("--self-test-report", type=Path)
    args = parser.parse_args()
    if args.ui_smoke_test:
        import tempfile
        result = {"ok":False, "frozen":bool(getattr(sys,"frozen",False))}
        ui = None
        try:
            with tempfile.TemporaryDirectory(prefix="ncsc-ui-test-") as directory:
                ui = Desktop(Path(directory), None, True)
                ui.root.update()
                assert hasattr(ui, "logo"), "The NCSC logo must load from the packaged resources"
                assert ui.start_button.winfo_exists()
                if args.self_test_report:
                    args.self_test_report.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        from PIL import ImageGrab
                        x,y = ui.root.winfo_rootx(),ui.root.winfo_rooty()
                        ImageGrab.grab((x,y,x+ui.root.winfo_width(),y+ui.root.winfo_height())).save(args.self_test_report.parent/"ui-host.png")
                    except Exception as error:
                        result["screenshot_note"] = type(error).__name__
                ui.mode.set("client")
                ui.show_connection_fields()
                ui.root.update()
                assert ui.url.get() == "http://127.0.0.1:8765"
                if args.self_test_report and "screenshot_note" not in result:
                    ImageGrab.grab((x,y,x+ui.root.winfo_width(),y+ui.root.winfo_height())).save(args.self_test_report.parent/"ui-client.png")
                result["ok"] = True
        except Exception as error:
            result["error"] = type(error).__name__ + ": " + str(error)
        finally:
            if ui:
                ui.root.destroy()
        if args.self_test_report:
            args.self_test_report.write_text(json.dumps(result,indent=2),encoding="utf-8")
        return 0 if result["ok"] else 1
    if args.self_test:
        from self_check import run
        result = run()
        if args.self_test_report:
            args.self_test_report.parent.mkdir(parents=True, exist_ok=True)
            args.self_test_report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if sys.stdout:
            print(json.dumps(result))
        return 0 if result["ok"] else 1
    home = application_home()
    home.mkdir(parents=True, exist_ok=True)
    configure_logging(home)
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NCSC.RO1.DocumentTracking")
        except Exception:
            pass
    from tkinter import messagebox
    handle, exists = mutex()
    try:
        if exists:
            if args.configure:
                messagebox.showinfo("NCSC RO1 is running", "Stop & exit the existing host window before changing connection settings.")
            else:
                settings = load_settings(home)
                if settings and settings["mode"] == "host":
                    open_workspace("http://127.0.0.1:" + str(settings["port"]))
                else:
                    messagebox.showinfo("NCSC RO1", "The connection window is already open. Select it from the taskbar.")
            return 0
        try:
            settings = load_settings(home)
        except ValueError as error:
            messagebox.showwarning("Connection settings", str(error))
            settings = None
        Desktop(home, settings, args.configure).run()
        return 0
    except Exception as error:
        logging.exception("Desktop startup failed")
        messagebox.showerror("NCSC RO1", str(error) + "\n\nLogs: " + str(home / "logs"))
        return 1
    finally:
        if handle:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


if __name__ == "__main__":
    raise SystemExit(main())
