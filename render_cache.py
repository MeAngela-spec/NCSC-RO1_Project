"""Bounded, short-lived in-memory rendering cache; authorization stays at each endpoint."""
from collections import OrderedDict
import threading
import time


class RenderCache:
    def __init__(self, max_bytes=48 * 1024 * 1024, ttl=600, max_entries=40):
        self.max_bytes, self.ttl, self.max_entries = max_bytes, ttl, max_entries
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry[0] < time.monotonic():
                self._bytes -= len(self._entries.pop(key)[1])
                return None
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, key, value):
        if len(value) > self.max_bytes:
            return value
        with self._lock:
            if key in self._entries:
                self._bytes -= len(self._entries.pop(key)[1])
            self._entries[key] = (time.monotonic() + self.ttl, value)
            self._bytes += len(value)
            while self._bytes > self.max_bytes or len(self._entries) > self.max_entries:
                self._bytes -= len(self._entries.popitem(last=False)[1][1])
        return value
