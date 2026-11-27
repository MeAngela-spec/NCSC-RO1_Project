"""Packaged app verification with fictional records in a temporary workspace."""
import http.cookiejar
from contextlib import closing
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
from zipfile import ZipFile

from desktop_runtime import HostService, read_health, import_workspace
from version import APP_VERSION


class Client:
    def __init__(self, url):
        self.url, self.csrf = url, ""
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, body=None, expected=200, upload=None):
        headers, data = {}, None
        if upload:
            boundary = "ncsc-self-check-boundary-763551"
            name, content = upload
            pieces = [("--"+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+name+'"\r\nContent-Type: application/octet-stream\r\n\r\n').encode(), content, b"\r\n"]
            for key, value in (body or {}).items():
                pieces.append(("--"+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+str(value)+"\r\n").encode())
            pieces.append(("--"+boundary+"--\r\n").encode())
            data = b"".join(pieces)
            headers["Content-Type"] = "multipart/form-data; boundary="+boundary
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if data is not None:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(self.url + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=180) as response:
                code, raw, kind = response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            code, raw, kind = error.code, error.read(), error.headers.get("Content-Type", "")
        result = json.loads(raw) if "application/json" in kind else raw
        if code != expected:
            raise AssertionError(path + " returned " + str(code) + " instead of " + str(expected) + ": " + str(result)[:240])
        return result


def run():
    report = {"ok":False, "version":APP_VERSION, "frozen":bool(getattr(sys, "frozen", False)), "checks":[]}
    def passed(name):
        report["checks"].append(name)
    service = None
    try:
        with tempfile.TemporaryDirectory(prefix="ncsc-self-check-") as folder:
            home = Path(folder)
            service = HostService(home / "data", port=0, address="127.0.0.1")
            service.start()
            app = service.backend
            with app.connect() as connection:
                assert connection.execute("SELECT 1").fetchone()[0] == 1
            try:
                connection.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                passed("Database connections release file handles after each transaction")
            else:
                raise AssertionError("A finished database context kept its connection open")
            assert not read_health(service.local_url)["configured"]
            for filename in ["index.html", "printing.html", "assets/app.js", "assets/style.css", "assets/login.css", "assets/logo.jpg",
                             "assets/matrix-letterhead.png", "assets/matrix-print.js", "templates/routing-slip.docx"]:
                assert (app.ROOT / filename).is_file(), filename
            passed("Application resource paths and initial workspace health")

            # Simulate a LAN caller while retaining a real local HTTP exchange.
            def remote_handler(request, address, server):
                app.Handler(request, ("192.0.2.20", address[1]), server)
            remote = ThreadingHTTPServer(("127.0.0.1", 0), remote_handler)
            worker = threading.Thread(target=remote.serve_forever, daemon=True)
            worker.start()
            try:
                Client("http://127.0.0.1:"+str(remote.server_port)).request("/api/setup",
                    {"username":"test.admin", "name":"Fictional administrator", "password":"fixture-password-123"}, expected=403)
            finally:
                remote.shutdown()
                remote.server_close()
                worker.join()
            passed("First administrator setup is restricted to the host PC")

            admin = Client(service.local_url)
            admin.request("/api/setup", {"username":"test.admin", "name":"Fictional administrator", "password":"fixture-password-123"})
            admin.csrf = admin.request("/api/me")["csrf"]
            assert read_health(service.local_url)["configured"]
            admin.request("/api/users", {"username":"test.staff", "name":"Fictional OPS staff", "password":"fixture-password-123", "role":"staff", "department":"OPS"})
            staff_id = next(row["id"] for row in admin.request("/api/users") if row["username"] == "test.staff")
            staff = Client(service.local_url)
            staff.request("/api/login", {"username":"test.staff", "password":"fixture-password-123"})
            staff.csrf = staff.request("/api/me")["csrf"]
            first = admin.request("/api/new", {"cells":{"Subject":"Fictional outreach coordination", "Assigned to":"OPS", "Requested Actions":"4 - Appropriate Staff Action"}})["id"]
            second = admin.request("/api/new", {"cells":{"Subject":"Fictional budget review", "Assigned to":"AFS"}})["id"]
            assert len(staff.request("/api/register")) == 1
            staff.request("/api/record/"+second, expected=403)
            row = staff.request("/api/record/"+first)
            staff.request("/api/save", {"id":first, "version":row["version"], "cells":{**row["cells"], "Action Taken":"Under review", "Status":"Ongoing"}})
            row = admin.request("/api/record/"+first)
            assert any("test.staff" in event["actor"] for event in row["events"])
            passed("Login, routing, department permissions, updates and actor history")

            pdf_source = (app.ROOT / "samples/demo-document.pdf").read_bytes()
            admin.request("/api/attach", {"record":first, "version":row["version"], "kind":"MOV", "slot":1}, upload=("Fictional-MOV.pdf", pdf_source))
            row = admin.request("/api/record/"+first)
            assert row["movs"]["MOV 1"][0]["name"] == "Fictional-MOV.pdf"
            file_id = next(file["id"] for file in row["files"] if file["name"] == "Fictional-MOV.pdf")
            assert admin.request("/api/file/"+file_id) == pdf_source
            assert admin.request("/api/file-preview/"+file_id).startswith(b"%PDF")
            passed("MOV uploads, original byte retention and PDF viewing")

            source = admin.request("/api/document-draft", {}, upload=("Fictional-email.eml", (app.ROOT / "samples/demo-email.eml").read_bytes()))
            assert source["info"]["type"] == "Email"
            preview = admin.request("/api/preview", {}, upload=("Fictional-matrix.xlsx", (app.ROOT / "samples/adaptive-layout.xlsx").read_bytes()))
            assert preview["datasets"]
            imported = admin.request("/api/import", {"token":preview["token"], "datasets":[{"index":0,"mappings":preview["datasets"][0]["mappings"]}]})
            assert imported["collections"]
            passed("Saved email intake and adaptive spreadsheet import")

            for kind, magic in [("xlsx", b"PK"), ("docx", b"PK")]:
                assert admin.request("/api/export", {"ids":[first,second], "format":kind}).startswith(magic)
            assert admin.request("/api/docx/"+first).startswith(b"PK")
            converter = app.office_converter()
            report["print_converter"] = "bundled" if converter and Path(converter).is_relative_to(app.ROOT) else "external" if converter else "unavailable"
            if report["frozen"]:
                assert report["print_converter"] == "bundled", "The full Windows installer must include its print converter"
            if converter:
                import pypdfium2
                result = admin.request("/api/print-batch", {"ids":[first,second], "mode":"combined"})
                assert result.startswith(b"%PDF")
                document = pypdfium2.PdfDocument(result)
                assert len(document) >= 1
                document[0].render(scale=1).close()
                document.close()
                assert admin.request("/api/export", {"ids":[first,second], "format":"pdf"}).startswith(b"%PDF")
                job = admin.request("/api/print-job", {"ids":[first], "mode":"individual"})
                assert job["pages"]
                passed("Bundled original-template printing, PDF rendering and PDF export")
            passed("Excel, Word and exact routing-template downloads")

            row = admin.request("/api/record/"+first)
            other = admin.request("/api/record/"+second)
            admin.request("/api/archive-batch", {"items":[{"id":first,"version":row["version"]},{"id":second,"version":other["version"]-1}]}, expected=409)
            assert not admin.request("/api/record/"+first)["deleted_at"]
            admin.request("/api/archive-batch", {"items":[{"id":first,"version":row["version"]}]})
            row = admin.request("/api/record/"+first)
            admin.request("/api/restore", {"id":first,"version":row["version"]})
            admin.request("/api/account-archive", {"id":staff_id})
            assert staff.request("/api/me")["user"] is None
            admin.request("/api/account-restore", {"id":staff_id})
            restored = next(user for user in admin.request("/api/users") if user["id"] == staff_id)
            assert restored["active"] == 0 and restored["archived_at"] is None
            passed("Atomic selected deletion, restoration and account archive session invalidation")

            backup = service.backup(home / "backup.zip")
            restored_folder = home / "extracted"
            with ZipFile(backup) as archive:
                archive.extractall(restored_folder)
            import_workspace(restored_folder / "data", home / "imported")
            with closing(sqlite3.connect(home / "imported/register.sqlite3")) as restored_db:
                assert restored_db.execute("SELECT COUNT(*) FROM records").fetchone()[0] == len(admin.request("/api/register"))
            assert (home / "imported/files" / file_id).read_bytes() == pdf_source
            passed("Consistent live backup and safe existing-workspace import")
            service.stop()
            service = None
            report["ok"] = True
    except Exception as error:
        report["ok"] = False
        report["error"] = type(error).__name__ + ": " + str(error)
        report["traceback"] = traceback.format_exc()
    finally:
        if service:
            service.stop()
    return report
