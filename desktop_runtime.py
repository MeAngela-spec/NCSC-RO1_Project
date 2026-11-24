"""Desktop installation paths and office LAN lifecycle. No GUI on import."""
from contextlib import closing, nullcontext
import ipaddress
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from zipfile import ZipFile, ZIP_DEFLATED

from version import PRODUCT


def application_home():
    override = os.environ.get("NCSC_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "NCSCRO1"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "NCSCRO1"


def normalize_host_url(value):
    value = str(value).strip()
    if "://" not in value:
        value = "http://" + value
    parsed = urllib.parse.urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("Enter a valid host port, for example 8765.") from None
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment or
            any(character.isspace() for character in value)):
        raise ValueError("Enter only the office host address, for example http://192.168.1.20:8765.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Use a port between 1 and 65535.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def validate_settings(settings):
    if not isinstance(settings, dict) or settings.get("mode") not in ("host", "client"):
        raise ValueError("Choose Host workspace or Connect to office host.")
    try:
        port = int(settings.get("port", 8765))
    except (ValueError, TypeError):
        raise ValueError("Enter a valid host port.") from None
    if not 1024 <= port <= 65535:
        raise ValueError("Use a host port between 1024 and 65535.")
    return {"mode":settings["mode"], "port":port,
            "host_url":normalize_host_url(settings.get("host_url", "http://127.0.0.1:8765")),
            "keep_awake":bool(settings.get("keep_awake", True))}


def load_settings(home):
    path = Path(home) / "connection.json"
    if not path.exists():
        return None
    try:
        return validate_settings(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        raise ValueError("The saved connection could not be read. Review and save your connection settings.") from None


def save_settings(home, settings):
    settings = validate_settings(settings)
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=home, prefix="connection-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, home / "connection.json")
    finally:
        Path(name).unlink(missing_ok=True)
    return settings


def read_health(url, timeout=5):
    # Use the selected LAN host directly, without sending a local request
    # through an HTTP proxy configured for internet traffic.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(normalize_host_url(url) + "/api/health", timeout=timeout) as response:
        result = json.load(response)
    if result.get("product") != PRODUCT:
        raise ValueError("That address does not point to an NCSC RO1 workspace.")
    return result


def local_addresses(port):
    addresses = []
    try:
        entries = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
        for entry in entries:
            value = entry[4][0]
            if not ipaddress.ip_address(value).is_loopback and value not in addresses:
                addresses.append(value)
    except OSError:
        pass
    return ["http://" + address + ":" + str(port) for address in addresses]


def open_workspace(url):
    url = normalize_host_url(url)
    if os.name == "nt":
        for base, suffix in [
            ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
            ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
            ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
            ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
        ]:
            candidate = Path(os.environ.get(base, "")) / suffix
            if candidate.is_file():
                subprocess.Popen([str(candidate), "--app=" + url], close_fds=True)
                return
    if not webbrowser.open(url):
        raise ValueError("Open your browser and visit " + url + ".")


class HostService:
    def __init__(self, data, port=8765, address="0.0.0.0"):
        self.data = Path(data).resolve()
        self.port = port
        self.address = address
        self.server = None
        self.thread = None
        self.backend = None

    @property
    def local_url(self):
        return "http://127.0.0.1:" + str(self.port)

    def start(self):
        if self.server:
            return
        already = sys.modules.get("app")
        if already is not None and already.DATA.resolve() != self.data:
            raise RuntimeError("A different workspace is already loaded in this process.")
        os.environ["NCSC_DATA"] = str(self.data)
        import app
        app.init()
        # Keep unfinished requests alive during a graceful host shutdown.
        server = ThreadingHTTPServer((self.address, self.port), app.Handler)
        server.daemon_threads = False
        server.block_on_close = True
        self.backend = app
        self.server = server
        self.port = server.server_port
        self.thread = threading.Thread(target=server.serve_forever, name="NCSC-office-host", daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            self.server = None

    def backup(self, destination):
        if not self.backend:
            raise ValueError("Start the workspace before creating a backup.")
        return backup_workspace(self.data, destination, self.backend.LOCK)


def check_workspace(folder):
    folder = Path(folder)
    database = folder / "register.sqlite3"
    if not database.is_file():
        raise ValueError("Choose the old app's data folder containing register.sqlite3.")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("The selected database failed its integrity check.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "records", "collections", "files"}.issubset(tables):
            raise ValueError("The selected folder is not an NCSC workspace.")
    return folder


def import_workspace(source, destination):
    """Import an old data folder once; never overwrite an existing workspace."""
    source = check_workspace(Path(source).resolve())
    destination = Path(destination).resolve()
    if source == destination or (destination / "register.sqlite3").exists():
        raise ValueError("This PC already has a workspace. Keep it and back it up before making changes.")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("The destination data folder must be empty.")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Choose a normal backup folder without linked files.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ncsc-import-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "data"
        staged.mkdir()
        # SQLite's backup API also handles a checkpointed WAL database correctly.
        with closing(sqlite3.connect((source / "register.sqlite3").as_uri() + "?mode=ro", uri=True)) as old:
            with closing(sqlite3.connect(staged / "register.sqlite3")) as copied:
                old.backup(copied)
        for directory in ("files", "drafts"):
            if (source / directory).is_dir():
                shutil.copytree(source / directory, staged / directory)
        check_workspace(staged)
        if destination.exists():
            destination.rmdir()
        os.replace(staged, destination)


def backup_workspace(data, destination, lock=None):
    data, destination = Path(data).resolve(), Path(destination).resolve()
    check_workspace(data)
    if destination.is_relative_to(data):
        raise ValueError("Save the backup outside the workspace data folder.")
    if destination.exists():
        raise ValueError("Choose a new filename to preserve the existing backup.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ncsc-backup-") as directory:
        copied = Path(directory) / "data"
        copied.mkdir()
        with lock if lock is not None else nullcontext():
            with closing(sqlite3.connect(data / "register.sqlite3")) as source:
                with closing(sqlite3.connect(copied / "register.sqlite3")) as target:
                    source.backup(target)
            for name in ("files", "drafts"):
                if (data / name).is_dir():
                    shutil.copytree(data / name, copied / name)
        # Compress the completed snapshot after releasing the live write lock.
        temporary = destination.with_name(destination.name + ".pending")
        try:
            with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
                for file in copied.rglob("*"):
                    if file.is_file():
                        archive.write(file, Path("data") / file.relative_to(copied))
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def keep_host_awake(enabled):
    if os.name != "nt":
        return True
    import ctypes
    # Prevent idle system sleep only; leave the display and user sleep controls alone.
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if enabled else 0x80000000))
