"""For internal use only. It provides a slice-like file reader."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, overload

from maxminddb.errors import InvalidDatabaseError

try:
    from multiprocessing import Lock
except ImportError:
    from threading import Lock  # type: ignore[assignment]

if TYPE_CHECKING:
    from maxminddb.types import StrOrBytesPath

# A read inside the size at open came back short, so the file shrank.
_SHORT_READ = "The database file changed after the reader opened it."


class FileBuffer:
    """A slice-able file reader."""

    def __init__(self, database: StrOrBytesPath | int) -> None:
        """Create FileBuffer."""
        self._handle = open(database, "rb")  # noqa: SIM115
        self._size = os.fstat(self._handle.fileno()).st_size
        if not hasattr(os, "pread"):
            self._lock = Lock()

    @overload
    def __getitem__(self, index: int) -> int: ...

    @overload
    def __getitem__(self, index: slice) -> bytes: ...

    def __getitem__(self, index: slice | int) -> bytes | int:
        """Get item by index."""
        # Past the size at open, a read acts as on bytes: a slice returns
        # fewer bytes, and an index raises IndexError.
        if isinstance(index, slice):
            size = index.stop - index.start
            data = self._read(size, index.start)
            if len(data) != size and index.stop <= self._size:
                raise InvalidDatabaseError(_SHORT_READ)
            return data
        if isinstance(index, int):
            data = self._read(1, index)
            if data:
                return data[0]
            if index < self._size:
                raise InvalidDatabaseError(_SHORT_READ)
            msg = "FileBuffer index out of range"
            raise IndexError(msg)
        msg = "Invalid argument type."
        raise TypeError(msg)

    def rfind(self, needle: bytes, start: int) -> int:
        """Reverse find needle from start."""
        pos = self._read(self._size - start, start).rfind(needle)
        if pos == -1:
            return pos
        return start + pos

    def size(self) -> int:
        """Size of file."""
        return self._size

    def close(self) -> None:
        """Close file."""
        self._handle.close()

    if hasattr(os, "pread"):

        def _read(self, buffersize: int, offset: int) -> bytes:
            """Read that uses pread."""
            return os.pread(self._handle.fileno(), buffersize, offset)  # type: ignore[attr-defined]

    else:

        def _read(self, buffersize: int, offset: int) -> bytes:
            """Read with a lock.

            This lock is necessary as after a fork, the different processes
            will share the same file table entry, even if we dup the fd, and
            as such the same offsets. There does not appear to be a way to
            duplicate the file table entry and we cannot re-open based on the
            original path as that file may have replaced with another or
            unlinked.
            """
            with self._lock:
                self._handle.seek(offset)
                return self._handle.read(buffersize)
