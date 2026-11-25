"""Real HTTP checks for department assignment and recoverable batch operations."""
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_runtime import HostService
from self_check import Client


class DepartmentAndBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="ncsc-workflow-tests-")
        cls.service = HostService(Path(cls.temporary.name) / "data", port=0, address="127.0.0.1")
        cls.service.start()
        cls.app = cls.service.backend
        cls.admin = Client(cls.service.local_url)
        cls.admin.request("/api/setup", {"username":"fixture.admin", "name":"Fictional administrator", "password":"fixture-password-123"})
        cls.admin.csrf = cls.admin.request("/api/me")["csrf"]
        for username, department, role in [("fixture.ops","OPS","staff"), ("fixture.afs","AFS","staff"), ("fixture.records","ORD","records"), ("fixture.review","OPS","viewer")]:
            cls.admin.request("/api/users", {"username":username,"name":username,"department":department,"role":role,"password":"fixture-password-123"})
        cls.users = {row["username"]:row for row in cls.admin.request("/api/users")}

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()
        cls.temporary.cleanup()

    def client(self, username):
        client = Client(self.service.local_url)
        client.request("/api/login", {"username":username,"password":"fixture-password-123"})
        client.csrf = client.request("/api/me")["csrf"]
        return client

    def record(self, rid):
        return self.admin.request("/api/record/" + rid)

    def items(self, ids):
        return [{"id":rid,"version":self.record(rid)["version"]} for rid in ids]

    def test_department_staff_membership_status_and_history(self):
        ops = self.users["fixture.ops"]["id"]
        afs = self.users["fixture.afs"]["id"]
        before = len(self.admin.request("/api/register"))
        self.admin.request("/api/new", {"cells":{"Subject":"Invalid staff assignment","Assigned to":"OPS"},"assigned_user_id":afs}, expected=400)
        self.assertEqual(len(self.admin.request("/api/register")), before)
        rid = self.admin.request("/api/new", {"cells":{"Subject":"Fictional coordination","Assigned to":"OPS"},"assigned_user_id":ops})["id"]
        row = self.record(rid)
        self.assertEqual(row["departments"], ["OPS"])
        self.assertEqual(row["assigned_staff"]["id"], ops)
        self.assertEqual(row["cells"]["Status"], "For routing")
        staff = self.client("fixture.ops")
        self.assertEqual([d["code"] for d in staff.request("/api/departments")], ["OPS"])
        self.client("fixture.afs").request("/api/record/"+rid, expected=403)
        for status in ["Received","Pending","Ongoing","Completed","For Comment","For Signature","Awaiting legal review"]:
            row = self.record(rid)
            staff.request("/api/save", {"id":rid,"version":row["version"],"cells":{**row["cells"],"Status":status,"Assigned to":"AFS"},"assigned_user_id":afs})
            row = self.record(rid)
            self.assertEqual(row["cells"]["Status"], status)
            self.assertEqual(row["assigned_user_id"], ops)
            self.assertEqual(row["cells"]["Assigned to"], "OPS")
        self.admin.request("/api/save", {"id":rid,"version":row["version"],"cells":{**row["cells"],"Assigned to":"AFS"},"assigned_user_id":ops}, expected=400)
        self.assertEqual(self.record(rid)["version"], row["version"])
        self.admin.request("/api/save", {"id":rid,"version":row["version"],"cells":{**row["cells"],"Assigned to":"AFS"}})
        self.assertIsNone(self.record(rid)["assigned_user_id"])
        self.assertTrue(any("Assigned staff" in event["message"] for event in self.record(rid)["events"]))
        directory = self.admin.request("/api/directory")
        self.assertNotIn(self.users["fixture.review"]["id"], [u["id"] for u in directory])
        shared = self.admin.request("/api/new", {"cells":{"Subject":"Fictional joint assignment","Assigned to":"AFS / OPS"}})["id"]
        self.assertEqual(self.record(shared)["departments"], ["AFS","OPS"])
        staff.request("/api/record/"+shared)
        self.client("fixture.afs").request("/api/record/"+shared)

    def test_memo_reference_sequence_collision_and_legacy_retention(self):
        year = datetime.now().year
        with self.app.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO reference_sequence VALUES(?,987654)", (year,))
            prior = connection.execute("SELECT last FROM memo_reference_sequence WHERE year=?", (year,)).fetchone()
            collision = (prior["last"] if prior else 0) + 1
        imported_reference = f"RO1-MEMO-{year}-{collision:05d}"
        legacy_reference = f"RO1-{year}-000001"
        csv = ("Subject,Ref. No.,Assigned to\nFictional imported memo,"+imported_reference+",ORD\nFictional legacy record,"+legacy_reference+",OPS\n").encode()
        preview = self.admin.request("/api/preview", {}, upload=("Fictional-reference-matrix.csv",csv))
        imported = self.admin.request("/api/import", {"token":preview["token"],"datasets":[{"index":0,"mappings":preview["datasets"][0]["mappings"]}]})
        def register(index):
            client = self.client("fixture.admin")
            rid = client.request("/api/new", {"cells":{"Subject":"Fictional concurrent memo "+str(index)}})["id"]
            return client.request("/api/record/"+rid)["cells"]["Ref. No."]
        with ThreadPoolExecutor(max_workers=4) as pool:
            references = list(pool.map(register, range(4)))
        self.assertEqual(set(references), {f"RO1-MEMO-{year}-{collision+offset:05d}" for offset in range(1,5)})
        self.app.init()
        retained = [r["cells"]["Ref. No."] for r in self.admin.request("/api/register") if r["collection_id"] in imported["collections"]]
        self.assertEqual(set(retained), {imported_reference,legacy_reference})
        with patch.object(self.app,"datetime") as clock:
            clock.now.return_value = datetime(2042,1,2,9,0)
            rid = self.admin.request("/api/new", {"cells":{"Subject":"Fictional new-year memo"}})["id"]
            self.assertEqual(self.record(rid)["cells"]["Ref. No."], "RO1-MEMO-2042-00001")
        before = len(self.admin.request("/api/register"))
        with self.app.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO memo_reference_sequence VALUES(2043,99999)")
            collections_before = connection.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
        with patch.object(self.app,"datetime") as clock:
            clock.now.return_value = datetime(2043,1,2,9,0)
            self.admin.request("/api/new", {"cells":{"Subject":"Fictional exhausted sequence"}}, expected=400)
        self.assertEqual(len(self.admin.request("/api/register")), before)
        with self.app.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM collections").fetchone()[0], collections_before)
            self.assertEqual(connection.execute("SELECT last FROM memo_reference_sequence WHERE year=2043").fetchone()[0], 99999)

    def test_password_change_verifies_rotates_code_and_ends_other_sessions(self):
        created = self.admin.request("/api/users", {"username":"fixture.password","name":"Fictional password test","department":"OPS","role":"staff","password":"fixture-password-123"})
        saved_code = created["recovery_code"]
        client = self.client("fixture.password")
        other = self.client("fixture.password")
        new_password = "new-fixture-password-456"
        body = {"current":"fixture-password-123","password":new_password,"confirmation":new_password}
        client.request("/api/password", body, expected=400)
        client.request("/api/password", {**body,"code":"wrong-code"}, expected=400)
        client.request("/api/password", {**body,"code":saved_code,"confirmation":"does-not-match"}, expected=400)
        client.request("/api/password", {**body,"code":saved_code,"current":"wrong-current-password"}, expected=400)
        self.assertIsNotNone(other.request("/api/me")["user"])
        result = client.request("/api/password", {**body,"code":saved_code.lower()})
        self.assertNotEqual(result["recovery_code"], saved_code)
        self.assertIsNotNone(client.request("/api/me")["user"])
        self.assertIsNone(other.request("/api/me")["user"])
        client.request("/api/password", {**body,"current":new_password,"code":saved_code}, expected=400)
        Client(self.service.local_url).request("/api/login", {"username":"fixture.password","password":"fixture-password-123"}, expected=401)
        new_session = Client(self.service.local_url)
        new_session.request("/api/login", {"username":"fixture.password","password":new_password})
        client.request("/api/recover", {"username":"fixture.password","code":saved_code,"password":"reset-fixture-password"}, expected=400)
        reset = client.request("/api/recover", {"username":"fixture.password","code":result["recovery_code"],"password":"reset-fixture-password"})
        self.assertNotEqual(reset["recovery_code"], result["recovery_code"])
        self.assertIsNone(client.request("/api/me")["user"])
        Client(self.service.local_url).request("/api/login", {"username":"fixture.password","password":"reset-fixture-password"})

    def test_import_bulk_restore_and_purge_preserve_shared_files(self):
        import openpyxl
        workbook = openpyxl.Workbook()
        first = workbook.active
        first.title = "Routing"
        first.append(["Subject","Assigned to","Status"])
        first.append(["Fictional document A","OPS","Pending"])
        first.append(["Fictional document B","AFS","Ongoing"])
        second = workbook.create_sheet("Follow-up")
        second.append(["Subject","Assigned to","Status"])
        second.append(["Fictional document C","OPS","Received"])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        original = output.getvalue()
        preview = self.admin.request("/api/preview", {}, upload=("Fictional-workbook.xlsx", original))
        imported = self.admin.request("/api/import", {"token":preview["token"],"datasets":[{"index":i,"mappings":d["mappings"]} for i,d in enumerate(preview["datasets"])]})
        cids = imported["collections"]
        ids = [r["id"] for r in self.admin.request("/api/register") if r["collection_id"] in cids]
        self.assertEqual(len(ids), 3)
        collections = [c for c in self.admin.request("/api/collections") if c["id"] in cids]
        selection = [{"id":c["id"],"revision":c["revision"]} for c in collections]
        self.admin.request("/api/archive-collections", {"items":[selection[0],{**selection[1],"revision":"stale"}]}, expected=409)
        self.assertTrue(all(not self.record(rid)["deleted_at"] for rid in ids))
        first_row = self.record(ids[0])
        evidence = b"Fictional supporting evidence"
        self.admin.request("/api/attach", {"record":ids[0],"version":first_row["version"],"kind":"MOV","slot":1}, upload=("Evidence.txt",evidence))
        selection = [{"id":c["id"],"revision":c["revision"]} for c in self.admin.request("/api/collections") if c["id"] in cids]
        self.assertEqual(self.admin.request("/api/archive-collections", {"items":selection})["count"], 3)
        items = self.items(ids)
        self.admin.request("/api/restore-batch", {"items":[items[0],{**items[1],"version":0}]}, expected=400)
        self.assertTrue(all(self.record(rid)["deleted_at"] for rid in ids))
        self.assertEqual(self.admin.request("/api/restore-batch", {"items":items})["count"], 3)
        row = self.record(ids[0])
        file_id = next(f["id"] for f in row["files"] if f["name"] == "Evidence.txt")
        self.assertEqual(self.admin.request("/api/file/"+file_id), evidence)
        self.admin.request("/api/archive-batch", {"items":self.items(ids)})
        lone = next(rid for rid in ids if sum(self.record(other)["collection_id"]==self.record(rid)["collection_id"] for other in ids)==1)
        self.admin.request("/api/purge-batch", {"items":self.items([lone]),"confirmation":"DELETE 1"})
        with self.app.connect() as connection:
            source = connection.execute("SELECT path FROM files WHERE kind='Original import' AND collection_id IN (?,?)", cids).fetchone()["path"]
        self.assertEqual((self.app.FILES/source).read_bytes(), original)
        remaining = [rid for rid in ids if rid != lone]
        items = self.items(remaining)
        self.admin.request("/api/purge-batch", {"items":[items[0],{**items[1],"version":0}],"confirmation":"DELETE 2"}, expected=400)
        self.admin.request("/api/purge-batch", {"items":items,"confirmation":"wrong"}, expected=400)
        self.assertTrue(all(self.record(rid)["deleted_at"] for rid in remaining))
        result = self.admin.request("/api/purge-batch", {"items":items,"confirmation":"DELETE 2"})
        self.assertEqual(result["count"], 2)
        self.assertFalse(result["cleanup_pending"])
        self.assertFalse((self.app.FILES/source).exists())
        self.assertFalse((self.app.FILES/file_id).exists())

    def test_bulk_permissions_and_duplicate_selection(self):
        rid = self.admin.request("/api/new", {"cells":{"Subject":"Fictional restricted deletion","Assigned to":"OPS"}})["id"]
        items = self.items([rid])
        self.client("fixture.ops").request("/api/archive-collections", {"items":[]}, expected=403)
        self.client("fixture.review").request("/api/restore-batch", {"items":items}, expected=403)
        self.admin.request("/api/archive-batch", {"items":items})
        items = self.items([rid])
        self.client("fixture.records").request("/api/purge-batch", {"items":items,"confirmation":"DELETE 1"}, expected=403)
        self.admin.request("/api/restore-batch", {"items":items+items}, expected=400)
        self.assertTrue(self.record(rid)["deleted_at"])
        self.client("fixture.records").request("/api/restore-batch", {"items":items})
        self.assertIsNone(self.record(rid)["deleted_at"])


if __name__ == "__main__":
    unittest.main()
