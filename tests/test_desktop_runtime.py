from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from desktop_runtime import (application_home, load_settings, save_settings,
    normalize_host_url, import_workspace, backup_workspace)


class ConnectionAndDataTests(unittest.TestCase):
    def test_connection_round_trip_and_url_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertIsNone(load_settings(path))
            saved = save_settings(path, {"mode":"client", "port":8765, "host_url":"192.168.1.30:8765/", "keep_awake":False})
            self.assertEqual(saved, load_settings(path))
            self.assertEqual(saved["host_url"], "http://192.168.1.30:8765")
            self.assertEqual(normalize_host_url("http://[::1]:8765"), "http://[::1]:8765")
            for value in ["file:///C:/data", "http://name:secret@host", "http://host/login", "http://host?key=secret", "http://host:99999", "http://my host"]:
                with self.assertRaises(ValueError):
                    normalize_host_url(value)
            with self.assertRaises(ValueError):
                save_settings(path, {"mode":"host", "port":80})
            with patch.dict(os.environ, {"NCSC_HOME":directory}):
                self.assertEqual(application_home(), path.resolve())

    def test_data_import_retains_original_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "old-data"
            (source / "files").mkdir(parents=True)
            with closing(sqlite3.connect(source / "register.sqlite3")) as db:
                db.executescript("CREATE TABLE users(id); CREATE TABLE records(id); CREATE TABLE collections(id); CREATE TABLE files(id); INSERT INTO records VALUES(1);")
            (source / "files/original-file").write_bytes(b"fictional supporting file")
            destination = home / "new-data"
            import_workspace(source, destination)
            self.assertTrue((source / "register.sqlite3").exists())
            self.assertEqual((destination / "files/original-file").read_bytes(), b"fictional supporting file")
            with self.assertRaises(ValueError):
                import_workspace(source, destination)
            with self.assertRaises(ValueError):
                backup_workspace(destination, destination / "unsafe.zip")
            backup = backup_workspace(destination, home / "backup.zip")
            self.assertTrue(backup.is_file())
            with self.assertRaises(ValueError):
                backup_workspace(destination, backup)

    def test_invalid_settings_are_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "connection.json").write_text("not valid json")
            with self.assertRaises(ValueError):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
