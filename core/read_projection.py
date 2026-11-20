"""Bounded cache of small read models, invalidated by actual file replacement/content metadata.
Live AI conversations validate their owner on cache hits, even without a journal write.
"""
from collections import OrderedDict
from copy import deepcopy
import threading


class ProjectionCache:
    def __init__(self, limit=8):
        self.limit = limit
        self.entries = OrderedDict()
        self.lock = threading.RLock()

    @staticmethod
    def signature(path):
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino
        except FileNotFoundError:
            return None

    def get(self, path, build, validate=None):
        key = str(path.resolve())
        with self.lock:
            signature = self.signature(path)
            cached = self.entries.get(key)
            if cached and cached[0] == signature and (validate is None or validate(cached[1])):
                self.entries.move_to_end(key)
                return deepcopy(cached[1])
            value, volatile = build()
            if not volatile and signature == self.signature(path):
                self.entries[key] = (signature, deepcopy(value))
                self.entries.move_to_end(key)
                while len(self.entries) > self.limit:
                    self.entries.popitem(last=False)
            else:
                self.entries.pop(key, None)
            return value


CACHE = ProjectionCache()
