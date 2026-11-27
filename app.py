"""NCSC RO1 offline LAN document register. Python 3.11+."""
import argparse
import csv
import hashlib
import hmac
import html
import io
import json
import mimetypes
import os
import re
from pathlib import Path
import secrets
import copy
import shutil
import subprocess
import tempfile
from zipfile import ZipFile
import sqlite3
import sys
import threading
import time
import urllib.parse
import uuid
import ipaddress
from datetime import datetime
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from render_cache import RenderCache

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))
DATA = Path(os.environ.get("NCSC_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
FILES = DATA / "files"
FILES.mkdir(exist_ok=True)
DRAFTS = DATA / "drafts"
DRAFTS.mkdir(exist_ok=True)
DB = DATA / "register.sqlite3"
LOCK = threading.Lock()
SESSIONS = {}
LOGIN_ATTEMPTS = {}
RENDER_CACHE = RenderCache()
DEPARTMENTS = {"ORD": "Office of the Regional Director", "AFS": "Administrative and Finance Section", "OPS": "Operations"}
ACTIONS = ["Approved", "Disapproved", "Request Initial/Signature", "Appropriate Staff Action",
           "Comment/Recommendation", "Rewrite/Redraft", "For Reference/Information",
           "See Me / Call Me", "File"]
STANDARD = ["Hard Copy Routed", "Ref. No.", "Subject", "Assigned to", "Requested Actions",
            "Action Taken", "MOV 1", "MOV 2", "Status"]
ALIASES = {
    "refno": "reference", "referenceno": "reference", "referencenumber": "reference", "drn": "reference",
    "subject": "subject", "assignedto": "assigned", "requestedactions": "action",
    "requestedaction": "action", "status": "status", "hardcopyroute": "hard",
    "hardcopyrouted": "hard", "actiontaken":"taken", "hardcopyroutedon": "hard",
    "title":"subject", "documentsubject":"subject", "documenttitle":"subject",
    "referencenumber":"reference", "documentno":"reference", "documentnumber":"reference",
    "assigneddepartment":"assigned", "responsibleoffice":"assigned", "assignedoffice":"assigned",
    "actionrequired":"action", "requestedaction":"action", "documentstatus":"status",
}
def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")

class WorkspaceConnection(sqlite3.Connection):
    """Commit/rollback and release the SQLite file handle on context exit."""
    def __exit__(self, *error):
        try:
            return super().__exit__(*error)
        finally:
            self.close()

def connect():
    c = sqlite3.connect(DB, timeout=30, factory=WorkspaceConnection)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240000).hex()
    return salt + ":" + digest

def password_ok(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)

def init():
    with connect() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL, department TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY, name TEXT NOT NULL, columns TEXT NOT NULL,
            mappings TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections(id),
            cells TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, record_id TEXT REFERENCES records(id),
            collection_id TEXT REFERENCES collections(id), name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
            at TEXT NOT NULL, actor TEXT NOT NULL, message TEXT NOT NULL, route TEXT);
        """)
        user_columns = {row["name"] for row in c.execute("PRAGMA table_info(users)")}
        if "recovery" not in user_columns:
            c.execute("ALTER TABLE users ADD COLUMN recovery TEXT")
        for column, definition in {"active":"INTEGER NOT NULL DEFAULT 1", "account_type":"TEXT NOT NULL DEFAULT 'individual'", "archived_at":"TEXT", "deleted_at":"TEXT"}.items():
            if column not in user_columns:
                c.execute("ALTER TABLE users ADD COLUMN " + column + " " + definition)
                if column == "account_type":
                    c.execute("UPDATE users SET account_type='department' WHERE UPPER(username) IN ('ORD','AFS','OPS')")
        record_columns = {row["name"] for row in c.execute("PRAGMA table_info(records)")}
        if "deleted_at" not in record_columns:
            c.execute("ALTER TABLE records ADD COLUMN deleted_at TEXT")
        if "assigned_user_id" not in record_columns:
            c.execute("ALTER TABLE records ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
        if "routing_revision" not in record_columns:
            c.execute("ALTER TABLE records ADD COLUMN routing_revision INTEGER NOT NULL DEFAULT 1")
        if "comment_text" not in record_columns:
            c.execute("ALTER TABLE records ADD COLUMN comment_text TEXT NOT NULL DEFAULT ''")
        file_columns = {row["name"] for row in c.execute("PRAGMA table_info(files)")}
        if "slot" not in file_columns:
            c.execute("ALTER TABLE files ADD COLUMN slot INTEGER NOT NULL DEFAULT 1")
            c.execute("UPDATE files SET slot=2 WHERE UPPER(kind) LIKE '%MOV%2%'")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS reference_sequence(year INTEGER PRIMARY KEY,last INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS memo_reference_sequence(year INTEGER PRIMARY KEY,last INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS app_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        c.execute("""CREATE INDEX IF NOT EXISTS record_reference_index ON records(json_extract(cells, '$."Ref. No."'))""")
        migrate_columns(c)
        c.execute("""CREATE TABLE IF NOT EXISTS imports(
            token TEXT PRIMARY KEY, collections TEXT NOT NULL)""")
        migrate_source_names(c)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS record_sources(record_id TEXT PRIMARY KEY REFERENCES records(id), info TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS document_drafts(token TEXT PRIMARY KEY, owner INTEGER NOT NULL, record_id TEXT NOT NULL REFERENCES records(id));
            CREATE TABLE IF NOT EXISTS purged_drafts(token TEXT PRIMARY KEY, owner INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS administration_log(id INTEGER PRIMARY KEY, at TEXT NOT NULL,
                actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pending_file_deletions(path TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS departments(code TEXT PRIMARY KEY COLLATE NOCASE, name TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS acknowledgements(record_id TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id), routing_revision INTEGER NOT NULL, at TEXT NOT NULL,
                PRIMARY KEY(record_id,user_id,routing_revision));
            CREATE TABLE IF NOT EXISTS department_acknowledgements(record_id TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                department TEXT NOT NULL, routing_revision INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id), at TEXT NOT NULL,
                PRIMARY KEY(record_id,department,routing_revision));
        """)
        # Retain prior acknowledgements when upgrading from per-person shared receipts.
        if not c.execute("SELECT 1 FROM app_metadata WHERE key='shared_acknowledgements_v1'").fetchone():
            c.execute("""INSERT OR IGNORE INTO department_acknowledgements
                SELECT a.record_id,UPPER(u.department),a.routing_revision,a.user_id,a.at
                FROM acknowledgements a JOIN users u ON u.id=a.user_id JOIN records r ON r.id=a.record_id
                WHERE r.assigned_user_id IS NULL ORDER BY a.at""")
            c.execute("INSERT INTO app_metadata VALUES('shared_acknowledgements_v1',?)", (now(),))
        for code,name in DEPARTMENTS.items():
            c.execute("INSERT OR IGNORE INTO departments VALUES(?,?,?)", (code,name,now()))
        for row in c.execute("SELECT DISTINCT department FROM users WHERE deleted_at IS NULL").fetchall():
            code = row["department"].strip().upper()
            if code:
                c.execute("INSERT OR IGNORE INTO departments VALUES(?,?,?)", (code,DEPARTMENTS.get(code,code),now()))
        finish_file_deletions(c)

def administration_event(c, user, action, details):
    actor = user["name"] + " (" + user["username"] + " / " + user["department"] + ")"
    c.execute("INSERT INTO administration_log(at,actor,action,details) VALUES(?,?,?,?)",
              (now(), actor, action, json.dumps(details)))

def finish_file_deletions(c):
    """Only unlink unused blobs after the database transaction has committed.

    A workbook may be shared by several imported worksheets. Failed filesystem
    cleanup stays queued and is retried on startup or the next permanent delete.
    """
    for row in c.execute("SELECT path FROM pending_file_deletions").fetchall():
        relative = row["path"]
        if c.execute("SELECT 1 FROM files WHERE path=? LIMIT 1", (relative,)).fetchone():
            c.execute("DELETE FROM pending_file_deletions WHERE path=?", (relative,))
            continue
        path = (FILES / relative).resolve()
        if not path.is_relative_to(FILES.resolve()):
            raise ValueError("Invalid stored file path.")
        try:
            path.unlink(missing_ok=True)
            if path.suffix == ".pending":
                path.with_suffix(".json").unlink(missing_ok=True)
        except OSError:
            continue
        c.execute("DELETE FROM pending_file_deletions WHERE path=?", (relative,))
    draft_failures = 0
    for entry in c.execute("SELECT token FROM purged_drafts"):
        token = entry["token"]
        if re.fullmatch(r"[0-9a-f]{32}", token):
            try:
                if (DRAFTS / token).exists():
                    shutil.rmtree(DRAFTS / token)
            except OSError:
                draft_failures += 1
    return c.execute("SELECT COUNT(*) FROM pending_file_deletions").fetchone()[0] + draft_failures

def permanently_delete(c, record, user, commit=True):
    """Remove a deleted record and its owned files, preserving shared imports."""
    rid, cid = record["id"], record["collection_id"]
    paths = [row["path"] for row in c.execute("SELECT path FROM files WHERE record_id=?", (rid,))]
    c.execute("INSERT OR IGNORE INTO purged_drafts SELECT token,owner FROM document_drafts WHERE record_id=?", (rid,))
    c.execute("DELETE FROM document_drafts WHERE record_id=?", (rid,))
    c.execute("DELETE FROM files WHERE record_id=?", (rid,))
    c.execute("DELETE FROM events WHERE record_id=?", (rid,))
    c.execute("DELETE FROM record_sources WHERE record_id=?", (rid,))
    c.execute("DELETE FROM records WHERE id=?", (rid,))
    if not c.execute("SELECT 1 FROM records WHERE collection_id=? LIMIT 1", (cid,)).fetchone():
        paths += [row["path"] for row in c.execute("SELECT path FROM files WHERE collection_id=?", (cid,))]
        c.execute("DELETE FROM files WHERE collection_id=?", (cid,))
        c.execute("DELETE FROM collections WHERE id=?", (cid,))
        for entry in c.execute("SELECT token,collections FROM imports").fetchall():
            original = json.loads(entry["collections"])
            if cid in original:
                c.execute("UPDATE imports SET collections=? WHERE token=?",
                          (json.dumps([value for value in original if value != cid]), entry["token"]))
    for relative in set(paths):
        c.execute("INSERT OR IGNORE INTO pending_file_deletions VALUES(?)", (relative,))
    administration_event(c, user, "Document permanently deleted", {"reference":record["cells"].get("Ref. No.", rid)})
    # Do not erase shared blobs unless their database deletion is durable.
    if commit:
        c.commit()
        return finish_file_deletions(c)
    return 0

def recovery_code():
    return "-".join(secrets.token_hex(3).upper() for _ in range(4))

def invalidate_sessions(user_id):
    for token, session in list(SESSIONS.items()):
        if session["user"] == user_id:
            SESSIONS.pop(token, None)

def editable_columns(user, record):
    if role_editor(user):
        return record["columns"]
    if user["role"] != "staff":
        return []
    return [column for column in record["columns"]
            if column in ("Action Taken", "Status", "MOV 1", "MOV 2") or norm(column) == "datesubmitted"]

def norm(s):
    return "".join(x for x in str(s).lower() if x.isalnum())

def automatic_mapping(headers):
    mapped = {}
    for column in headers:
        key = ALIASES.get(norm(column))
        if key and key not in mapped:
            mapped[key] = column
    return mapped

def value_text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)

CORE_COLUMNS = ["Hard Copy Routed", "Ref. No.", "Subject", "Assigned to",
                "Requested Actions", "Action Taken", "MOV 1", "MOV 2", "Status"]
CORE_KEYS = {"hard":"Hard Copy Routed", "reference":"Ref. No.", "subject":"Subject",
             "assigned":"Assigned to", "action":"Requested Actions", "status":"Status"}
ACTION_TAKEN = ["Acknowledged receipt", "Under review", "Coordinated with concerned office",
                "Prepared response", "Submitted required document", "Forwarded for approval",
                "Approved", "Filed", "Completed"]

def canonical_column(label, mappings=None):
    # Numbered copies of known headers map to the same logical field.
    plain = re.sub(r"\s*\(\d+\)\s*$", "", str(label)).strip()
    key = norm(plain)
    for field, source in (mappings or {}).items():
        if source == label and field in CORE_KEYS:
            return CORE_KEYS[field]
    if key.startswith("actiontaken"):
        return "Action Taken"
    if key in ("mov", "movs", "mov1", "movs1", "meansofverification", "meansofverification1"):
        return "MOV 1"
    if key in ("mov2", "movs2", "meansofverification2"):
        return "MOV 2"
    if key in ("actionstaken", "actiondone"):
        return "Action Taken"
    if key in ("deadline", "duedate", "datesubmitted", "datereceived"):
        return {"deadline":"Deadline", "duedate":"Deadline", "datesubmitted":"Date Submitted", "datereceived":"Date Received"}[key]
    return CORE_KEYS.get(ALIASES.get(key), str(label).strip())

def normalize_table(columns, values, mappings=None):
    targets, extras, extra_names = [], [], {}
    for index, label in enumerate(columns):
        target = canonical_column(label, mappings)
        placeholder = re.fullmatch(r"Column(?:\s*\d+)?(?:\s*\(\d+\))?", str(label), re.I)
        if placeholder:
            if not any(index < len(row) and str(row[index] or "").strip() for row in values):
                targets.append(None)
                continue
            populated = [value_text(row[index]).strip() for row in values if index < len(row) and value_text(row[index]).strip()]
            preceding_empty = index > 0 and not any(value_text(row[index-1]).strip() for row in values if index-1 < len(row))
            if preceding_empty and targets and targets[-1] in CORE_COLUMNS:
                target = targets[-1]
            elif populated == [str(i+1) for i in range(len(populated))]:
                target = "Source row no."
            else:
                number = re.search(r"\d+", str(label))
                target = "Imported field " + (number.group() if number else str(index+1))
        if target not in CORE_COLUMNS:
            target = extra_names.setdefault(target.casefold(), target)
            if target not in extras:
                extras.append(target)
        targets.append(target)
    normalized = []
    for row in values:
        cells = dict.fromkeys(CORE_COLUMNS + extras, "")
        for index, target in enumerate(targets):
            if not target or index >= len(row):
                continue
            text = value_text(row[index]).strip()
            if text and text not in cells[target].split("\n"):
                cells[target] = "\n".join(filter(None, [cells[target], text]))
        normalized.append(cells)
    return CORE_COLUMNS + extras, normalized

def next_reference(c):
    year = datetime.now().year
    while True:
        row = c.execute("INSERT INTO memo_reference_sequence(year,last) VALUES(?,1) ON CONFLICT(year) DO UPDATE SET last=last+1 RETURNING last", (year,)).fetchone()
        if row["last"] > 99999:
            raise ValueError("The five-digit memorandum reference sequence is full for this year. Contact the administrator.")
        reference = f"RO1-MEMO-{year}-{row['last']:05d}"
        exists = c.execute("""SELECT 1 FROM records WHERE json_extract(cells, '$."Ref. No."')=? LIMIT 1""", (reference,)).fetchone()
        if not exists:
            return reference

def migrate_columns(c):
    if c.execute("SELECT value FROM app_metadata WHERE key='canonical_columns_v4'").fetchone():
        return
    for collection in c.execute("SELECT * FROM collections").fetchall():
        records = c.execute("SELECT * FROM records WHERE collection_id=? ORDER BY rowid", (collection["id"],)).fetchall()
        columns = json.loads(collection["columns"])
        mappings = json.loads(collection["mappings"])
        old_cells = [json.loads(r["cells"]) for r in records]
        headers, normalized = normalize_table(columns, [[cells.get(h, "") for h in columns] for cells in old_cells], mappings)
        for record, cells in zip(records, normalized):
            if not cells["Ref. No."]:
                cells["Ref. No."] = next_reference(c)
            c.execute("UPDATE records SET cells=?,version=version+1 WHERE id=?", (json.dumps(cells),record["id"]))
        c.execute("UPDATE collections SET columns=?,mappings=? WHERE id=?",
                  (json.dumps(headers),json.dumps(automatic_mapping(headers)),collection["id"]))
    c.execute("INSERT INTO app_metadata VALUES('canonical_columns_v4','1')")

def migrate_source_names(c):
    if c.execute("SELECT 1 FROM app_metadata WHERE key='source_names_v5'").fetchone():
        return
    for collection in c.execute("SELECT id,name FROM collections").fetchall():
        if norm(collection["name"]) not in ("incomingdocument", "incomingdocuments"):
            continue
        source = c.execute("SELECT name FROM files WHERE collection_id=? AND kind='Original import' LIMIT 1", (collection["id"],)).fetchone()
        row = c.execute("SELECT cells FROM records WHERE collection_id=? ORDER BY rowid LIMIT 1", (collection["id"],)).fetchone()
        title = source["name"] if source else (json.loads(row["cells"]).get("Subject") if row else "")
        c.execute("UPDATE collections SET name=? WHERE id=?", ((title or "Registered documents")[:200],collection["id"]))
    c.execute("INSERT INTO app_metadata VALUES('source_names_v5','1')")

def mov_entries(text, files):
    entries = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        urls = re.findall(r"https?://[^\s\]<>]+", line)
        if urls:
            for url in urls:
                entries.append({"name":line.strip() if line.strip() != url else url, "url":url, "type":"link"})
        else:
            entries.append({"name":line.strip(), "url":"", "type":"note"})
    entries.extend({"name":f["name"], "url":"/api/file/" + f["id"], "type":"file"} for f in files)
    return list({(entry["name"],entry["url"]):entry for entry in entries}.values())

def export_value(record, column):
    if column in ("MOV 1", "MOV 2"):
        return "\n".join(entry["name"] + (" ["+entry["url"]+"]" if entry["type"] == "link" and entry["url"] not in entry["name"] else "")
                         for entry in record["movs"][column])
    return record["cells"].get(column, "")

def unique_headers(values):
    result = []
    for index, value in enumerate(values):
        label = value_text(value).strip() or "Column " + str(index + 1)
        candidate, suffix = label, 2
        while candidate in result:
            candidate = label + " (" + str(suffix) + ")"
            suffix += 1
        result.append(candidate)
    return result

def parse_file(filename, raw, header_override=None):
    suffix = Path(filename).suffix.lower()
    datasets, warnings = [], []
    if suffix == ".xlsx":
        import openpyxl
        workbook = openpyxl.load_workbook(io.BytesIO(raw), data_only=False)
        values_book = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
        for sheet in workbook:
            merged_labels = {}
            for area in sheet.merged_cells.ranges:
                if area.min_row == area.max_row:
                    label = sheet.cell(area.min_row, area.min_col).value
                    for column in range(area.min_col, area.max_col+1):
                        merged_labels[(area.min_row,column)] = label
            data = []
            for row in sheet:
                values = []
                for cell in row:
                    value = values_book[sheet.title][cell.coordinate].value if cell.data_type == "f" else cell.value
                    if value is None and (cell.row,cell.column) in merged_labels:
                        value = merged_labels[(cell.row,cell.column)]
                    if value is None and cell.data_type == "f":
                        value = ""
                    if cell.hyperlink and cell.hyperlink.target:
                        value = str(value or "") + " [" + cell.hyperlink.target + "]"
                    values.append(value_text(value))
                data.append(values)
            if any(any(v for v in row) for row in data):
                override = header_override.get(sheet.title) if isinstance(header_override, dict) else header_override
                datasets.append(table_dataset(sheet.title, data, override))
    elif suffix == ".csv":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        datasets.append(table_dataset(filename, list(csv.reader(io.StringIO(text), dialect)), header_override))
    elif suffix == ".pdf":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if tables:
                    for index, table in enumerate(tables, 1):
                        datasets.append(table_dataset(f"Page {page_number} table {index}", table, header_override))
                else:
                    text = page.extract_text() or ""
                    datasets.append({"name": f"Page {page_number}", "columns": ["Page", "Extracted text"],
                                     "rows": [[str(page_number), text or "Scanned page — review the original PDF and encode details manually."]]})
                    if not text:
                        warnings.append(f"Page {page_number} is scanned. Automatic OCR is unavailable in this package.")
        warnings.append("PDF table detection depends on layout. Review the preview and column mapping before importing.")
    elif suffix == ".docx":
        from docx import Document
        document = Document(io.BytesIO(raw))
        for index, table in enumerate(document.tables, 1):
            datasets.append(table_dataset(f"Table {index}", [[c.text for c in row.cells] for row in table.rows], header_override))
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        if paragraphs:
            datasets.append({"name": "Document text", "columns": ["Paragraph", "Extracted text"],
                             "rows": [[str(i + 1), p] for i, p in enumerate(paragraphs)]})
    elif suffix == ".txt":
        datasets.append({"name": filename, "columns": ["Line", "Extracted text"],
                         "rows": [[str(i + 1), t] for i, t in enumerate(raw.decode("utf-8-sig").splitlines()) if t.strip()]})
    else:
        datasets.append({"name": filename, "columns": ["File name", "Subject", "Assigned to", "Status"],
                         "rows": [[filename, Path(filename).stem, "", "For Routing"]]})
        warnings.append("This file is retained as an attachment. Its internal layout is not parsed.")
    for dataset in datasets:
        headers, cells = normalize_table(dataset["columns"], dataset["rows"])
        for index, row in enumerate(cells, 1):
            if not row["Subject"]:
                row["Subject"] = Path(filename).stem + " - " + dataset["name"] + (" " + str(index) if len(cells)>1 else "")
        dataset["columns"] = headers
        dataset["rows"] = [[row.get(h, "") for h in headers] for row in cells]
        dataset["mappings"] = automatic_mapping(headers)
    if not datasets:
        raise ValueError("No readable content found.")
    if sum(len(d["rows"]) for d in datasets) > 10000:
        raise ValueError("Import up to 10,000 rows at a time.")
    return {"datasets": datasets, "warnings": warnings}

def table_dataset(name, data, override):
    if not data:
        return {"name": name, "columns": ["Column 1"], "rows": []}
    width = max(len(row) for row in data)
    data = [[value_text(x) for x in row] + [""] * (width - len(row)) for row in data]
    occupied = [i for i in range(width) if any(row[i] for row in data)]
    if not occupied:
        return {"name": name, "columns": ["Column 1"], "rows": []}
    first, last = occupied[0], occupied[-1] + 1
    if override is not None:
        header = int(override) - 1
        if header < 0 or header >= len(data):
            raise ValueError("Header row is outside the file.")
    else:
        scores = [sum(norm(v) in ALIASES or "actiontaken" in norm(v) or norm(v).startswith("mov") for v in row) for row in data[:60]]
        header = max(range(len(scores)), key=scores.__getitem__) if max(scores, default=0) >= 2 else next((i for i, r in enumerate(data) if any(r)), 0)
    columns = unique_headers(data[header][first:last])
    return {"name": name, "columns": columns, "header_row": header + 1,
            "rows": [row[first:last] for row in data[header + 1:] if any(row[first:last])]}

def event(c, rid, user, message, route=None):
    c.execute("INSERT INTO events(record_id,at,actor,message,route) VALUES(?,?,?,?,?)",
              (rid, now(), user["name"] + " (" + user["username"] + " / " + user["department"] + ")", message, json.dumps(route) if route else None))

def multipart_form(content_type, raw):
    """Parse form headers without interpreting a file's internal MIME structure.

    BytesParser on the complete form recursively parses message/rfc822 uploads
    and returns no decoded byte payload. Split only the actual form boundaries
    so email originals and binary documents are stored byte for byte.
    """
    envelope=BytesParser(policy=default).parsebytes(("Content-Type: "+content_type+"\r\n\r\n").encode(),headersonly=True)
    boundary=envelope.get_boundary()
    if not boundary or len(boundary)>200:
        raise ValueError("Invalid upload form.")
    markers=list(re.finditer(rb"(?:\A|\r\n)--"+re.escape(boundary.encode('ascii'))+rb"(--)?(?:\r\n|\Z)",raw))
    if len(markers)<2 or not markers[-1].group(1):
        raise ValueError("The upload is incomplete. Choose the file again.")
    body={}
    for start,end in zip(markers,markers[1:]):
        part=raw[start.end():end.start()]
        headers,separator,payload=part.partition(b"\r\n\r\n")
        if not separator:
            raise ValueError("Invalid upload part.")
        message=BytesParser(policy=default).parsebytes(headers+b"\r\n\r\n",headersonly=True)
        name=message.get_param("name",header="content-disposition")
        if not name:
            continue
        filename=message.get_filename()
        if filename is not None:
            from intake import safe_name
            body[name]={"name":safe_name(filename),"data":payload}
        else:
            charset=message.get_content_charset() or 'utf-8'
            try:
                body[name]=payload.decode(charset,errors='replace')
            except LookupError:
                body[name]=payload.decode('utf-8',errors='replace')
    return body

def clean_drafts():
    for folder in DRAFTS.iterdir():
        if folder.is_dir() and re.fullmatch(r"[0-9a-f]{32}", folder.name) and time.time()-folder.stat().st_mtime>86400:
            shutil.rmtree(folder, ignore_errors=True)

def read_draft(token, user):
    if not isinstance(token,str) or not re.fullmatch(r"[0-9a-f]{32}",token):
        raise ValueError("Choose a valid source file.")
    folder=DRAFTS/token
    if not (folder/"metadata.json").is_file() or time.time()-folder.stat().st_mtime>86400:
        raise ValueError("This source preview has expired. Import the file again.")
    metadata=json.loads((folder/"metadata.json").read_text(encoding="utf-8"))
    if metadata["owner"]!=user["id"]:
        raise PermissionError("This source file belongs to another account.")
    return folder,metadata

def source_summary(info):
    return {key:info.get(key,"") for key in ("filename","type","sender","sent","sheet","row","attachment_count")}

def get_record(c, rid):
    row = c.execute("SELECT r.*,c.columns,c.mappings,c.name collection_name FROM records r JOIN collections c ON c.id=r.collection_id WHERE r.id=?", (rid,)).fetchone()
    if not row:
        raise ValueError("Record not found.")
    result = dict(row)
    for key in ["cells", "columns", "mappings"]:
        result[key] = json.loads(result[key])
    record_files = [dict(f) for f in c.execute("SELECT id,name,kind,slot FROM files WHERE record_id=?", (rid,))]
    result["movs"] = {column:mov_entries(result["cells"].get(column, ""),
                        [f for f in record_files if f["kind"].upper().startswith("MOV") and f["slot"] == slot])
                      for slot,column in [(1,"MOV 1"),(2,"MOV 2")]}
    source=c.execute("SELECT info FROM record_sources WHERE record_id=?",(rid,)).fetchone()
    result["source"] = source_summary(json.loads(source["info"])) if source else None
    result["departments"] = assigned_departments(result["cells"].get(result["mappings"].get("assigned"), ""), department_catalog(c))
    staff = c.execute("SELECT id,name,username,department,active,archived_at FROM users WHERE id=?",
                      (result["assigned_user_id"],)).fetchone()
    result["assigned_staff"] = dict(staff) if staff else None
    result["year"] = record_year(result)
    return result

def record_year(record):
    """Use the register-reference year, then routed date, then registration year."""
    cells, mapping = record["cells"], record["mappings"]
    reference = cells.get(mapping.get("reference"), "")
    match = re.search(r"\bRO1-(?:MEMO-)?((?:19|20|21)\d{2})-", reference, re.I)
    if match:
        return match[1]
    for value in (cells.get(mapping.get("hard"), ""), record["created"]):
        match = re.search(r"\b((?:19|20|21)\d{2})\b", value)
        if match:
            return match[1]
    return ""

def department_catalog(c):
    return {row["code"]:row["name"] for row in c.execute("SELECT code,name FROM departments ORDER BY created,code")}

def require_department(c, code):
    code = str(code).strip().upper()
    if code not in department_catalog(c):
        raise ValueError("Choose a registered department. Add new departments in Account management first.")
    return code

def receipt_state(c, user, record):
    if record["assigned_user_id"] is None and user["department"].upper() in record["departments"]:
        ack = c.execute("""SELECT a.at,u.name FROM department_acknowledgements a JOIN users u ON u.id=a.user_id
            WHERE a.record_id=? AND a.department=? AND a.routing_revision=?""",
            (record["id"],user["department"].upper(),record["routing_revision"])).fetchone()
    else:
        ack = c.execute("""SELECT a.at,u.name FROM acknowledgements a JOIN users u ON u.id=a.user_id
            WHERE a.record_id=? AND a.user_id=? AND a.routing_revision=?""",
            (record["id"],user["id"],record["routing_revision"])).fetchone()
    record["acknowledged_at"] = ack["at"] if ack else None
    record["acknowledged_by"] = ack["name"] if ack else None
    record["is_new"] = user["role"] == "staff" and not record["deleted_at"] and not ack
    return record

def assigned_departments(value, catalog):
    result = []
    for code, name in catalog.items():
        aliases = [code, name] + (["OPERATIONS"] if code == "OPS" else [])
        if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", str(value), re.I) for alias in aliases):
            result.append(code)
    return result

def assignment_staff(c, body, departments, previous=None):
    """Validate staff membership on the host, including requests made outside the UI."""
    value = body.get("assigned_user_id", previous)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError("Choose a valid staff account.")
    staff = c.execute("SELECT * FROM users WHERE id=?", (int(value),)).fetchone()
    # Retain an existing historical assignment, even if the account was retired.
    if previous == int(value) and staff and staff["department"].upper() in departments:
        return int(value)
    if not staff or not staff["active"] or staff["archived_at"] or staff["deleted_at"] or staff["account_type"] != "individual" or staff["role"] == "viewer":
        raise ValueError("Choose an active staff account.")
    if len(departments) != 1 or staff["department"].upper() != departments[0]:
        raise ValueError("The selected staff member must belong to the selected department.")
    return int(value)

def canonical_status(value):
    value = str(value).strip()
    choices = {"forrouting":"For routing", "routed":"For routing", "received":"Received",
               "pending":"Pending", "ongoing":"Ongoing", "completed":"Completed",
               "forcomment":"For Comment", "forsignature":"For Signature"}
    return choices.get(norm(value), value or "For routing")

def batch_records(c, user, items, deleted):
    if not isinstance(items, list) or not 1 <= len(items) <= 10000:
        raise ValueError("Select between 1 and 10,000 documents.")
    records, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
            raise ValueError("The selection contains invalid or duplicate documents.")
        record = get_record(c, item["id"])
        if bool(record["deleted_at"]) != deleted or item.get("version") != record["version"]:
            raise ValueError("A selected document changed. Refresh and select again. No documents were changed.")
        if not department_access(user, record):
            raise PermissionError("One of the selected documents is outside your access.")
        records.append(record)
        seen.add(record["id"])
    return records

def collection_revision(c, cid):
    versions = [(row["id"], row["version"], row["deleted_at"]) for row in c.execute(
        "SELECT id,version,deleted_at FROM records WHERE collection_id=? ORDER BY id", (cid,))]
    return hashlib.sha256(json.dumps(versions).encode()).hexdigest()

def may_edit(user):
    return user["role"] in ("admin", "records", "staff")

def role_editor(user):
    return user["role"] in ("admin", "records")

def can_oversee(user):
    return role_editor(user) or user["department"].upper() == "ORD"

def department_access(user, record):
    if can_oversee(user):
        return True
    if record["assigned_user_id"] is not None:
        return record["assigned_user_id"] == user["id"]
    return user["department"].upper() in record["departments"]

PRINT_LOCK = threading.Lock()

def filled_docx(record, events):
    """Fill the official template; center rows and paginate without shrinking text."""
    from routing import combined_sheet, printed_date
    cells,mapping=record["cells"],record["mappings"]
    routes=[json.loads(entry["route"]) for entry in events if entry["route"]]
    if not routes:
        routes=[{"from":"ORD","to":cells.get(mapping.get("assigned"),""),
                 "date":cells.get(mapping.get("hard"),""),"time":""}]
    routes=[{**route,"date":printed_date(route.get("date","")),"note":route.get("action_taken","")} for route in routes]
    routes[-1]["note"]=cells.get("Action Taken","")
    return combined_sheet(ROOT/"templates/routing-slip.docx",routes,cells.get("Subject",""),cells.get("Ref. No.",""))

def original_body_tables(children, namespaces):
    return [child for child in children if child.tag == "{"+namespaces["w"]+"}tbl"]

def office_converter():
    for filename in ("soffice.com", "soffice.exe"):
        private = ROOT / "libreoffice/program" / filename
        if private.is_file():
            return str(private)
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable:
        return executable
    if os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            for filename in ("soffice.com", "soffice.exe"):
                candidate = Path(os.environ.get(env, "")) / "LibreOffice/program" / filename
                if candidate.is_file():
                    return str(candidate)
    return None

def render_slip_pdf(docx_bytes):
    """Export through the bundled renderer, or the developer's office renderer."""
    key = ("pdf", hashlib.sha256(docx_bytes).digest())
    cached = RENDER_CACHE.get(key)
    if cached is not None:
        return cached
    converter = office_converter()
    with PRINT_LOCK, tempfile.TemporaryDirectory(prefix="ncsc-print-") as folder:
        cached = RENDER_CACHE.get(key)
        if cached is not None:
            return cached
        directory = Path(folder)
        source = directory / "Routing-Slip.docx"
        destination = directory / "Routing-Slip.pdf"
        source.write_bytes(docx_bytes)
        if converter:
            profile = (directory / "office-profile").as_uri()
            command = [converter, "-env:UserInstallation="+profile, "--headless", "--convert-to", "pdf",
                       "--outdir", str(directory), str(source)]
        elif os.name == "nt":
            # Word is used only on the local host through its installed COM server.
            script = ROOT / "print-with-word.ps1"
            command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                       "-File", str(script), "-Source", str(source), "-Destination", str(destination)]
        else:
            raise ValueError("Install LibreOffice on the host for PDF print preview, or download the filled Word template and print it in Word.")
        try:
            result = subprocess.run(command, capture_output=True, timeout=90, check=False,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            raise ValueError("The office application took too long. Download the Word template to print it.")
        if result.returncode or not destination.is_file():
            raise ValueError("Print preview needs Microsoft Word or LibreOffice on the host. You can download and print the exact filled Word template.")
        return RENDER_CACHE.put(key, destination.read_bytes())

def selected_records(c, user, ids, limit=100):
    if not isinstance(ids, list) or not ids or len(ids) > limit:
        raise ValueError(f"Select between 1 and {limit} documents.")
    records = []
    for rid in dict.fromkeys(str(value) for value in ids):
        record = get_record(c, rid)
        if not department_access(user, record):
            raise PermissionError("One of the selected documents is outside your department access.")
        if record["deleted_at"]:
            raise ValueError("Restore deleted documents before printing or exporting them.")
        records.append(record)
    return records

def filled_slips(c, records):
    """Combine filled copies of the original template without rebuilding the form."""
    from lxml import etree
    ns = {"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    documents = []
    for record in records:
        events = c.execute("SELECT * FROM events WHERE record_id=? ORDER BY id", (record["id"],)).fetchall()
        documents.append(filled_docx(record, events))
    if len(documents) == 1:
        return documents[0]
    with ZipFile(io.BytesIO(documents[0])) as source:
        root = etree.fromstring(source.read("word/document.xml"))
        body = root.find("w:body", ns)
        section = body.find("w:sectPr", ns)
        for raw in documents[1:]:
            with ZipFile(io.BytesIO(raw)) as part:
                incoming = etree.fromstring(part.read("word/document.xml")).find("w:body", ns)
                paragraph = etree.Element("{"+ns["w"]+"}p")
                run = etree.SubElement(paragraph, "{"+ns["w"]+"}r")
                etree.SubElement(run, "{"+ns["w"]+"}br").set("{"+ns["w"]+"}type", "page")
                body.insert(body.index(section), paragraph)
                for child in incoming:
                    if child.tag != "{"+ns["w"]+"}sectPr":
                        body.insert(body.index(section), copy.deepcopy(child))
        output = io.BytesIO()
        with ZipFile(output, "w") as destination:
            for info in source.infolist():
                destination.writestr(info, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                                    if info.filename == "word/document.xml" else source.read(info.filename))
        return output.getvalue()

def shared_slip_draft(c, records):
    rows = []
    for record in records:
        entry = c.execute("SELECT route FROM events WHERE record_id=? AND route IS NOT NULL ORDER BY id DESC LIMIT 1", (record["id"],)).fetchone()
        route = json.loads(entry["route"]) if entry else {}
        cells = record["cells"]
        note = cells.get("Action Taken", "")
        rows.append({"id":record["id"],"version":record["version"],"reference":cells.get("Ref. No.",""),
                     "subject":cells.get("Subject",""),"from":route.get("from","ORD"),"to":cells.get("Assigned to",""),
                     "date":cells.get("Hard Copy Routed") or route.get("date",""),"time":route.get("time",""),
                     "note":note,"sign":"","received":""})
    return {"subject":"SELECTED DOCUMENTS","rows":rows}

def combined_document_rows(c, records, overrides=None):
    from routing import combined_sheet, printed_date
    draft = shared_slip_draft(c,records)
    if overrides is not None:
        if len(records) < 2 or not isinstance(overrides,dict):
            raise ValueError("Print-only edits are available for multiple documents on a shared slip.")
        title = overrides.get("subject")
        if not isinstance(title,str) or not title.strip() or len(title)>200:
            raise ValueError("Enter a shared slip subject of up to 200 characters.")
        edits = overrides.get("rows")
        if not isinstance(edits,list) or len(edits)!=len(records):
            raise ValueError("Reopen the shared slip editor and review every selected document.")
        by_id = {row.get("id"):row for row in edits if isinstance(row,dict) and isinstance(row.get("id"),str)}
        if len(by_id)!=len(records) or set(by_id)!={r["id"] for r in records}:
            raise ValueError("The shared slip selection does not match the requested documents.")
        limits = {"subject":500,"from":120,"to":200,"date":80,"time":80,"note":3000,"sign":120,"received":200}
        for row in draft["rows"]:
            edit = by_id[row["id"]]
            if edit.get("version") != row["version"]:
                raise ValueError("A saved document changed. Reopen the printing page to refresh the shared slip.")
            if set(edit)-set(limits)-{"id","version"}:
                raise ValueError("Only the shared slip text fields can be edited. References stay unchanged.")
            for key,limit in limits.items():
                if key in edit:
                    if not isinstance(edit[key],str) or len(edit[key])>limit:
                        raise ValueError("The slip field "+key+" exceeds its allowed text length.")
                    row[key]=edit[key]
            if not row["subject"].strip():
                raise ValueError("Each document needs a printable subject.")
        draft["subject"]=title.strip()
    rows=[]
    for index,row in enumerate(draft["rows"],1):
        rows.append({**row,"from":str(index).zfill(2)+"\n"+row["from"],"date":printed_date(row["date"]),
                     "note":"\n".join(filter(None,[row["reference"],row["subject"],row["note"]]))})
    return combined_sheet(ROOT/"templates/routing-slip.docx",rows,draft["subject"])

def batch_document(c, records, mode, overrides=None):
    if mode == "combined":
        return combined_document_rows(c, records, overrides)
    if mode == "individual" and overrides is None:
        return filled_slips(c, records)
    raise ValueError("Choose combined rows or individual routing slips. Individual slips use saved details.")

def export_package(records, format, paper="compact"):
    if paper not in ("compact", "a4"):
        raise ValueError("Choose compact pages or A4 landscape.")
    from reports import make_export
    names = list(dict.fromkeys(r["collection_name"] for r in records))
    title = names[0] if len(names) == 1 else "Selected documents from " + str(len(names)) + " worksheets"
    content, mime = make_export(records, title, format, ROOT, render_slip_pdf, paper)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", title).strip(" .")[:110] or "Tracking-Matrix"
    return content, mime, "NCSC-"+name+"."+format

def authorized_file(c, user, fid):
    file = c.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not file:
        raise ValueError("File not found.")
    if not can_oversee(user):
        if file["collection_id"] or file["kind"] == "Original import":
            raise PermissionError("Original workbooks are available to records staff. Use the files attached to your document.")
        if not file["record_id"] or not department_access(user, get_record(c, file["record_id"])):
            raise PermissionError("Access denied.")
    return file

def preview_file(file):
    raw = (FILES/file["path"]).read_bytes()
    extension = Path(file["name"]).suffix.lower()
    if extension in (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return raw, mimetypes.guess_type(file["name"])[0]
    if extension == ".docx":
        return render_slip_pdf(raw), "application/pdf"
    key = ("preview", extension, file["name"], hashlib.sha256(raw).digest())
    cached = RENDER_CACHE.get(key)
    if cached is not None:
        return cached, "text/html; charset=utf-8"
    title = html.escape(file["name"])
    styles = "body{font:14px Arial,sans-serif;margin:24px;color:#24314d}h1{font-size:18px;color:#152467}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d9dfed;padding:9px;vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere}th{background:#152467;color:white}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
    if extension in (".eml", ".msg"):
        from intake import read_eml, read_msg
        info,attachments=(read_eml if extension == ".eml" else read_msg)(raw)
        body="<table>"+"".join("<tr><th>"+label+"</th><td>"+html.escape(info.get(key,""))+"</td></tr>" for key,label in
            [("subject","Subject"),("sender","From"),("to","To"),("sent","Sent")])+"</table><pre>"+html.escape(info.get("body",""))+"</pre>"
        if attachments:
            body+="<h2>Attachments</h2><ul>"+"".join("<li>"+html.escape(a["name"])+"</li>" for a in attachments)+"</ul>"
    elif extension in (".txt", ".csv", ".log"):
        body = "<pre>"+html.escape(raw.decode("utf-8-sig", errors="replace"))+"</pre>"
    elif extension == ".xlsx":
        import openpyxl
        workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        body = "<p>Preview shows up to 200 rows and 30 columns per worksheet. Download the file for its complete original formatting.</p>"
        for sheet in workbook:
            body += "<h2>"+html.escape(sheet.title)+"</h2><table>"
            for row in sheet.iter_rows(max_row=min(sheet.max_row or 0,200), max_col=min(sheet.max_column or 0,30), values_only=True):
                body += "<tr>"+"".join("<td>"+html.escape(value_text(value))+"</td>" for value in row)+"</tr>"
            body += "</table>"
        workbook.close()
    else:
        raise ValueError("This file type can be downloaded and opened in its desktop application. Inline preview is available for PDF, images, Word, Excel and text files.")
    content = ("<!doctype html><html><head><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\"><style>"+styles+"</style></head><body><h1>"+title+"</h1>"+body+"</body></html>").encode()
    return RENDER_CACHE.put(key, content), "text/html; charset=utf-8"

class Handler(BaseHTTPRequestHandler):
    server_version = "NCSC-RO1"
    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args)

    @contextmanager
    def write_transaction(self):
        # A client may immediately refresh after a successful write. Send its
        # response only after SQLite commits, so it cannot read the old state.
        response = None
        with LOCK:
            self._defer_response = True
            self._transaction_response = None
            try:
                with connect() as c:
                    yield c
                response = self._transaction_response
            finally:
                self._defer_response = False
                self._transaction_response = None
        if response:
            self.respond(*response)

    def respond(self, code, data, content_type="application/json", filename=None, cookie=None, inline=False):
        if getattr(self, "_defer_response", False):
            self._transaction_response = (code, data, content_type, filename, cookie, inline)
            return
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if inline else "DENY")
        self.send_header("Cache-Control", "no-store")
        if filename:
            safe = urllib.parse.quote(filename)
            self.send_header("Content-Disposition", ("inline" if inline else "attachment")+"; filename*=UTF-8''" + safe)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def session(self):
        jar = cookies.SimpleCookie()
        jar.load(self.headers.get("Cookie", ""))
        token = jar.get("ncsc_session")
        session = SESSIONS.get(token.value if token else "")
        if not session or session["expires"] < time.time():
            return None
        session["expires"] = time.time() + 8 * 3600
        with connect() as c:
            user = c.execute("SELECT id,username,name,role,department,account_type FROM users WHERE id=? AND active=1 AND archived_at IS NULL AND deleted_at IS NULL", (session["user"],)).fetchone()
        return (dict(user), session) if user else None

    def do_GET(self):
        try:
            self.get()
        except PermissionError as exc:
            self.respond(403, {"error":str(exc)})
        except (ValueError, KeyError) as exc:
            self.respond(400, {"error": str(exc)})
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500, {"error": "The request failed. Check the server console."})

    def get(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path in ("/", "/assets/style.css", "/assets/workspace.css", "/assets/ui.js", "/assets/login.css", "/assets/app.js", "/assets/logo.jpg", "/assets/ncsc-banner.jpg", "/assets/login-photo.jpg", "/assets/login-seniors.png", "/assets/login-background.jpg", "/assets/ncsc-official-logo.jpg", "/assets/login-waves.svg", "/assets/login-geometric.png", "/assets/printing.js", "/assets/matrix-letterhead.png", "/assets/matrix-print.js"):
            file = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
            self.respond(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            return
        auth = self.session()
        if path == "/api/health":
            from version import APP_VERSION, PRODUCT
            with connect() as c:
                configured = bool(c.execute("SELECT 1 FROM users LIMIT 1").fetchone())
            self.respond(200, {"product":PRODUCT, "version":APP_VERSION, "configured":configured})
            return
        if path == "/api/me":
            with connect() as c:
                setup = c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            self.respond(200, {"user": auth[0] if auth else None, "csrf": auth[1]["csrf"] if auth else None, "setup": setup})
            return
        if not auth:
            self.respond(401, {"error": "Please log in."})
            return
        user, session = auth
        if path == "/printing":
            self.respond(200, (ROOT/"printing.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path.startswith("/api/print-page/"):
            from print_jobs import page
            match=re.fullmatch(r"/api/print-page/([0-9a-f]{48})/(\d+)\.png",path)
            if not match:
                raise ValueError("Print page not found.")
            with connect() as c:
                def authorize(ids):
                    try:
                        records=[get_record(c,rid) for rid in ids]
                        return all(not r["deleted_at"] and department_access(user,r) for r in records)
                    except ValueError:
                        return False
                content=page(match[1],int(match[2]),user["id"],authorize)
            self.respond(200,content,"image/png")
            return
        if path.startswith("/api/draft-file/"):
            if not role_editor(user):
                raise PermissionError("Records access required.")
            folder,metadata=read_draft(path.split("/")[-1],user)
            index=int(query.get("attachment",["-1"])[0])
            entry={"path":"original","name":metadata["info"]["filename"]} if index == -1 else (
                metadata["attachments"][index] if 0 <= index < len(metadata["attachments"]) else None)
            if not entry:
                raise ValueError("Source attachment not found.")
            self.respond(200,(folder/entry["path"]).read_bytes(),"application/octet-stream",entry["name"])
            return
        with connect() as c:
            if path == "/api/collections":
                collections = []
                for row in c.execute("SELECT * FROM collections ORDER BY created DESC"):
                    item = dict(row)
                    item["columns"] = json.loads(item["columns"])
                    item["mappings"] = json.loads(item["mappings"])
                    visible = [r for r in (get_record(c,entry["id"]) for entry in c.execute("SELECT id FROM records WHERE collection_id=? AND deleted_at IS NULL", (item["id"],))) if department_access(user,r)]
                    item["count"] = len(visible)
                    if role_editor(user):
                        item["revision"] = collection_revision(c, item["id"])
                    if can_oversee(user) or visible:
                        collections.append(item)
                self.respond(200, collections)
            elif path == "/api/register":
                deleted = query.get("deleted", ["0"])[0] == "1"
                if deleted and not role_editor(user):
                    self.respond(403, {"error": "ORD access required."})
                    return
                clause = "IS NOT NULL" if deleted else "IS NULL"
                records = [get_record(c, row["id"]) for row in c.execute(
                    "SELECT id FROM records WHERE deleted_at " + clause + " ORDER BY rowid DESC")]
                self.respond(200, [receipt_state(c,user,r) for r in records if department_access(user, r)])
            elif path == "/api/records":
                cid = query.get("collection", [""])[0]
                records = [get_record(c, row["id"]) for row in c.execute("SELECT id FROM records WHERE collection_id=? AND deleted_at IS NULL ORDER BY rowid", (cid,))]
                self.respond(200, [receipt_state(c,user,r) for r in records if department_access(user, r)])
            elif path.startswith("/api/record/"):
                r = get_record(c, path.split("/")[-1])
                if not department_access(user, r):
                    self.respond(403, {"error": "This record belongs to another department."})
                    return
                source=c.execute("SELECT info FROM record_sources WHERE record_id=?",(r["id"],)).fetchone()
                r["source"]=json.loads(source["info"]) if source else None
                r["editable_columns"] = editable_columns(user, r)
                r["files"] = [dict(x) for x in c.execute("SELECT id,name,kind,slot FROM files WHERE record_id=? OR collection_id=?", (r["id"], r["collection_id"]))]
                r["events"] = [dict(x) for x in c.execute("SELECT * FROM events WHERE record_id=? ORDER BY id", (r["id"],))]
                if not can_oversee(user):
                    r["files"] = [f for f in r["files"] if f["kind"] != "Original import"]
                self.respond(200, receipt_state(c,user,r))
            elif path.startswith("/api/file-preview/"):
                file = authorized_file(c, user, path.split("/")[-1])
                content, mime = preview_file(file)
                self.respond(200, content, mime, inline=True)
            elif path.startswith("/api/file/"):
                file = authorized_file(c, user, path.split("/")[-1])
                self.respond(200, (FILES/file["path"]).read_bytes(), "application/octet-stream", file["name"])
            elif path.startswith("/api/docx/"):
                r = get_record(c, path.split("/")[-1])
                if not department_access(user, r):
                    self.respond(403, {"error": "Access denied."})
                    return
                events = list(c.execute("SELECT * FROM events WHERE record_id=? ORDER BY id", (r["id"],)))
                self.respond(200, filled_docx(r, events), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Routing-Slip.docx")
            elif path.startswith("/api/print/"):
                r = get_record(c, path.split("/")[-1])
                if not department_access(user, r):
                    self.respond(403, {"error":"Access denied."})
                    return
                events = list(c.execute("SELECT * FROM events WHERE record_id=? ORDER BY id", (r["id"],)))
                self.respond(200, render_slip_pdf(filled_docx(r, events)), "application/pdf")
            elif path == "/api/print-status":
                self.respond(200, {"available":bool(office_converter()) or os.name == "nt"})
            elif path == "/api/directory":
                self.respond(200, [dict(r) for r in c.execute(
                    "SELECT id,name,username,department FROM users WHERE active=1 AND archived_at IS NULL AND account_type='individual' AND role!='viewer' ORDER BY department,name")])
            elif path == "/api/departments":
                catalog = department_catalog(c)
                self.respond(200, [{"code":code,"name":name} for code,name in catalog.items()
                                  if can_oversee(user) or code == user["department"].upper()])
            elif path == "/api/users":
                if user["role"] != "admin":
                    self.respond(403, {"error": "Administrator access required."})
                    return
                self.respond(200, [dict(r) for r in c.execute("SELECT id,username,name,role,department,active,account_type,archived_at FROM users WHERE deleted_at IS NULL ORDER BY name")])
            elif path == "/api/print-batch":
                records = selected_records(c, user, query.get("ids", [""])[0].split(","))
                content = render_slip_pdf(batch_document(c, records, query.get("mode", ["combined"])[0]))
                self.respond(200, content, "application/pdf", "NCSC-Routing-Slips.pdf", inline=True)
            elif path == "/api/export":
                cid = query.get("collection", [""])[0]
                ids = [row["id"] for row in c.execute("SELECT id FROM records WHERE collection_id=? AND deleted_at IS NULL ORDER BY rowid", (cid,))]
                records = [get_record(c, rid) for rid in ids]
                records = [r for r in records if department_access(user, r)]
                if not records:
                    raise ValueError("No accessible documents to export.")
                content, mime, name = export_package(records, query.get("format", ["xlsx"])[0], query.get("paper", ["compact"])[0])
                self.respond(200, content, mime, name)
            else:
                self.respond(404, {"error": "Not found."})

    def do_POST(self):
        try:
            self.post()
        except PermissionError as exc:
            self.respond(403, {"error":str(exc)})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except sqlite3.IntegrityError:
            self.respond(400, {"error": "That username is already in use."})
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500, {"error": "The operation failed. Check the server console."})

    def post(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 25 * 1024 * 1024:
            self.respond(413, {"error": "Upload up to 25 MB at a time."})
            return
        raw = self.rfile.read(length)
        path = urllib.parse.urlparse(self.path).path
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            body = multipart_form(content_type,raw)
        elif content_type.startswith("application/x-www-form-urlencoded") and path == "/matrix-print":
            body = {key: values[0] for key, values in urllib.parse.parse_qs(raw.decode("utf-8")).items()}
        else:
            body = json.loads(raw or b"{}")
        if path == "/api/recover":
            with self.write_transaction() as c:
                username = str(body.get("username", "")).strip()
                user = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE AND deleted_at IS NULL", (username,)).fetchone()
                code = str(body.get("code", "")).strip().upper()
                if not user or not user["active"] or not user["recovery"] or not password_ok(code, user["recovery"]):
                    self.respond(400, {"error": "The username or recovery code is incorrect."})
                    return
                if len(body.get("password", "")) < 8:
                    raise ValueError("Use at least 8 characters for the new password.")
                new_code = recovery_code()
                c.execute("UPDATE users SET password=?, recovery=? WHERE id=?",
                          (password_hash(body["password"]), password_hash(new_code), user["id"]))
                invalidate_sessions(user["id"])
            self.respond(200, {"ok": True, "recovery_code": new_code})
            return
        if path in ("/api/setup", "/api/login"):
            with self.write_transaction() as c:
                if path == "/api/setup":
                    if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                        raise PermissionError("Create the first administrator on the host PC using http://127.0.0.1:" + str(self.server.server_port) + ". Staff can connect after setup.")
                    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                        self.respond(403, {"error": "Setup is already complete."})
                        return
                    if len(body.get("password", "")) < 8:
                        raise ValueError("Use at least 8 characters for the password.")
                    username = str(body.get("username", "")).strip()
                    name = str(body.get("name", "")).strip()
                    if not username or not name:
                        raise ValueError("Enter your full name and personal username.")
                    code = recovery_code()
                    codes = {username:code}
                    c.execute("INSERT INTO users(username,password,name,role,department,recovery,account_type) VALUES(?,?,?,?,?,?,?)",
                              (username, password_hash(body["password"]), name, "admin", "ORD", password_hash(code), "individual"))
                username = str(body.get("username", "")).strip()
                attempt_key = (self.client_address[0], username.casefold())
                failures = [at for at in LOGIN_ATTEMPTS.get(attempt_key, []) if time.time() - at < 60]
                if len(failures) >= 8:
                    self.respond(429, {"error": "Too many attempts. Please wait one minute before trying again."})
                    return
                user = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE AND deleted_at IS NULL", (username,)).fetchone()
                if not user or not user["active"] or not password_ok(body.get("password", ""), user["password"]):
                    LOGIN_ATTEMPTS[attempt_key] = failures + [time.time()]
                    self.respond(401, {"error": "The username or password is incorrect."})
                    return
                LOGIN_ATTEMPTS.pop(attempt_key, None)
                token = secrets.token_urlsafe(32)
                SESSIONS[token] = {"user": user["id"], "csrf": secrets.token_urlsafe(24), "expires": time.time() + 8 * 3600}
            self.respond(200, {"ok": True, "recovery_codes": codes if path == "/api/setup" else None}, cookie="ncsc_session=" + token + "; HttpOnly; SameSite=Strict; Path=/")
            return
        auth = self.session()
        if not auth:
            self.respond(401, {"error": "Please log in."})
            return
        user, session = auth
        supplied_csrf = body.get("csrf", "") if path == "/matrix-print" else self.headers.get("X-CSRF-Token", "")
        if not isinstance(supplied_csrf, str) or not hmac.compare_digest(supplied_csrf, session["csrf"]):
            self.respond(403, {"error": "Session verification failed. Refresh and retry."})
            return
        if path == "/matrix-print":
            from matrix_print import matrix_html
            with connect() as c:
                records = selected_records(c, user, json.loads(body.get("ids", "[]")), 10000)
                content = matrix_html(records, json.loads(body.get("columns", "null")))
            self.respond(200, content, "text/html; charset=utf-8")
            return
        if path == "/api/logout":
            with LOCK:
                for token, s in list(SESSIONS.items()):
                    if s is session:
                        SESSIONS.pop(token, None)
            self.respond(200, {"ok": True}, cookie="ncsc_session=; Max-Age=0; Path=/")
            return
        if path == "/api/preview":
            if not role_editor(user):
                self.respond(403, {"error": "Records access required."})
                return
            file = body["file"]
            header = body.get("header") or None
            if header and str(header).startswith("{"):
                header = json.loads(header)
            result = parse_file(file["name"], file["data"], header)
            temp_id = uuid.uuid4().hex
            (FILES / (temp_id + ".pending")).write_bytes(file["data"])
            (FILES / (temp_id + ".json")).write_text(json.dumps({"name": file["name"], "owner": user["id"], "result": result}), encoding="utf-8")
            self.respond(200, {**result, "token": temp_id})
            return
        if path == "/api/document-draft":
            if not role_editor(user):
                raise PermissionError("Records access required.")
            from intake import intake
            file=body.get("file")
            if not isinstance(file,dict) or not file.get("data"):
                raise ValueError("Choose an email or document file.")
            result=intake(file["name"],file["data"],parse_file,canonical_column)
            with LOCK:
                clean_drafts()
                token=uuid.uuid4().hex
                folder=DRAFTS/token
                folder.mkdir()
                (folder/"original").write_bytes(file["data"])
                attachments=[]
                for index,attachment in enumerate(result["attachments"]):
                    path=str(index)+".attachment"
                    (folder/path).write_bytes(attachment["data"])
                    attachments.append({"path":path,"name":attachment["name"],"size":len(attachment["data"])})
                metadata={"owner":user["id"],"info":result["info"],"candidates":result["candidates"],"attachments":attachments}
                (folder/"metadata.json").write_text(json.dumps(metadata),encoding="utf-8")
            self.respond(200,{"token":token,"info":result["info"],"candidates":result["candidates"],"warnings":result["warnings"]})
            return
        if path in ("/api/export", "/api/print-batch", "/api/print-job", "/api/slip-draft"):
            with connect() as c:
                records = selected_records(c, user, body.get("ids"), 10000 if path == "/api/export" else 100)
                if path == "/api/slip-draft":
                    if len(records)<2:
                        raise ValueError("Select at least two documents for a shared slip.")
                    self.respond(200,shared_slip_draft(c,records))
                    return
                if path in ("/api/print-batch", "/api/print-job"):
                    content = render_slip_pdf(batch_document(c, records, str(body.get("mode", "combined")),body.get("draft")))
                    if path == "/api/print-job":
                        from print_jobs import create
                        self.respond(200,create(content,user["id"],[r["id"] for r in records]))
                    else:
                        self.respond(200, content, "application/pdf", "NCSC-Routing-Slips.pdf", inline=True)
                else:
                    content, mime, name = export_package(records, str(body.get("format", "xlsx")), str(body.get("paper", "compact")))
                    self.respond(200, content, mime, name)
            return
        with self.write_transaction() as c:
            if path == "/api/acknowledge":
                r = get_record(c,body["id"])
                if not department_access(user,r):
                    raise PermissionError("This document is not assigned to your account or department inbox.")
                if r["deleted_at"] or body.get("version") != r["version"]:
                    self.respond(409,{"error":"This document changed. Reopen it before acknowledging."})
                    return
                department = user["department"].upper()
                shared = r["assigned_user_id"] is None and department in r["departments"]
                if shared:
                    added = c.execute("INSERT OR IGNORE INTO department_acknowledgements VALUES(?,?,?,?,?)",
                        (r["id"],department,r["routing_revision"],user["id"],now())).rowcount
                else:
                    added = c.execute("INSERT OR IGNORE INTO acknowledgements VALUES(?,?,?,?)",(r["id"],user["id"],r["routing_revision"],now())).rowcount
                if added:
                    event(c,r["id"],user,"Document acknowledged" + (" for " + department if shared else ""))
                self.respond(200,{"ok":True})
            elif path == "/api/departments":
                if user["role"] != "admin":
                    raise PermissionError("Administrator access required.")
                code = str(body.get("code", "")).strip().upper()
                name = str(body.get("name", "")).strip()
                if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,19}", code) or not 2 <= len(name) <= 120:
                    raise ValueError("Use a 2–20 character department code and a 2–120 character department name.")
                if code in department_catalog(c):
                    raise ValueError("That department code already exists.")
                c.execute("INSERT INTO departments VALUES(?,?,?)", (code,name,now()))
                administration_event(c,user,"Department added",{"code":code,"name":name})
                self.respond(200,{"ok":True,"code":code})
            elif path == "/api/account-purge":
                if user["role"] != "admin":
                    raise PermissionError("Administrator access required.")
                target = c.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL",(body["id"],)).fetchone()
                if not target or not target["archived_at"] or target["account_type"] != "individual" or target["id"] == user["id"]:
                    raise ValueError("Only archived individual staff accounts can be permanently deleted.")
                if body.get("confirmation") != target["username"]:
                    raise ValueError("Type the exact username to confirm permanent account deletion.")
                administration_event(c,user,"Staff login/profile permanently deleted",{"user_id":target["id"],"username":target["username"]})
                # Preserve a non-login identity so private assignments never become shared.
                c.execute("UPDATE users SET username=?,name='Deleted staff account',password=?,recovery=NULL,active=0,deleted_at=? WHERE id=?",
                          ("removed_"+uuid.uuid4().hex,password_hash(secrets.token_urlsafe(48)),now(),target["id"]))
                invalidate_sessions(target["id"])
                self.respond(200,{"ok":True})
            elif path == "/api/import":
                if not role_editor(user):
                    self.respond(403, {"error": "Records access required."})
                    return
                token = body["token"]
                if len(token) != 32 or any(x not in "0123456789abcdef" for x in token):
                    raise ValueError("Invalid import.")
                previous = c.execute("SELECT collections FROM imports WHERE token=?", (token,)).fetchone()
                if previous and not json.loads(previous["collections"]):
                    raise ValueError("The documents from this import were permanently deleted. Upload the file again to create a new import.")
                metadata = json.loads((FILES / (token + ".json")).read_text(encoding="utf-8"))
                if metadata["owner"] != user["id"]:
                    raise ValueError("Import belongs to another user.")
                previous = c.execute("SELECT collections FROM imports WHERE token=?", (token,)).fetchone()
                if previous:
                    self.respond(200, {"collections": json.loads(previous["collections"])})
                    return
                imported = []
                for selected in body["datasets"]:
                    dataset = metadata["result"]["datasets"][selected["index"]]
                    original_columns = dataset["columns"]
                    columns, normalized = normalize_table(original_columns, dataset["rows"], selected["mappings"])
                    mappings = automatic_mapping(columns)
                    if any(v not in original_columns for v in selected["mappings"].values() if v):
                        raise ValueError("Column mapping is invalid.")
                    mappings = {k: v for k, v in mappings.items() if v}
                    cid = uuid.uuid4().hex
                    c.execute("INSERT INTO collections VALUES(?,?,?,?,?)", (cid, metadata["name"] + " · " + dataset["name"], json.dumps(columns), json.dumps(mappings), now()))
                    for cells in normalized:
                        rid = uuid.uuid4().hex
                        if not cells["Ref. No."]:
                            cells["Ref. No."] = next_reference(c)
                        c.execute("INSERT INTO records(id,collection_id,cells,version,created) VALUES(?,?,?,?,?)", (rid, cid, json.dumps(cells), 1, now()))
                        event(c, rid, user, "Imported from " + metadata["name"])
                    fid = uuid.uuid4().hex
                    c.execute("INSERT INTO files(id,record_id,collection_id,name,path,kind) VALUES(?,?,?,?,?,?)", (fid, None, cid, metadata["name"], token + ".pending", "Original import"))
                    imported.append(cid)
                if not imported:
                    raise ValueError("Select at least one worksheet or table.")
                c.execute("INSERT INTO imports VALUES(?,?)", (token, json.dumps(imported)))
                self.respond(200, {"collections": imported})
            elif path == "/api/save":
                if not may_edit(user):
                    self.respond(403, {"error": "Editing access required."})
                    return
                r = get_record(c, body["id"])
                if not department_access(user, r):
                    self.respond(403, {"error": "This record belongs to another department."})
                    return
                if r["deleted_at"]:
                    raise ValueError("Restore this document before editing.")
                if body["version"] != r["version"]:
                    self.respond(409, {"error": "Another user updated this row. Reopen it before saving."})
                    return
                cells = {h: str(body["cells"].get(h, ""))[:20000] for h in r["columns"]}
                if user["role"] == "staff":
                    allowed = editable_columns(user, r)
                    cells = {h: cells[h] if h in allowed else r["cells"].get(h, "") for h in r["columns"]}
                cells["Ref. No."] = r["cells"].get("Ref. No.") or next_reference(c)
                old_assigned = r["cells"].get(r["mappings"].get("assigned"), "")
                new_assigned = cells.get(r["mappings"].get("assigned"), "")
                status_column = r["mappings"].get("status")
                if status_column:
                    cells[status_column] = canonical_status(cells.get(status_column, ""))
                comment = body.get("comment_text", r["comment_text"])
                if not isinstance(comment,str) or len(comment)>20000:
                    raise ValueError("Enter comments of up to 20,000 characters.")
                if comment != r["comment_text"] and not (r["comment_text"] or
                    canonical_status(r["cells"].get(status_column,"")) == "For Comment" or cells.get(status_column) == "For Comment"):
                    raise ValueError("Set the document to For Comment before entering comments.")
                staff_id = r["assigned_user_id"]
                if role_editor(user):
                    codes = assigned_departments(new_assigned, department_catalog(c))
                    previous = staff_id
                    if "assigned_user_id" not in body and new_assigned != old_assigned:
                        previous = None
                    staff_id = assignment_staff(c, body, codes, previous)
                rerouted = (new_assigned != old_assigned or staff_id != r["assigned_user_id"] or
                            cells.get(r["mappings"].get("action"), "") != r["cells"].get(r["mappings"].get("action"), ""))
                c.execute("UPDATE records SET cells=?,comment_text=?,assigned_user_id=?,version=version+1,routing_revision=routing_revision+? WHERE id=?",
                          (json.dumps(cells), comment, staff_id, int(rerouted), r["id"]))
                event(c, r["id"], user, "Updated record")
                if comment != r["comment_text"]:
                    event(c,r["id"],user,"Comments updated: " + (comment or "[cleared]"))
                if staff_id != r["assigned_user_id"]:
                    name = c.execute("SELECT name FROM users WHERE id=?", (staff_id,)).fetchone() if staff_id else None
                    event(c, r["id"], user, "Assigned staff: " + (name["name"] if name else "Department assignment only"))
                if new_assigned and (new_assigned != old_assigned or
                    cells.get(r["mappings"].get("action"), "") != r["cells"].get(r["mappings"].get("action"), "")):
                    event(c, r["id"], user, "Routed record", {"from": user["department"], "to": new_assigned,
                          "date": datetime.now().strftime("%m/%d/%Y"), "time": datetime.now().strftime("%I:%M %p"),
                          "action_taken":cells.get("Action Taken", ""), "received": ""})
                self.respond(200, {"ok": True})
            elif path == "/api/new":
                if not role_editor(user):
                    self.respond(403, {"error": "ORD access required."})
                    return
                source_token=body.get("source_token")
                source=None
                if source_token:
                    if c.execute("SELECT 1 FROM purged_drafts WHERE token=?", (source_token,)).fetchone():
                        raise ValueError("This source was already registered and permanently deleted. Import it again to create a new document.")
                    folder,metadata=read_draft(source_token,user)
                    previous=c.execute("SELECT record_id FROM document_drafts WHERE token=? AND owner=?",(source_token,user["id"])).fetchone()
                    if previous:
                        record=get_record(c,previous["record_id"])
                        self.respond(200,{"id":record["id"],"collection":record["collection_id"]})
                        return
                    candidate_index=int(body.get("source_row",0))
                    if candidate_index<0 or candidate_index>=len(metadata["candidates"]):
                        raise ValueError("Choose a source row from the file preview.")
                    candidate=metadata["candidates"][candidate_index]
                    source={**metadata["info"],"source_reference":candidate.get("source_reference",""),
                            "sheet":candidate.get("sheet",""),"row":candidate.get("row",""),
                            "attachment_count":len(metadata["attachments"])}
                cid = body.get("collection")
                collection = c.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
                extra=[]
                if source_token:
                    extra=[h for h in candidate["cells"] if h not in STANDARD]
                if not collection:
                    subject = str(body.get("cells", {}).get("Subject", "")).strip()
                    if not subject:
                        raise ValueError("Enter a document subject.")
                    cid = uuid.uuid4().hex
                    columns=list(dict.fromkeys(STANDARD+extra))
                    c.execute("INSERT INTO collections VALUES(?,?,?,?,?)",
                              (cid, (source["filename"] if source else subject)[:200], json.dumps(columns), json.dumps(automatic_mapping(columns)), now()))
                    collection = c.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
                columns = json.loads(collection["columns"])
                mapping = json.loads(collection["mappings"])
                additions=[h for h in extra if h not in columns]
                if additions:
                    columns+=additions
                    c.execute("UPDATE collections SET columns=? WHERE id=?",(json.dumps(columns),cid))
                    c.execute("UPDATE records SET version=version+1 WHERE collection_id=?",(cid,))
                cells = {h: str(body.get("cells", {}).get(h, ""))[:20000] for h in columns}
                subject = cells.get(mapping.get("subject"), "").strip()
                if not subject:
                    raise ValueError("Enter a document subject. Map the Subject column in worksheet settings if needed.")
                for followup in ("Action Taken", "MOV 1", "MOV 2"):
                    cells[followup] = ""
                # Source serial/reference numbers never become the new register identity.
                for column in columns:
                    if norm(column) in ("no","rowno","rownumber","sourcerowno","sourcerownumber","serialno","serialnumber","sno"):
                        cells[column]=""
                reference = mapping.get("reference")
                if reference:
                    cells[reference] = next_reference(c)
                assigned = cells.get(mapping.get("assigned"), "")
                status_column = mapping.get("status")
                if status_column:
                    cells[status_column] = canonical_status(cells.get(status_column, ""))
                staff_id = assignment_staff(c, body, assigned_departments(assigned, department_catalog(c)))
                rid = uuid.uuid4().hex
                comment = body.get("comment_text", "")
                if not isinstance(comment,str) or len(comment)>20000 or (comment and cells.get(status_column)!="For Comment"):
                    raise ValueError("Comments require For Comment status and must be up to 20,000 characters.")
                c.execute("INSERT INTO records(id,collection_id,cells,version,created,assigned_user_id,comment_text) VALUES(?,?,?,?,?,?,?)",
                          (rid, cid, json.dumps(cells), 1, now(), staff_id, comment))
                event(c, rid, user, "Document registered")
                if comment:
                    event(c,rid,user,"Comments added: " + comment)
                if staff_id:
                    staff_name = c.execute("SELECT name FROM users WHERE id=?", (staff_id,)).fetchone()["name"]
                    event(c, rid, user, "Assigned staff: " + staff_name)
                if source:
                    entries=[{"path":"original","name":source["filename"],"kind":
                              "Original import" if source["type"]=="Spreadsheet" else "Source email" if source["type"]=="Email" else "Source document"}]+metadata["attachments"]
                    for entry in entries:
                        fid=uuid.uuid4().hex
                        shutil.copyfile(folder/entry["path"],FILES/fid)
                        c.execute("INSERT INTO files(id,record_id,collection_id,name,path,kind,slot) VALUES(?,?,?,?,?,?,?)",
                                  (fid,rid,None,entry["name"],fid,entry.get("kind","Email attachment"),1))
                    c.execute("INSERT INTO record_sources VALUES(?,?)",(rid,json.dumps(source)))
                    c.execute("INSERT INTO document_drafts VALUES(?,?,?)",(source_token,user["id"],rid))
                    event(c,rid,user,"Registered from "+source["filename"]+" ("+str(len(metadata["attachments"]))+" attachments)")
                if assigned:
                    event(c, rid, user, "Routed record", {"from":user["department"], "to":assigned,
                          "date":datetime.now().strftime("%m/%d/%Y"), "time":datetime.now().strftime("%I:%M %p"),
                          "action_taken":cells.get("Action Taken", ""), "received":""})
                self.respond(200, {"id": rid, "collection": cid})
            elif path == "/api/archive-collections":
                if not role_editor(user):
                    raise PermissionError("Records administration access required.")
                items = body.get("items")
                if not isinstance(items, list) or not 1 <= len(items) <= 10000:
                    raise ValueError("Select at least one imported file or worksheet.")
                records, seen = [], set()
                for item in items:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
                        raise ValueError("Invalid or duplicate worksheet selection.")
                    cid = item["id"]
                    if not c.execute("SELECT 1 FROM collections WHERE id=?", (cid,)).fetchone() or item.get("revision") != collection_revision(c, cid):
                        self.respond(409, {"error":"A selected worksheet changed. Refresh and select again. No documents were moved."})
                        return
                    records += [get_record(c, row["id"]) for row in c.execute("SELECT id FROM records WHERE collection_id=? AND deleted_at IS NULL", (cid,))]
                    seen.add(cid)
                if not records or len(records) > 10000:
                    raise ValueError("Select worksheets containing between 1 and 10,000 active documents.")
                for record in records:
                    c.execute("UPDATE records SET deleted_at=?,version=version+1 WHERE id=?", (now(), record["id"]))
                    event(c, record["id"], user, "Moved to Deleted documents (selected imported worksheets)")
                self.respond(200, {"ok":True,"count":len(records)})
            elif path in ("/api/restore-batch", "/api/purge-batch"):
                if not role_editor(user):
                    raise PermissionError("Records administration access required.")
                if path == "/api/purge-batch" and user["role"] != "admin":
                    raise PermissionError("Only an administrator can permanently delete documents.")
                records = batch_records(c, user, body.get("items"), deleted=True)
                if path == "/api/purge-batch":
                    if str(body.get("confirmation", "")).strip() != "DELETE " + str(len(records)):
                        raise ValueError("Type DELETE followed by the selected document count to confirm.")
                    for record in records:
                        permanently_delete(c, record, user, commit=False)
                    c.commit()
                    pending = finish_file_deletions(c)
                    self.respond(200, {"ok":True,"count":len(records),"cleanup_pending":pending})
                else:
                    for record in records:
                        c.execute("UPDATE records SET deleted_at=NULL,version=version+1 WHERE id=?", (record["id"],))
                        event(c, record["id"], user, "Document restored (selected batch)")
                    self.respond(200, {"ok":True,"count":len(records)})
            elif path == "/api/archive-batch":
                if not role_editor(user):
                    raise PermissionError("Records administration access required.")
                items = body.get("items")
                if not isinstance(items, list) or not 1 <= len(items) <= 10000:
                    raise ValueError("Select between 1 and 10,000 documents.")
                records, seen = [], set()
                # Validate the entire batch before changing any row.
                for item in items:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
                        raise ValueError("The selection contains invalid or duplicate documents.")
                    r = get_record(c, item["id"])
                    if r["deleted_at"] or item.get("version") != r["version"]:
                        self.respond(409, {"error":"A selected document changed or was deleted. Refresh and select the documents again. No documents were moved."})
                        return
                    if not department_access(user, r):
                        raise PermissionError("One of the selected documents is outside your access.")
                    records.append(r)
                    seen.add(r["id"])
                at = now()
                for r in records:
                    c.execute("UPDATE records SET deleted_at=?,version=version+1 WHERE id=?", (at, r["id"]))
                    event(c, r["id"], user, "Moved to Deleted documents (selected batch)")
                self.respond(200, {"ok":True, "count":len(records)})
            elif path == "/api/purge":
                if user["role"] != "admin":
                    raise PermissionError("Only an administrator can permanently delete documents.")
                r = get_record(c, body["id"])
                if not r["deleted_at"]:
                    raise ValueError("Move the document to Deleted documents first.")
                if body.get("version") != r["version"]:
                    self.respond(409, {"error":"This document changed. Refresh Deleted documents before continuing."})
                    return
                reference = r["cells"].get("Ref. No.", "") or r["id"][:8].upper()
                if str(body.get("confirmation", "")).strip() != reference:
                    raise ValueError("Type the exact reference number to confirm permanent deletion.")
                pending = permanently_delete(c, r, user)
                self.respond(200, {"ok":True, "cleanup_pending":pending})
            elif path in ("/api/archive", "/api/restore"):
                if not role_editor(user):
                    self.respond(403, {"error": "ORD access required."})
                    return
                r = get_record(c, body["id"])
                if body.get("version") != r["version"]:
                    self.respond(409, {"error": "This record changed. Refresh before continuing."})
                    return
                deleted = now() if path == "/api/archive" else None
                c.execute("UPDATE records SET deleted_at=?,version=version+1 WHERE id=?", (deleted, r["id"]))
                event(c, r["id"], user, "Moved to Deleted documents" if deleted else "Document restored")
                self.respond(200, {"ok": True})
            elif path in ("/api/account-archive", "/api/account-restore"):
                if user["role"] != "admin":
                    raise PermissionError("Administrator access required.")
                target = c.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (body["id"],)).fetchone()
                if not target:
                    raise ValueError("Staff account not found.")
                if target["id"] == user["id"]:
                    raise ValueError("You cannot archive your signed-in account.")
                archive = path == "/api/account-archive"
                if archive and target["archived_at"]:
                    raise ValueError("This account is already archived.")
                if not archive and not target["archived_at"]:
                    raise ValueError("This account is not archived.")
                if archive and target["role"] == "admin" and target["active"] and c.execute(
                        "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND archived_at IS NULL").fetchone()[0] <= 1:
                    raise ValueError("Keep at least one active administrator account.")
                c.execute("UPDATE users SET active=0,archived_at=?,recovery=NULL WHERE id=?",
                          (now() if archive else None, target["id"]))
                invalidate_sessions(target["id"])
                administration_event(c, user, "Account archived" if archive else "Account restored",
                                     {"user_id":target["id"], "username":target["username"]})
                self.respond(200, {"ok":True})
            elif path == "/api/account-update":
                if user["role"] != "admin":
                    self.respond(403, {"error": "ORD administrator access required."})
                    return
                target = c.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (body["id"],)).fetchone()
                if not target:
                    raise ValueError("Department account not found.")
                if target["archived_at"]:
                    raise ValueError("Restore this archived account before editing or enabling it.")
                username = str(body.get("username", "")).strip().upper()
                name = str(body.get("name", "")).strip()
                department = require_department(c, body.get("department", ""))
                role = str(body.get("role", "staff"))
                account_type = str(body.get("account_type", "individual"))
                active = 1 if body.get("active", True) else 0
                if account_type not in ("individual", "department"):
                    raise ValueError("Invalid account type.")
                if not username or not name or not department:
                    raise ValueError("Complete the department details.")
                if role not in ("admin", "records", "staff", "viewer"):
                    raise ValueError("Invalid access setting.")
                if target["id"] == user["id"] and not active:
                    raise ValueError("You cannot disable your current account.")
                if target["role"] == "admin" and target["active"] and (role != "admin" or not active) and c.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] == 1:
                    raise ValueError("Keep at least one ORD administrator account.")
                duplicate = c.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE AND id<>?",
                                      (username, target["id"])).fetchone()
                if duplicate:
                    raise ValueError("That department username already exists.")
                c.execute("UPDATE users SET username=?,name=?,department=?,role=?,active=?,account_type=? WHERE id=?",
                          (username, name, department, role, active, account_type, target["id"]))
                if not active:
                    invalidate_sessions(target["id"])
                self.respond(200, {"ok": True})
            elif path == "/api/account-recovery":
                if user["role"] != "admin":
                    self.respond(403, {"error": "ORD administrator access required."})
                    return
                target = c.execute("SELECT id,archived_at FROM users WHERE id=? AND deleted_at IS NULL", (body["id"],)).fetchone()
                if not target:
                    raise ValueError("Department account not found.")
                if target["archived_at"]:
                    raise ValueError("Restore this archived account before generating a recovery code.")
                code = recovery_code()
                c.execute("UPDATE users SET recovery=? WHERE id=?", (password_hash(code), target["id"]))
                self.respond(200, {"recovery_code": code})
            elif path == "/api/attach":
                if not may_edit(user):
                    self.respond(403, {"error": "Editing access required."})
                    return
                r = get_record(c, body["record"])
                if not department_access(user, r):
                    self.respond(403, {"error": "Access denied."})
                    return
                if r["deleted_at"]:
                    raise ValueError("Restore the document before uploading files.")
                if body.get("version") and int(body["version"]) != r["version"]:
                    self.respond(409, {"error":"This record changed. Reopen it before uploading."})
                    return
                file, fid = body["file"], uuid.uuid4().hex
                kind = "MOV" if str(body.get("kind","MOV")).upper().startswith("MOV") else "Document"
                slot = int(body.get("slot", 1))
                if slot not in (1,2):
                    raise ValueError("Choose MOV 1 or MOV 2.")
                (FILES / fid).write_bytes(file["data"])
                c.execute("INSERT INTO files(id,record_id,collection_id,name,path,kind,slot) VALUES(?,?,?,?,?,?,?)",
                          (fid,r["id"],None,file["name"],fid,kind,slot))
                c.execute("UPDATE records SET version=version+1 WHERE id=?", (r["id"],))
                event(c,r["id"],user, "Added " + ("MOV "+str(slot) if kind=="MOV" else "document") + " — " + file["name"])
                self.respond(200, {"ok": True})
            elif path == "/api/columns":
                if not role_editor(user):
                    self.respond(403, {"error": "Records access required."})
                    return
                col = c.execute("SELECT * FROM collections WHERE id=?", (body["id"],)).fetchone()
                if not col:
                    raise ValueError("Collection not found.")
                original = json.loads(col["columns"])
                additions = [str(name).strip()[:150] for name in body.get("add",[]) if str(name).strip()]
                columns = list(dict.fromkeys(original + additions))
                mappings = body["mappings"]
                if any(value not in columns for value in mappings.values() if value):
                    raise ValueError("Choose a valid column.")
                records = c.execute("SELECT id,cells FROM records WHERE collection_id=?", (col["id"],)).fetchall()
                raw_cells = [json.loads(row["cells"]) for row in records]
                headers, normalized = normalize_table(columns, [[cells.get(h,"") for h in columns] for cells in raw_cells], mappings)
                for row,cells in zip(records,normalized):
                    c.execute("UPDATE records SET cells=?,version=version+1 WHERE id=?", (json.dumps(cells),row["id"]))
                c.execute("UPDATE collections SET columns=?,mappings=? WHERE id=?",
                          (json.dumps(headers),json.dumps(automatic_mapping(headers)),col["id"]))
                self.respond(200, {"ok": True})
            elif path == "/api/users":
                if user["role"] != "admin":
                    self.respond(403, {"error": "Administrator access required."})
                    return
                if len(body.get("password", "")) < 8:
                    raise ValueError("Use a password of at least 8 characters.")
                if body["role"] not in ("admin", "records", "staff", "viewer"):
                    raise ValueError("Invalid role.")
                if not all(body.get(k, "").strip() for k in ("username", "name", "department")):
                    raise ValueError("Complete all account details.")
                if c.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE", (body["username"].strip(),)).fetchone():
                    raise ValueError("That department username already exists.")
                code = recovery_code()
                c.execute("INSERT INTO users(username,password,name,role,department,recovery) VALUES(?,?,?,?,?,?)",
                          (body["username"].strip(), password_hash(body["password"]), body["name"].strip(),
                           body["role"], require_department(c,body["department"]), password_hash(code)))
                self.respond(200, {"ok": True, "recovery_code": code})
            elif path == "/api/password":
                credentials = c.execute("SELECT password,recovery FROM users WHERE id=?", (user["id"],)).fetchone()
                if not password_ok(body.get("current", ""), credentials["password"]):
                    raise ValueError("Current password is incorrect.")
                code = str(body.get("code", "")).strip().upper()
                if not code or not credentials["recovery"] or not password_ok(code, credentials["recovery"]):
                    raise ValueError("Enter your valid generated recovery code. If you lost it, request a replacement from the administrator.")
                if len(body.get("password", "")) < 8:
                    raise ValueError("Use at least 8 characters.")
                if body.get("confirmation") != body["password"]:
                    raise ValueError("The new password and confirmation do not match.")
                new_code = recovery_code()
                c.execute("UPDATE users SET password=?,recovery=? WHERE id=?",
                          (password_hash(body["password"]), password_hash(new_code), user["id"]))
                administration_event(c, user, "Password changed with recovery-code verification", {"account_id":user["id"]})
                # Keep this verified session; other sessions must use the new password.
                for token, other in list(SESSIONS.items()):
                    if other["user"] == user["id"] and other is not session:
                        SESSIONS.pop(token, None)
                self.respond(200, {"ok": True,"recovery_code":new_code})
            else:
                self.respond(404, {"error": "Not found."})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    init()
    print(f"NCSC RO1 ready at http://{args.host}:{args.port}")
    print("Create the first administrator on the host computer before enabling LAN access.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    if args.open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    server.serve_forever()
