"""Per-file content-hash cache for call-graph extraction.

Models chiasmus `src/graph/cache.ts` at the level the substrate needs: cache the
per-file CodeGraph keyed on a hash of (path, content), so building the graph for
a project only re-extracts the files whose content changed. This is the
"hang it off edited-file tracking, re-run touched files on write" idea from #39.

In-process (a module-level dict) rather than chiasmus's on-disk store — enough
for incremental recompute within a running v3-service. A bounded LRU keeps it
from growing without limit across many projects.
"""

from __future__ import annotations

import copy
import hashlib
from collections import OrderedDict
from typing import Optional

from .extract import extract_file
from .types import CodeGraph


def file_hash(path: str, content: str) -> str:
    h = hashlib.sha256()
    h.update(content.encode("utf-8"))
    h.update(b"\x00")
    h.update(path.encode("utf-8"))
    return h.hexdigest()


class FileGraphCache:
    """Bounded LRU mapping file-hash -> per-file CodeGraph."""

    def __init__(self, max_entries: int = 4096):
        self._max = max_entries
        self._store: "OrderedDict[str, CodeGraph]" = OrderedDict()

    def get_or_extract(self, path: str, content: str) -> CodeGraph:
        key = file_hash(path, content)
        hit = self._store.get(key)
        if hit is not None:
            self._store.move_to_end(key)
            # Return a copy: callers (build_graph -> resolve_imports) mutate
            # ImportsFact.resolved in place, which would otherwise corrupt the
            # cached per-file graph and leak resolution state across requests
            # with different file sets.
            return copy.deepcopy(hit)
        g = extract_file(path, content)
        self._store[key] = g
        while len(self._store) > self._max:
            self._store.popitem(last=False)
        return copy.deepcopy(g)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# Shared default cache for the running process.
_DEFAULT_CACHE: Optional[FileGraphCache] = None


def default_cache() -> FileGraphCache:
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        _DEFAULT_CACHE = FileGraphCache()
    return _DEFAULT_CACHE
