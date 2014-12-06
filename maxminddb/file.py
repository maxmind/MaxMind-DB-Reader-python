"""This is intended for internal use only"""

import os


class FileBuffer(object):

    """A slice-able file reader"""

    def __init__(self, database):
        self._handle = open(database, 'rb')
        self._size = os.fstat(self._handle.fileno()).st_size

    def __getitem__(self, key):
        if isinstance(key, slice):
            self._handle.seek(key.start)
            return self._handle.read(key.stop - key.start)
        elif isinstance(key, int):
            self._handle.seek(key)
            return self._handle.read(1)
        else:
            raise TypeError("Invalid argument type.")

    def rfind(self, needle, start):
        """Reverse find needle from start"""
        self._handle.seek(start)
        pos = self._handle.read(self._size - start - 1).rfind(needle)
        if pos == -1:
            return pos
        return start + pos

    def size(self):
        """Size of file"""
        return self._size

    def close(self):
        """Close file"""
        self._handle.close()
